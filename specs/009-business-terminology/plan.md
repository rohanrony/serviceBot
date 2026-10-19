# Implementation Plan: Configurable business terminology and intake

## Technical Context
Existing Python/FastAPI, Pydantic, PostgreSQL, plain JavaScript portal; no new service.
`services/business_profile.py` owns profile defaults, validation, intake validation, neutral prompt/summary rendering. Portal handles configuration/forms; BookingService owns transactional persistence; telephony adapts configured data into existing booking entry points.

## Constitution Check
One shared validation owner; intake persisted inside booking transactions; validate before side effects; offline provider fakes; test-first lower-level and browser coverage; additive migration with verification and guarded rollback. No operational latency changes or external mutations. Gates pass before and after design.

## Design
- Preserve existing automotive mode for installations lacking a profile; explicit Config selection disables automotive requirements. Legacy table/tool/DOM names remain compatibility adapters.
- Add request `intake_data JSONB NOT NULL DEFAULT '{}'`, constrained to an object. Do not rename/drop legacy vehicle tables; generic requests have no vehicle. Reject rollback while nonempty intake exists.
- Config Business pane edits identity/industry, validated portal_base_url for notification links, automotive toggle, field rows. Stable keys survive label changes. User explicitly chooses prompt regeneration.
- New request and edit forms render configured fields safely with DOM text APIs; lists show structured intake. Removing a configured field never deletes recorded intake.
- Existing legacy booking adapter carries configured intake in `vehicle_details.intake_data` into the shared booking owner; no new scheduling owner. Store in every request creation path inside its transaction, including multi-agent plans and callbacks. Required validation is shared by portal and voice before mutation.
- Return schema from voice get_service_fields. Tool definitions add optional intake_data_json string for providers lacking arbitrary object support. Existing typed automotive parameters remain accepted.
- App-owned labels, summaries, email/calendar/SMS prose use Agent and neutral service terminology. Business-authored content remains editable; Config explains catalog/knowledge/template review.

## Test Layers
Unit/integration: config save/read/reject without mutation, data validation boundaries, generated prompts/summary, neutral text and tool schema, migration apply/guarded rollback, generic and legacy persistence.
Browser E2E: Services header, Business save/reload, custom field creation, request creation/edit/reload without vehicle, profile switch preserving history. Existing service/config/appointment journeys rerun.

## Project Structure
Changes: serviceBot/services/business_profile.py, api/portal.py, api/telephony.py, services/booking.py, db/queries.py, db/migrations/0010_business_intake*, static/index.html, static/app.js, app-owned copy in services and db, scripts/sync_elevenlabs_tools.py. Tests: tests/test_business_profile.py, e2e/test_business_profile.py plus relevant existing suites.
