-- Record a verified native calendar deletion without violating projection states.
ALTER TABLE appointment_reservations
    DROP CONSTRAINT IF EXISTS appointment_reservations_calendar_integration_status_check;
ALTER TABLE appointment_reservations
    ADD CONSTRAINT appointment_reservations_calendar_integration_status_check
    CHECK (calendar_integration_status IN ('PENDING_CALENDAR', 'CREATED', 'FAILED', 'DELETED'));

ALTER TABLE mock_calendar_slots
    DROP CONSTRAINT IF EXISTS mock_calendar_slots_calendar_integration_status_check;
ALTER TABLE mock_calendar_slots
    ADD CONSTRAINT mock_calendar_slots_calendar_integration_status_check
    CHECK (calendar_integration_status IN ('NOT_REQUIRED', 'PENDING_CALENDAR', 'CREATED', 'FAILED', 'DELETED'));
