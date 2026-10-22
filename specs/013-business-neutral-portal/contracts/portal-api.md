# Contract: Portal API Endpoints

## 1. Config Endpoints

### `GET /api/v1/portal/config`
Response: JSON dictionary including:
- `business_name`: string
- `business_address`: string
- `google_maps_url`: string
- `business_timezone`: string
- `support_phone_number`: string (canonical support helpline)
- `portal_base_url`: string
- `business_profile`: BusinessProfile object
- `system_prompt`: string
- `first_message`: string
- (all existing operational settings)

### `POST /api/v1/portal/config`
Payload `ConfigUpdatePayload`:
- Accepts `business_address`, `google_maps_url`, `business_timezone`, `support_phone_number` / `support_helpline`
- When `support_phone_number` is provided: updates `config.json` AND synchronizes with `sms_config` in database.
- `regenerate_business_prompt`: bool (when true, regenerates prompt and greeting).
Response:
```json
{
  "success": true,
  "saved": true,
  "provider_sync": {
    "status": "synced" | "failed" | "unavailable",
    "message": "Voice provider synchronization details..."
  }
}
```

## 2. Staff Agent Endpoints

### `POST /api/v1/portal/agents`
Payload `StaffAgentCreate`:
```python
class StaffAgentCreate(BaseModel):
    name: str = Field(min_length=1)
    role: Optional[str] = "Service Advisor"
    email: str = Field(min_length=3)
    phone_number: str = Field(min_length=7)
```
Validation:
- Both `email` and `phone_number` must be nonblank, valid email and phone format.
- Rejection on blank or invalid format with 400 or 422 HTTP status.

### `PUT/PATCH /api/v1/portal/agents/{agent_id}`
Payload `StaffAgentUpdate`:
```python
class StaffAgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
```
Validation:
- If `email` or `phone_number` is passed as an empty/whitespace string, reject with 400 Bad Request ("Email/Phone cannot be cleared").
- If older profile has NULL email or phone in DB, and unrelated field is updated (e.g. `name="Alice"` while `email=None`), allow the update.

## 3. Service Catalogue Endpoints

### `GET /api/v1/portal/services`
Returns catalogue services with assigned agent IDs and names.

### `POST /api/v1/portal/services` and `PUT /api/v1/portal/services/{id}`
Preserves pricing, duration, and assigned staff agents. Requirement settings remain business-wide in `business_profile`.

## 4. Service Request Booking & Availability

### `GET /api/v1/portal/available-slots?date={YYYY-MM-DD}&duration_minutes={min}&staff_agent_id={id}`
Returns available slots with start and end times in business timezone.

### `POST /api/v1/portal/service-requests` & `PUT /api/v1/portal/service-requests/{id}`
- Atomic booking/rescheduling through `BookingService`.
- If modifying an existing appointment's scheduled time: requires customer consent flag (`customer_consent: true`).
- Invariant: Revalidate availability before committing; reject conflicting reservations without partial mutations.
