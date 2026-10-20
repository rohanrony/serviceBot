-- No signatures, credentials, or raw transcripts are retained.
CREATE TABLE IF NOT EXISTS authenticated_webhook_ingress (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'elevenlabs'),
    event_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    verified_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, event_id),
    CHECK (event_id = conversation_id)
);
