# Story 1: SMS Configuration & Notification Matrix

## User Story
As an Administrator, I want to configure SMS notification rules, reminder timings, quiet hours, test whitelists, and support contact details via a web UI settings page, so that I can control who receives text messages without deploying code changes.

## Sub-tasks & Checklist

- [ ] **Task 1.1: Database Schema Migrations**
  * File: `serviceBot/db/connection.py`
  * Add new tables to `DDL_SCHEMA`:
    * `sms_config` — quiet hours, support number, auto-responder template, environment mode (see SMS Spec §7.1)
    * `sms_matrix_rules` — event × role toggle matrix with UNIQUE constraint (see SMS Spec §7.2)
    * `sms_whitelist` — phone numbers for staging test allowlist (see SMS Spec §7.3)
    * `sms_log` — per-message delivery tracking with Twilio SID, status, error codes (see SMS Spec §5.3)
    * `sms_reminders` — scheduled reminder jobs with status lifecycle (see SMS Spec §3.2)
    * `sms_conversations` — two-way thread state per customer phone (see SMS Spec §7.6)
    * `sms_messages` — inbound/outbound message log for Live Inbox (see SMS Spec §7.7)
  * Add `_safe_alter` migrations for existing tables:
    * `staff_agents`: Add `phone_number VARCHAR(50) DEFAULT NULL` (E.164 format, required for agent SMS)
    * `customers`: Add `sms_opt_in BOOLEAN DEFAULT TRUE` (required for TCPA compliance)
    * `service_requests`: Expand status CHECK constraint to include `confirmed` and `cancelled_by_customer`
  * Seed `sms_matrix_rules` with default values matching the notification matrix in SMS Spec §2.2.
  * Seed `sms_config` with a single default row (quiet hours 21:00–08:00, threshold 12h, environment PRODUCTION).

- [ ] **Task 1.2: Portal Configuration API**
  * File: `serviceBot/api/portal.py`
  * Add `GET /api/portal/sms-settings` to fetch current `sms_config` row and all `sms_matrix_rules`.
  * Add `PUT /api/portal/sms-settings` to update `sms_config` fields and matrix toggles.
  * Add `GET /api/portal/sms-whitelist` to list all whitelisted numbers.
  * Add `POST /api/portal/sms-whitelist` to add a phone number to the whitelist.
  * Add `DELETE /api/portal/sms-whitelist/{id}` to remove a whitelisted number.

- [ ] **Task 1.3: Automated Unit & Integration Tests**
  * File: `tests/test_sms_config.py`
  * Test default `sms_config` row is created on DB init.
  * Test default `sms_matrix_rules` seed matches the spec matrix.
  * Test updating matrix toggles via REST API.
  * Test whitelist CRUD API behavior.
  * Test that `staff_agents.phone_number` column exists and accepts E.164 format.
  * Test that `customers.sms_opt_in` defaults to `true`.
  * Test that `service_requests.status` now accepts `confirmed` and `cancelled_by_customer`.

- [ ] **Task 1.4: Admin Web UI Settings Page**
  * File: `serviceBot/static/` (Admin portal HTML/JS)
  * Add SMS Matrix Checkbox Table (Customer, Agent, Previous Agent, Admin × Events including compound `Rescheduled + Reassigned` row).
  * Add Quiet Hours & Reminder Time pickers.
  * Add Support Phone Number & Auto-Responder Template text fields.
  * Add Whitelist management table (Add/Remove phone numbers).

- [ ] **Task 1.5: Agent Onboarding Phone Field & Twilio Verification Flow**
  * File: `serviceBot/api/portal.py` & `serviceBot/static/`
  * Add mandatory `phone_number` field to Agent Onboarding API and UI form.
  * Implement endpoint `POST /api/portal/twilio/verify-caller-id` invoking Twilio `client.validation_requests.create(phone_number=..., friendly_name=...)` for test mode whitelisting.

## Verification Checklist
- Run `pytest tests/test_sms_config.py` to ensure all backend API tests pass.
- Verify GET and PUT endpoints return expected JSON structures.
- Verify new columns exist: `staff_agents.phone_number`, `customers.sms_opt_in`.
- Verify `service_requests` accepts `confirmed` and `cancelled_by_customer` status values.
