-- Durable original ownership claims; never reconstruct a receipt from current rows.
CREATE TABLE IF NOT EXISTS simulation_staff_intents (
    run_id VARCHAR(80) PRIMARY KEY,
    intent_id UUID NOT NULL UNIQUE,
    original_response JSONB NOT NULL,
    mapping_snapshot CHAR(64) NOT NULL CHECK (mapping_snapshot ~ '^[0-9a-f]{64}$'),
    cleanup_complete BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (original_response->>'run_id'=run_id),
    CHECK (original_response->>'intent_id'=replace(intent_id::text,'-',''))
);
CREATE OR REPLACE FUNCTION reject_simulation_staff_intent_change() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    IF TG_OP='UPDATE' AND OLD.cleanup_complete=FALSE AND NEW.cleanup_complete=TRUE
       AND (to_jsonb(OLD)-'cleanup_complete')=(to_jsonb(NEW)-'cleanup_complete') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Original simulation staff ownership claims are immutable';
END $$;
CREATE TRIGGER simulation_staff_intents_immutable BEFORE UPDATE OR DELETE
    ON simulation_staff_intents FOR EACH ROW EXECUTE FUNCTION reject_simulation_staff_intent_change();
