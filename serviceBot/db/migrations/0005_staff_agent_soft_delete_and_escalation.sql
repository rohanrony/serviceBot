-- Migration: 0005_staff_agent_soft_delete_and_escalation
-- Adds is_active column to staff_agents for soft deletion support, avoiding foreign key constraint violations
-- on historical appointment_reservations and appointment_reservation_segments.

ALTER TABLE staff_agents
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_staff_agents_is_active
    ON staff_agents(is_active);
