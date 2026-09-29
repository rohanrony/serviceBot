"""Periodic recovery for recent ElevenLabs calls missing from local call history."""

import os
import time
import threading
import httpx
from typing import Optional, Dict, Any

from serviceBot.logger import get_logger
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import lookup_customer_by_phone, create_crm_note
from serviceBot.services.webhook_security import WebhookEventStore

logger = get_logger("call_sync")

_sync_worker_thread: Optional[threading.Thread] = None
_sync_worker_stop_event = threading.Event()


def sync_recent_elevenlabs_calls(limit: int = 100) -> int:
    """Reconcile missing calls in the configured lookback window, paging provider results."""
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "").strip()

    if not api_key or not agent_id:
        logger.error("[call_sync] Missing API credentials; reconciliation cannot run.")
        return 0

    try:
        lookback_days = int(os.getenv("CALL_SYNC_LOOKBACK_DAYS", "7"))
        if lookback_days < 1:
            raise ValueError("lookback must be positive")
    except ValueError:
        logger.error("[call_sync] CALL_SYNC_LOOKBACK_DAYS must be a positive integer.")
        return 0

    page_size = max(1, min(int(limit), 100))
    call_start_after = int(time.time()) - lookback_days * 24 * 60 * 60
    headers = {"xi-api-key": api_key}
    synced_count = 0
    conversation_count = 0
    cursor = None
    seen_cursors = set()
    list_url = "https://api.elevenlabs.io/v1/convai/conversations"

    try:
        with httpx.Client(timeout=10.0) as list_client, httpx.Client(timeout=15.0) as detail_client:
            while True:
                params = {
                    "agent_id": agent_id,
                    "page_size": page_size,
                    "call_start_after_unix": call_start_after,
                }
                if cursor:
                    params["cursor"] = cursor

                try:
                    response = list_client.get(list_url, headers=headers, params=params)
                except Exception:
                    logger.exception("[call_sync] Failed to contact the ElevenLabs conversations API.")
                    break
                if response.status_code != 200:
                    logger.error("[call_sync] Conversations API returned HTTP %s.", response.status_code)
                    break

                try:
                    page = response.json()
                except ValueError:
                    logger.exception("[call_sync] Conversations API returned invalid JSON.")
                    break
                if not isinstance(page, dict):
                    logger.error("[call_sync] Conversations API returned an unexpected response shape.")
                    break

                conversations = page.get("conversations") or []
                if not isinstance(conversations, list):
                    logger.error("[call_sync] Conversations API returned an invalid conversation list.")
                    break
                conv_ids = [
                    conversation["conversation_id"]
                    for conversation in conversations
                    if isinstance(conversation, dict)
                    if conversation.get("conversation_id")
                    and conversation.get("status") not in {"initiated", "in-progress", "processing"}
                ]
                conversation_count += len(conv_ids)

                if conv_ids:
                    try:
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as db_cursor:
                                placeholders = ", ".join(["%s"] * len(conv_ids))
                                db_cursor.execute(
                                    f"SELECT call_id FROM crm_notes WHERE call_id IN ({placeholders});",
                                    tuple(conv_ids),
                                )
                                existing_ids = {
                                    row["call_id"] for row in db_cursor.fetchall() if row.get("call_id")
                                }
                    except Exception:
                        logger.exception("[call_sync] Database lookup failed; this reconciliation pass stopped.")
                        break

                    missing_ids = [conversation_id for conversation_id in conv_ids if conversation_id not in existing_ids]
                    if missing_ids:
                        logger.info("[call_sync] Reconciling %d missing call(s) from this page.", len(missing_ids))
                    for conversation_id in missing_ids:
                        try:
                            detail_url = f"https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}"
                            detail_response = detail_client.get(detail_url, headers=headers)
                            if detail_response.status_code != 200:
                                logger.warning(
                                    "[call_sync] Conversation detail request returned HTTP %s for %s.",
                                    detail_response.status_code,
                                    conversation_id,
                                )
                                continue
                            conversation_data = detail_response.json()
                            if conversation_data.get("status") in {"initiated", "in-progress", "processing"}:
                                continue
                            if _ingest_conversation(conversation_id, conversation_data):
                                synced_count += 1
                        except Exception:
                            logger.exception("[call_sync] Failed to reconcile conversation %s.", conversation_id)

                if not page.get("has_more"):
                    break
                next_cursor = page.get("next_cursor")
                if not next_cursor or next_cursor in seen_cursors:
                    logger.error("[call_sync] Provider pagination stopped without a new cursor.")
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
    except Exception:
        logger.exception("[call_sync] Reconciliation pass failed.")

    if synced_count:
        logger.info(
            "[call_sync] Reconciled %d of %d eligible conversation(s) in the lookback window.",
            synced_count,
            conversation_count,
        )
    else:
        logger.info(
            "[call_sync] Reconciliation complete: scanned %d eligible conversation(s); no missing calls saved.",
            conversation_count,
        )
    return synced_count


def _ingest_conversation(conversation_id: str, cdata: Dict[str, Any]) -> bool:
    """Parses and ingests a single conversation payload into customers and crm_notes."""
    event_store = WebhookEventStore()
    event_id = conversation_id
    # Provider details can change after completion; keep the reconciliation event hash stable.
    raw_payload = {"conversation_id": conversation_id}

    # Do not write call data unless the durable idempotency claim succeeds.
    claimed = event_store.begin("elevenlabs_reconciliation", event_id, raw_payload)
    if not claimed:
        return False

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
    logger.info("[call_sync] Background worker loop started (interval=%ss).", interval_seconds)
    while not _sync_worker_stop_event.is_set():
        try:
            sync_recent_elevenlabs_calls(limit=100)
        except Exception:
            logger.exception("[call_sync] Error in worker loop.")
        if _sync_worker_stop_event.wait(interval_seconds):
            break


def start_call_sync_worker(interval_seconds: int = 60):
    """Launches the background synchronization worker daemon."""
    global _sync_worker_thread
    if _sync_worker_thread is not None and _sync_worker_thread.is_alive():
        return

    _sync_worker_stop_event.clear()
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
    global _sync_worker_thread
    _sync_worker_stop_event.set()
    thread = _sync_worker_thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=5)
    if thread is None or not thread.is_alive():
        _sync_worker_thread = None
