# Implementation Plan: Configurable Business Time Zone Settings & System-Wide Timezone Linking

**Branch**: `005-configurable-business-timezone` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-configurable-business-timezone/spec.md`

## Summary

Implement a centralized business timezone architecture across backend and frontend services. Introduce `business_timezone` (default: `"America/New_York"`) in `serviceBot/config.json`, exposed and editable via `/config` and `/sms/config` endpoints with a dedicated selector in the Portal Settings UI. Create a centralized `serviceBot/services/timezone_service.py` to eliminate hardcoded fixed offsets (`timedelta(hours=-4)`) and statically assumed Eastern strings across booking, availability, quiet hours, Google Calendar sync, reminders, and SLAs. Link frontend portal formatting (`serviceBot/static/app.js`) to the configured business timezone using `Intl.DateTimeFormat`, guaranteeing that all displayed appointment schedules, call logs, and SMS timestamps are rendered in the business's operational timezone regardless of client browser local timezone.

## Technical Context

**Language/Version**: Python 3.13 / FastAPI, Vanilla JavaScript (ES6+)  
**Primary Dependencies**: `zoneinfo` (Python Standard Library), `psycopg2`, `Intl.DateTimeFormat` (Web API)  
**Storage**: `serviceBot/config.json`, PostgreSQL (`service_requests`, `call_logs`, `sms_conversations`)  
**Testing**: `pytest`, `./run_tests.sh`  
**Target Platform**: Linux (Render) / macOS  
**Project Type**: Voice AI Backend, Telephony Service & Management Portal  
**Performance Goals**: Timezone resolution overhead < 0.5ms; zero external network calls for timezone math  
**Constraints**: Zero regression on existing booking, reminder, or availability tests; strict compliance with VoiceAI Constitution v1.2.0 (TDD, deterministic time handling, offline mocks)

## Constitution Check

*GATE: Must pass before implementation. Re-check after Phase 1 design.*

- [x] **Principle I (Simple Architecture & Clear Ownership)**: Single authoritative owner for timezone operations created in `serviceBot/services/timezone_service.py`. All subsystems (booking, calendar, quiet hours, reminders, portal) consume this service rather than inventing ad-hoc timezone logic.
- [x] **Principle II (Reliable State & Provider Operations)**: Eliminates fixed 4-hour offsets that break during DST transitions. Bookings, quiet hour releases, and calendar sync use dynamic IANA timezone calculations, ensuring durable and idempotent scheduling.
- [x] **Principle III (Privacy & Trusted Integrations)**: Timezone configuration is validated against valid IANA names; prevents injection or malformed strings.
- [x] **Principle IV (Strict Test-First Development & Contract Coverage)**: Authored unit and integration tests in `tests/test_configurable_business_timezone.py` before modifying application code, asserting failure before implementation and passing cleanly afterwards.
- [x] **Principle V (Observable Calls & Human Recovery)**: Settings API returns explicit validation messages for unsupported timezones; Portal UI clearly communicates the operational timezone and UTC offset to operators.

## Project Structure

### Documentation (this feature)

```text
specs/005-configurable-business-timezone/
├── spec.md              # Feature specification & requirements
├── plan.md              # Implementation plan (this file)
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Actionable task list
```

### Source Code & Tests

```text
serviceBot/
├── config.json                             # Default "business_timezone": "America/New_York"
├── services/
│   ├── timezone_service.py                 # NEW: Centralized business timezone service
│   ├── calendar_availability.py            # Updated: Uses timezone_service for slots & 4h buffer
│   ├── booking.py                          # Updated: Uses timezone_service for business TZ
│   ├── quiet_hours.py                      # Updated: Evaluates quiet hours via timezone_service
│   ├── sms_reminders.py                    # Updated: Calculates reminder cadences via timezone_service
│   ├── google_calendar.py                  # Updated: Uses business_timezone for event creation
│   ├── calendar_sync.py                    # Updated: Uses business_timezone for sync offsets
│   └── gmail.py                            # Updated: Formats emails in business_timezone
├── api/
│   └── portal.py                           # Updated: Config endpoints support business_timezone
└── static/
    ├── index.html                          # Updated: Time Zone dropdown in Portal Settings
    └── app.js                              # Updated: Date formatting linked to business timezone
tests/
└── test_configurable_business_timezone.py  # NEW: Comprehensive TDD suite for timezone linking
```

## Implementation Phases

### Phase 1: Centralized Timezone Service (`serviceBot/services/timezone_service.py`)
1. Create `timezone_service.py`:
   - `get_business_timezone_str() -> str`: Reads `business_timezone` from `config.json` with fallback to `"America/New_York"`.
   - `get_business_zoneinfo() -> ZoneInfo`: Returns validated `ZoneInfo` instance.
   - `validate_timezone(tz_name: str) -> bool`: Verifies `tz_name` exists in IANA database.
   - `now_in_business_tz() -> datetime`: Returns timezone-aware current datetime.
   - `to_business_tz(dt: datetime) -> datetime`: Safely converts naive (assumed business or UTC as appropriate) or aware datetime to business timezone.
   - `to_utc(dt: datetime) -> datetime`: Converts datetime to UTC.
   - `get_utc_offset_str(dt: Optional[datetime] = None) -> str`: Returns current offset string (e.g. `"-04:00"` or `"-05:00"`).

### Phase 2: Configuration API & Settings UI
1. Update `serviceBot/config.json` with `"business_timezone": "America/New_York"`.
2. Update `serviceBot/api/portal.py`:
   - Add `business_timezone: Optional[str] = None` to `ConfigUpdatePayload`.
   - In `update_config()` and `/sms/config` PUT: Validate timezone string via `timezone_service.validate_timezone()`. Raise 400 if invalid.
   - Persist to `config.json`.
3. Update `serviceBot/static/index.html`:
   - Add "Business Time Zone" select dropdown with common US/major IANA timezones (Eastern, Central, Mountain, Pacific, Alaska, Hawaii, UTC) and an option for custom IANA timezone.
4. Update `serviceBot/static/app.js`:
   - Populate and bind `business_timezone` field in Settings form.
   - Cache `activeBusinessTimezone` globally (defaulting to `"America/New_York"`).
   - Update `formatLocalTimestamp()`, `formatBookingTimeRange()`, `formatShortDate()`, and other date renderers to use `Intl.DateTimeFormat('en-US', { timeZone: activeBusinessTimezone, ... })`.

### Phase 3: Backend Services Refactoring & Linking
1. Refactor `calendar_availability.py`:
   - Replace static `timedelta(hours=-4)` with `get_business_zoneinfo()`.
   - Calculate current time in business timezone for 4-hour lead time checks.
2. Refactor `booking.py`:
   - Dynamically load business timezone in `parse_booking_time()` and slot validation.
3. Refactor `quiet_hours.py`:
   - Use `get_business_zoneinfo()` for quiet hours check (21:00 to 08:00) and morning release calculation.
4. Refactor `sms_reminders.py`:
   - Use `now_in_business_tz()` in `shop_now_naive()` and `parse_business_datetime()`.
5. Refactor `google_calendar.py`, `calendar_sync.py`, and `gmail.py`:
   - Use dynamic business timezone string and offset.

### Phase 4: Test-Driven Verification (TDD)
1. Author comprehensive test suite in `tests/test_configurable_business_timezone.py`.
2. Confirm initial failure (Red).
3. Implement services, API, and frontend linking (Green).
4. Run full test suite `./run_tests.sh` to ensure 0 regressions.
