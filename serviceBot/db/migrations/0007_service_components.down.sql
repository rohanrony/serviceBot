-- Explicit rollback discards new snapshot metadata; booking/reservation rows remain.
ALTER TABLE service_requests DROP COLUMN IF EXISTS service_components;
