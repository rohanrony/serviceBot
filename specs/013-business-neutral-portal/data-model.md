# Data Model: Business-Neutral Intake & Simplified Portal

## Schemas & Entities

### 1. `config.json`
Configuration keys:
- `business_name` (string): Business display name
- `business_address` (string): Physical address
- `google_maps_url` (string): Google Maps URL or navigation link
- `business_timezone` (string): Valid IANA timezone
- `support_phone_number` (string): Canonical customer support helpline
- `portal_base_url` (string): Base URL for notification links
- `business_profile` (object):
  - `industry` (string): Type of business
  - `collect_vehicle_details` (bool): Legacy automotive switch
  - `intake_fields` (array of IntakeField):
    - `key` (string, snake_case pattern `^[a-z][a-z0-9_]{0,39}$`)
    - `detail_type` (string enum: `general`, `asset_type`, `brand`, `model`, `serial_number`)
    - `label` (string, 1..80 chars)
    - `type` (string enum: `text`, `number`)
    - `required` (bool)

### 2. Database Entities (Existing Schema Reused)

- `sms_config`:
  - `support_phone_number` (VARCHAR(50)): Kept in sync with `config.json` canonical value.

- `service_requests`:
  - `customer_id` (INT)
  - `vehicle_id` (INT, nullable): NULL for generic requests without vehicle data.
  - `intake_data` (JSONB): Key-value pairs matching configured `intake_fields`.
  - `booking_type` (VARCHAR): `appointment` or `callback`.
  - `booking_time` (TIMESTAMP): Scheduled time in business timezone / UTC.
  - `status` (VARCHAR): `pending`, `confirmed`, `completed`, `cancelled`, etc.

- `staff_agents`:
  - `id` (INT)
  - `name` (VARCHAR)
  - `role` (VARCHAR)
  - `email` (VARCHAR): Required for new staff.
  - `phone_number` (VARCHAR): Required for new staff.
  - `is_active` (BOOLEAN)

- `vehicles`:
  - Existing table preserved. Only populated if automotive vehicle details are genuinely provided; never fabricated with dummy records for generic business intake.
