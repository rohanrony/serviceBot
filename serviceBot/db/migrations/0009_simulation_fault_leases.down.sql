-- Never erase unresolved owned-resource provenance during rollback.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM simulation_fault_leases WHERE phase <> 'cleaned') THEN
        RAISE EXCEPTION 'Simulation leases require owned cleanup before rollback';
    END IF;
END $$;
DROP TABLE IF EXISTS simulation_fault_journal;
DROP TABLE IF EXISTS simulation_fault_leases;
