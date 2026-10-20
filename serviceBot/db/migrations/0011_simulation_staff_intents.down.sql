DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM simulation_staff_intents i
        WHERE EXISTS (SELECT 1 FROM staff_agents s WHERE s.id=(i.original_response->>'staff_id')::integer)
           OR EXISTS (SELECT 1 FROM services s WHERE s.id=(i.original_response->>'service_id')::integer)) THEN
        RAISE EXCEPTION 'Original simulation staff resources require cleanup before journal rollback';
    END IF;
END $$;
DROP TABLE IF EXISTS simulation_staff_intents;
DROP FUNCTION IF EXISTS reject_simulation_staff_intent_change();
