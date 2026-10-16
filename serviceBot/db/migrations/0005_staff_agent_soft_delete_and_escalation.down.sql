-- Migration Rollback: 0005_staff_agent_soft_delete_and_escalation
DROP INDEX IF EXISTS idx_staff_agents_is_active;
ALTER TABLE staff_agents DROP COLUMN IF EXISTS is_active;
