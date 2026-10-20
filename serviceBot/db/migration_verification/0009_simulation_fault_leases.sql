-- Read-only structural verification: expect both tables and no invalid bindings.
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' AND table_name IN ('simulation_fault_leases','simulation_fault_journal')
ORDER BY table_name;
SELECT handle FROM simulation_fault_leases
WHERE (request_id IS NULL) <> (reservation_id IS NULL)
   OR (request_id IS NULL) <> (outbox_id IS NULL)
   OR (outbox_id IS NULL) <> (outbox_payload_hash IS NULL)
   OR (phase='cleaned' AND service_id IS NOT NULL)
   OR (phase IN ('bound','committed') AND request_id IS NULL)
   OR (mode='calendar_once' AND response_loss_consumed_at IS NOT NULL)
   OR (mode='response_loss_once' AND fault_consumed_at IS NOT NULL);
SELECT handle FROM simulation_fault_leases WHERE phase <> 'cleaned' AND service_id IS NULL;
SELECT l.handle FROM simulation_fault_leases l
JOIN outbox_notifications o ON o.id=l.outbox_id
WHERE o.request_id IS DISTINCT FROM l.request_id OR o.event_type<>'calendar_projection';
