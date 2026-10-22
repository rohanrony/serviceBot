# Research & Technical Considerations

## Research Findings

1. **Business Profile & Config Canonicalization**:
   - `config.json` is loaded via `serviceBot.api.portal.load_config()` and saved via `save_config()`.
   - `sms_config` table in PostgreSQL has a `support_phone_number` column.
   - When Business Settings is saved, both `config.json` and `sms_config` in the DB should be synchronized.
   - When legacy SMS configuration updates `support_phone_number`, it must also update `config.json`.
   - Removing `sms-config-support-phone`, `sms-config-shop-address`, `sms-config-maps-url`, `sms-config-timezone` from Notifications tab prevents conflicting edits.

2. **Save Confirmation & Provider Synchronization**:
   - When saving Business Settings, prompt regeneration is now the default outcome, but replacing the AI greeting and instructions requires deliberate user consent.
   - A modal dialog ensures confirmation before any HTTP request or file write.
   - If voice provider sync (ElevenLabs) fails or credentials are unset, the backend must return a distinct `provider_sync` status (`unavailable` or `failed`) while returning `saved: true`. The frontend must display this clearly without false claims.

3. **Generic Intake & Vehicle Record Prevention**:
   - In `serviceBot/services/booking.py`, `create_service_request` currently had logic inserting a vehicle row if `collect_vehicle_details` was true, falling back to "Vehicle", "Standard", 2020.
   - With generalized intake, if `vehicle_details` is not provided (or empty), `vehicle_id` is kept `None`. No fabricated vehicle record is inserted.
   - The prompt instructs the agent to ask for missing required fields using configured labels, but not to solicit optional fields.

4. **Service Request Date-First Flow**:
   - Replacing `<input type="datetime-local" id="sr-booking-time">` with:
     - `<input type="date" id="sr-booking-date">`
     - `<button id="sr-check-slots-btn">Check Availability</button>`
     - `<select id="sr-slots-dropdown">`
   - Form state management must ensure that when date, duration, service, or agent change, stale slot selections are invalidated and cleared.
   - Existing appointments load with their scheduled date and slot visible. Unscheduled requests remain unscheduled.
   - Changes to an existing appointment time require customer consent.

5. **Staff Member Validation**:
   - `StaffAgentCreate` model in Pydantic validates `email` (valid email string) and `phone_number` (valid phone string).
   - `StaffAgentUpdate` model: if `email` or `phone_number` is provided as empty/blank string, raises 400 Bad Request. If older records have NULL email/phone, updating `name` or `role` does not trigger validation failure on the missing fields.

6. **Inbound Message Acknowledgment**:
   - In `serviceBot/services/sms_classifier.py`, line 148 had hardcoded: `"Message received. For urgent scheduling assistance, please contact dispatch."`
   - This must resolve the configured support helpline, falling back to `"Message received."` if unset.
