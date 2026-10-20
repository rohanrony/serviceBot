-- Read-only: expect both checks to return no invalid rows.
SELECT run_id FROM simulation_staff_intents
WHERE original_response->>'run_id' IS DISTINCT FROM run_id
   OR original_response->>'intent_id' IS DISTINCT FROM replace(intent_id::text,'-','')
   OR jsonb_typeof(original_response->'receipt') IS DISTINCT FROM 'string';
SELECT 'missing_or_invalid_immutability_trigger' AS violation
WHERE NOT EXISTS (
    SELECT 1 FROM pg_trigger t
    WHERE t.tgrelid='simulation_staff_intents'::regclass
      AND t.tgname='simulation_staff_intents_immutable'
      AND NOT t.tgisinternal AND t.tgenabled='O'
      AND t.tgfoid='reject_simulation_staff_intent_change()'::regprocedure
      AND t.tgtype=27
);
