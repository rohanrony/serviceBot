-- Development rollback only. Do not run in production without a reviewed backup.
UPDATE sms_conversations
   SET state = 'HANDOFF_REQUIRED'
 WHERE state = 'OUT_OF_BUSINESS_HOURS';

ALTER TABLE sms_conversations
    DROP CONSTRAINT IF EXISTS sms_conversations_state_check;
ALTER TABLE sms_conversations
    ADD CONSTRAINT sms_conversations_state_check
    CHECK (state IN ('AUTOMATED', 'HANDOFF_REQUIRED', 'IN_PROGRESS', 'RESOLVED'));

ALTER TABLE sms_log DROP COLUMN IF EXISTS channel;
ALTER TABLE sms_log DROP COLUMN IF EXISTS body;

DROP TABLE IF EXISTS webhook_events;
DROP TABLE IF EXISTS appointment_reservation_segments;
DROP TABLE IF EXISTS appointment_reservations;

ALTER TABLE service_requests DROP COLUMN IF EXISTS calendar_event_id;
ALTER TABLE service_requests DROP COLUMN IF EXISTS calendar_integration_status;
ALTER TABLE service_requests DROP COLUMN IF EXISTS booking_end_at;
ALTER TABLE service_requests DROP COLUMN IF EXISTS booking_start_at;

ALTER TABLE mock_calendar_slots DROP COLUMN IF EXISTS calendar_event_id;
ALTER TABLE mock_calendar_slots DROP COLUMN IF EXISTS calendar_integration_status;
ALTER TABLE mock_calendar_slots DROP COLUMN IF EXISTS service_request_id;
ALTER TABLE mock_calendar_slots DROP COLUMN IF EXISTS reservation_status;

