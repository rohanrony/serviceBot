"""ElevenLabs conversation synchronization service and background reconciliation worker.

Provides automatic polling and reconciliation of completed conversations from ElevenLabs,
guaranteeing call history logs are never lost due to cold-starts, timeouts, or webhook drops.
"""

import os
import time
import threading
import httpx
from typing import Optional, List, Dict, Any

from serviceBot.logger import get_logger
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import lookup_customer_by_phone, create_crm_note
from serviceBot.services.webhook_security import WebhookEventStore

logger = get_logger("call_sync")

_sync_worker_thread: Optional[threading.Thread] = None
_sync_worker_running: bool = False


def sync_recent_elevenlabs_calls(limit: int = 20) -> int:
    """Polls ElevenLabs ConvAI for recent completed conversations and ingests any missing calls.

    Returns the number of calls newly synced and inserted into crm_notes.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "").strip()

    if not api_key or not agent_id:
        logger.debug("[call_sync] Missing ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID; skipping sync.")
        return 0

    headers = {"xi-api-key": api_key}
    list_url = f"https://api.elevenlabs.io/v1/convai/conversations?agent_id={agent_id}&page_size={limit}"

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(list_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"[call_sync] Failed to fetch conversations list: {resp.status_code} {resp.text}")
                return 0
            data = resp.json()
            conversations = data.get("conversations", [])
    except Exception as exc:
        logger.warning(f"[call_sync] Error contacting ElevenLabs API: {exc}")
        return 0

    if not conversations:
        return 0

    conv_ids = [c["conversation_id"] for c in conversations if c.get("conversation_id")]
    if not conv_ids:
        return 0

    # Query DB to find which conversations are already recorded in crm_notes
    existing_ids = set()
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                placeholders = ", ".join(["%s"] * len(conv_ids))
                cursor.execute(
                    f"SELECT call_id FROM crm_notes WHERE call_id IN ({placeholders});",
                    tuple(conv_ids)
                )
                rows = cursor.fetchall()
                existing_ids = {r["call_id"] for r in rows if r.get("call_id")}
    except Exception as exc:
        logger.error(f"[call_sync] Database error checking existing call IDs: {exc}")
        return 0

    missing_ids = [cid for cid in conv_ids if cid not in existing_ids]
    if not missing_ids:
        logger.debug(f"[call_sync] All {len(conv_ids)} recent conversations are already synced.")
        return 0

    logger.info(f"[call_sync] Found {len(missing_ids)} unsynced call(s) from ElevenLabs. Ingesting...")
    synced_count = 0

    with httpx.Client(timeout=15.0) as client:
        for cid in missing_ids:
            try:
                detail_url = f"https://api.elevenlabs.io/v1/convai/conversations/{cid}"
                d_resp = client.get(detail_url, headers=headers)
                if d_resp.status_code != 200:
                    logger.warning(f"[call_sync] Failed to fetch details for {cid}: {d_resp.status_code}")
                    continue
                cdata = d_resp.json()
                
                # Ingest single conversation
                if _ingest_conversation(cid, cdata):
                    synced_count += 1
            except Exception as exc:
                logger.error(f"[call_sync] Error syncing conversation {cid}: {exc}", exc_info=exc)

    logger.info(f"[call_sync] Successfully reconciled and saved {synced_count} missing call(s).")
    return synced_count


def _ingest_conversation(conversation_id: str, cdata: Dict[str, Any]) -> bool:
    """Parses and ingests a single conversation payload into customers and crm_notes."""
    event_store = WebhookEventStore()
    event_id = conversation_id
    raw_payload = {"type": "post_call_transcription", "data": cdata}

    # Claim event in event_store for auditability & deduplication
    try:
        claimed = event_store.begin("elevenlabs_reconciliation", event_id, raw_payload)
        if not claimed:
            # Already completed or in-flight
            return False
    except Exception as exc:
        logger.debug(f"[call_sync] Event store notice for {event_id}: {exc}")

    try:
        metadata = cdata.get("metadata") or {}
        phone_call = metadata.get("phone_call") or {}
        from_number = (
            phone_call.get("external_number")
            or metadata.get("from_number")
            or cdata.get("user_id")
            or "Unknown"
        )

        # Format transcript lines
        transcript_arr = cdata.get("transcript") or []
        transcript_lines = []
        for turn in transcript_arr:
            role = turn.get("role", "unknown")
            role_label = "User" if role == "user" else "Agent"
            msg = turn.get("message", "")
            transcript_lines.append(f"{role_label}: {msg}")
        transcript_text = "\n".join(transcript_lines)

        # Generate or use summary
        summary = ""
        if transcript_text.strip():
            try:
                from serviceBot.api.telephony import generate_service_summary
                summary = generate_service_summary(transcript_text)
            except Exception as sum_err:
                logger.warning(f"[call_sync] AI summary generation fallback: {sum_err}")
                summary = ""

        if not summary or not summary.strip():
            analysis = cdata.get("analysis") or {}
            summary = (
                analysis.get("transcript_summary")
                or analysis.get("summary")
                or "Call ended before completion; no service details were gathered."
            )

        # Look up or create customer
        from_number_to_use = from_number if from_number else "Unknown"
        customer = lookup_customer_by_phone(from_number_to_use)

        if not customer:
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute(
                        "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
                        ("Unknown Customer", from_number_to_use),
                    )
                    conn.commit()
                    customer_id = cursor.fetchone()["id"]
        else:
            customer_id = customer["customer_id"]

        # Insert CRM note
        create_crm_note(
            call_id=conversation_id,
            customer_id=customer_id,
            summary=summary,
            transcript=transcript_text,
        )

        event_store.complete("elevenlabs_reconciliation", event_id)
        logger.info(f"[call_sync] Successfully ingested call {conversation_id} for customer {customer_id}")
        return True
    except Exception as exc:
        try:
            event_store.fail("elevenlabs_reconciliation", event_id)
        except Exception:
            pass
        raise exc


def _worker_loop(interval_seconds: int):
    """Background polling loop."""
    logger.info(f"[call_sync] Background worker loop started (interval={interval_seconds}s).")
    while _sync_worker_running:
        try:
            sync_recent_elevenlabs_calls(limit=15)
        except Exception as exc:
            logger.error(f"[call_sync] Error in worker loop: {exc}", exc_info=exc)
        time.sleep(interval_seconds)


def start_call_sync_worker(interval_seconds: int = 60):
    """Launches the background synchronization worker daemon."""
    global _sync_worker_thread, _sync_worker_running
    if _sync_worker_thread is not None and _sync_worker_thread.is_alive():
        return

    _sync_worker_running = True
    _sync_worker_thread = threading.Thread(
        target=_worker_loop,
        args=(interval_seconds,),
        daemon=True,
        name="CallSyncWorkerThread"
    )
    _sync_worker_thread.start()
    logger.info("[call_sync] Call sync background thread launched.")


def stop_call_sync_worker():
    """Stops the background synchronization worker daemon."""
    global _sync_worker_running
    _sync_worker_running = False
