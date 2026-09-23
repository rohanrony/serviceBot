"""Provider webhook verification and durable replay protection."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Callable

from serviceBot.db.connection import dict_cursor, get_db_connection


class WebhookVerificationError(ValueError):
    """Raised when a provider request cannot be authenticated safely."""


class WebhookReplayConflictError(ValueError):
    """Raised when an event identifier is reused with a different payload."""


def is_test_environment() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST") or os.getenv("TESTING") == "1")


def canonical_twilio_url(request: Any) -> str:
    """Build the externally signed URL from an explicit public base URL."""
    public_base = os.getenv("TWILIO_WEBHOOK_BASE_URL", "").strip().rstrip("/")
    if not public_base:
        raise WebhookVerificationError("TWILIO_WEBHOOK_BASE_URL must be configured for webhook verification.")
    path = request.url.path
    query = request.url.query
    return f"{public_base}{path}{f'?{query}' if query else ''}"


def verify_twilio_request(request: Any, form_data: dict[str, Any]) -> None:
    """Validate an inbound Twilio request unless the explicit test bypass is active."""
    if is_test_environment():
        return
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    signature = request.headers.get("X-Twilio-Signature")
    if not auth_token:
        raise WebhookVerificationError("TWILIO_AUTH_TOKEN must be configured for webhook verification.")
    if not signature:
        raise WebhookVerificationError("Missing X-Twilio-Signature header.")
    try:
        from twilio.request_validator import RequestValidator
    except ImportError as exc:  # pragma: no cover - packaging failure is deployment-specific
        raise WebhookVerificationError("The Twilio SDK is required for webhook verification.") from exc
    if not RequestValidator(auth_token).validate(canonical_twilio_url(request), form_data, signature):
        raise WebhookVerificationError("Invalid Twilio request signature.")


def _elevenlabs_secret() -> str:
    return (
        os.getenv("ELEVENLABS_WEBHOOK_SECRET", "").strip()
        or os.getenv("ELEVENLABS_CONVAI_WEBHOOK_SECRET", "").strip()
    )


def verify_elevenlabs_request(raw_body: bytes, signature_header: str | None) -> None:
    """Verify ElevenLabs' t=<unix>,v0=<hmac> signature over timestamp.body."""
    if is_test_environment():
        return
    secret = _elevenlabs_secret()
    if not secret:
        raise WebhookVerificationError("ELEVENLABS_WEBHOOK_SECRET must be configured for webhook verification.")
    if not signature_header:
        raise WebhookVerificationError("Missing ElevenLabs-Signature header.")

    fields: dict[str, list[str]] = {}
    for component in signature_header.split(","):
        key, separator, value = component.strip().partition("=")
        if not separator or not key or not value:
            continue
        fields.setdefault(key, []).append(value)
    timestamp_values = fields.get("t") or []
    signatures = fields.get("v0") or []
    if len(timestamp_values) != 1 or not signatures:
        raise WebhookVerificationError("Malformed ElevenLabs-Signature header.")
    try:
        timestamp = int(timestamp_values[0])
    except ValueError as exc:
        raise WebhookVerificationError("Malformed ElevenLabs signature timestamp.") from exc
    tolerance = int(os.getenv("ELEVENLABS_WEBHOOK_TOLERANCE_SECONDS", "300"))
    if abs(time.time() - timestamp) > tolerance:
        raise WebhookVerificationError("ElevenLabs webhook timestamp is outside the permitted tolerance.")

    signed_payload = str(timestamp).encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise WebhookVerificationError("Invalid ElevenLabs request signature.")


class WebhookEventStore:
    """Claims provider events before side effects and records their final state."""

    def __init__(
        self,
        connection_factory: Callable = get_db_connection,
        cursor_factory: Callable = dict_cursor,
    ):
        self._connection_factory = connection_factory
        self._cursor_factory = cursor_factory

    @staticmethod
    def _payload_hash(raw_payload: bytes | str | dict[str, Any]) -> str:
        if isinstance(raw_payload, dict):
            import json

            raw_payload = json.dumps(raw_payload, sort_keys=True, separators=(",", ":"))
        if isinstance(raw_payload, str):
            raw_payload = raw_payload.encode("utf-8")
        return hashlib.sha256(raw_payload).hexdigest()

    def begin(self, provider: str, event_id: str, raw_payload: bytes | str | dict[str, Any]) -> bool:
        """Claim a new event; return False for a completed/in-flight identical delivery."""
        if not event_id:
            raise WebhookVerificationError("Webhook event is missing its provider event identifier.")
        payload_hash = self._payload_hash(raw_payload)
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    INSERT INTO webhook_events (provider, event_id, payload_hash, status, updated_at)
                    VALUES (%s, %s, %s, 'PROCESSING', CURRENT_TIMESTAMP)
                    ON CONFLICT (provider, event_id) DO NOTHING
                    RETURNING id;
                    """,
                    (provider, event_id, payload_hash),
                )
                if cursor.fetchone():
                    return True
                cursor.execute(
                    """
                    SELECT payload_hash, status, updated_at
                    FROM webhook_events
                    WHERE provider = %s AND event_id = %s
                    FOR UPDATE;
                    """,
                    (provider, event_id),
                )
                existing = cursor.fetchone()
                if not existing:
                    raise WebhookReplayConflictError("Webhook event record could not be read after its uniqueness conflict.")
                if existing["payload_hash"] != payload_hash:
                    raise WebhookReplayConflictError("Webhook event identifier was reused with a different payload.")
                if existing["status"] == "FAILED":
                    cursor.execute(
                        """
                        UPDATE webhook_events
                        SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP, completed_at = NULL
                        WHERE provider = %s AND event_id = %s;
                        """,
                        (provider, event_id),
                    )
                    return True
                return False

    def complete(self, provider: str, event_id: str) -> None:
        self._set_status(provider, event_id, "COMPLETED", completed=True)

    def fail(self, provider: str, event_id: str) -> None:
        self._set_status(provider, event_id, "FAILED", completed=False)

    def _set_status(self, provider: str, event_id: str, status: str, *, completed: bool) -> None:
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    UPDATE webhook_events
                    SET status = %s,
                        updated_at = CURRENT_TIMESTAMP,
                        completed_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
                    WHERE provider = %s AND event_id = %s;
                    """,
                    (status, completed, provider, event_id),
                )
