-- Older code cannot represent verified deletion. Preserve an explicit failure
-- state rather than claiming the removed provider event still exists.
UPDATE service_requests SET calendar_integration_status = 'FAILED'
    WHERE calendar_integration_status = 'DELETED';
UPDATE appointment_reservations SET calendar_integration_status = 'FAILED'
    WHERE calendar_integration_status = 'DELETED';
UPDATE mock_calendar_slots SET calendar_integration_status = 'FAILED'
    WHERE calendar_integration_status = 'DELETED';

ALTER TABLE appointment_reservations
    DROP CONSTRAINT IF EXISTS appointment_reservations_calendar_integration_status_check;
ALTER TABLE appointment_reservations
    ADD CONSTRAINT appointment_reservations_calendar_integration_status_check
    CHECK (calendar_integration_status IN ('PENDING_CALENDAR', 'CREATED', 'FAILED'));

ALTER TABLE mock_calendar_slots
    DROP CONSTRAINT IF EXISTS mock_calendar_slots_calendar_integration_status_check;
ALTER TABLE mock_calendar_slots
    ADD CONSTRAINT mock_calendar_slots_calendar_integration_status_check
    CHECK (calendar_integration_status IN ('NOT_REQUIRED', 'PENDING_CALENDAR', 'CREATED', 'FAILED'));
