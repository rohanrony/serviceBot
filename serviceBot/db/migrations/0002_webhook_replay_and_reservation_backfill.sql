-- Make replay claims recoverable and protect parseable legacy bookings with
-- the same segment uniqueness model as new reservations.

ALTER TABLE webhook_events
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

DO $$
DECLARE
    legacy RECORD;
    reservation_id INTEGER;
    starts_at TIMESTAMP;
    duration INTEGER;
BEGIN
    FOR legacy IN
        SELECT sr.id, sr.staff_agent_id, sr.booking_time, sr.duration_minutes
        FROM service_requests sr
        WHERE sr.booking_type IN ('appointment', 'callback', 'appointment_and_callback')
          AND sr.staff_agent_id IS NOT NULL
          AND sr.booking_time ~ '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$'
          AND NOT EXISTS (
              SELECT 1
              FROM appointment_reservations ar
              WHERE ar.service_request_id = sr.id
          )
        ORDER BY sr.staff_agent_id, sr.booking_time, sr.id
    LOOP
        starts_at := legacy.booking_time::timestamp;
        duration := GREATEST(15, CEIL(COALESCE(legacy.duration_minutes, 60) / 15.0)::INTEGER * 15);

        IF NOT EXISTS (
            SELECT 1
            FROM appointment_reservation_segments segment
            WHERE segment.staff_agent_id = legacy.staff_agent_id
              AND segment.segment_start >= starts_at
              AND segment.segment_start < starts_at + make_interval(mins => duration)
        ) THEN
            INSERT INTO appointment_reservations (
                service_request_id, staff_agent_id, starts_at, ends_at,
                status, calendar_integration_status
            )
            VALUES (
                legacy.id, legacy.staff_agent_id, starts_at,
                starts_at + make_interval(mins => duration),
                'ACTIVE', 'PENDING_CALENDAR'
            )
            RETURNING id INTO reservation_id;

            INSERT INTO appointment_reservation_segments (reservation_id, staff_agent_id, segment_start)
            SELECT reservation_id, legacy.staff_agent_id, segment_start
            FROM generate_series(
                starts_at,
                starts_at + make_interval(mins => duration - 15),
                INTERVAL '15 minutes'
            ) AS segment_start;

            UPDATE service_requests
            SET booking_start_at = starts_at,
                booking_end_at = starts_at + make_interval(mins => duration),
                calendar_integration_status = 'PENDING_CALENDAR'
            WHERE id = legacy.id;
        ELSE
            -- Preserve conflicting historical records but make reconciliation visible.
            UPDATE service_requests
            SET calendar_integration_status = 'FAILED'
            WHERE id = legacy.id;
        END IF;
    END LOOP;
END $$;
