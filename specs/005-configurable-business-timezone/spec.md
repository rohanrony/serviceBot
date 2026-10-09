# Feature Specification: Configurable Business Time Zone Settings & System-Wide Timezone Linking

**Feature Branch**: `005-configurable-business-timezone`  
**Created**: 2026-10-08  
**Status**: Draft  
**Target Version**: `v0.9.0`  
**Author / PM**: AI Product Management Co-Pilot & Engineering  
**Input**: User description: "Allow for configuring the time zone in the settings. All the time zones will be linked, and whatever is shown in the app should also be in the relevant time zone. The time zone for this business is Eastern Time, and let's just ensure that is shown appropriately everywhere. It has to be processed accordingly."

---

## 1. Executive Summary & Value Proposition

### 1.1 Problem Statement
Currently, date and time operations across the VoiceAI platform exhibit multiple points of divergence and hardcoding:
1. **Hardcoded Fixed Offsets in Backend**: Multiple services (`booking.py`, `calendar_availability.py`, `google_calendar.py`, `calendar_sync.py`, `gmail.py`, `queries.py`) hardcode fixed offsets like `timedelta(hours=-4)` or static strings like `"America/New_York"`. Fixed 4-hour offsets break during Daylight Saving Time (DST) transitions (EST is UTC-5 while EDT is UTC-4).
2. **No Setting in Portal**: Shop administrators have no ability to configure or view their business timezone in the portal settings (`config.json` has no `business_timezone` setting).
3. **Browser Time Drift in Frontend Portal**: The frontend dashboard (`app.js`) formats timestamps using the client device's browser local timezone (`new Date()`, `d.getHours()`, `toLocaleTimeString()`). If a shop administrator or remote supervisor opens the portal from Pacific Time (UTC-7) or another timezone, appointments booked for "10:00 AM Eastern" appear as "7:00 AM", creating operational confusion.
4. **Disconnected Subsystems**: Quiet hours, booking lead times (4-hour buffer), reminder cadences, Google Calendar sync, and escalation SLAs each manage their own timezone logic independently rather than subscribing to a single linked business timezone source of truth.

### 1.2 Proposed Solution
Implement a **Configurable Business Time Zone Architecture with Centralized Linking**:
1. **Configurable Setting in Settings/Portal**: Add `business_timezone` (default: `"America/New_York"`) to `config.json`, exposed via `GET /config` and updateable via `POST /config` (and `sms/config`), with a dedicated Time Zone dropdown selector in the Portal Settings UI.
2. **Linked Backend Time Zone Engine**: Create a centralized `timezone_service` (or `time_utils`) that provides:
   - Dynamic `ZoneInfo` lookup based on the configured `business_timezone`.
   - Robust DST handling (accurate UTC offsets regardless of winter/summer).
   - Standardized conversions between UTC storage and business wall-clock time.
3. **Linked Processing Across All Backend Workflows**:
   - Availability checking & slot generation in `calendar_availability.py` and `booking.py`.
   - Business operating hours (7:00 AM - 6:00 PM) and 4-hour minimum booking lead time.
   - Quiet hours evaluation (21:00 - 08:00) and release scheduling in `quiet_hours.py`.
   - SMS reminder cadences & SLA escalation timers in `sms_reminders.py`.
   - Google Calendar event creation, syncing, and Gmail notification bodies.
4. **Linked Display in Frontend App**:
   - Update `app.js` date/time formatters (`formatLocalTimestamp`, `formatBookingTimeRange`, `formatShortDate`, `formatRelativeTime`) to format all displayed appointment times, call logs, SMS thread timestamps, and audit traces using the configured `business_timezone` via `Intl.DateTimeFormat(..., { timeZone: businessTimezone })`.
   - The default business timezone is Eastern Time (`America/New_York`), ensuring consistent display and processing immediately.

---

## 2. User Scenarios & Acceptance Criteria

### User Story 1 - Admin Configures Shop Time Zone in Portal Settings (Priority: P1)

As a shop administrator, I want to view and configure my shop's business time zone from the Portal Settings, so that the platform operates according to our facility's geographical time zone without requiring code changes.

**Why this priority**: Without configurable settings, multi-region deployment or changing shop locations requires hardcoded code edits.

**Independent Test**: Load the portal settings tab, change the time zone from `America/New_York` to `America/Chicago`, save settings, and verify `GET /config` returns `business_timezone: "America/Chicago"`.

**Acceptance Scenarios**:
1. **Given** an administrator opens the Portal Settings (Config tab), **When** the page loads, **Then** the Business Time Zone dropdown reflects the currently configured timezone (defaulting to `"America/New_York"` - Eastern Time).
2. **Given** an administrator selects a new timezone (e.g. `"America/Chicago"`) and clicks Save, **When** the request completes, **Then** `config.json` is updated with `business_timezone: "America/Chicago"`, a success notification is shown, and the UI adapts its display formatting immediately.
3. **Given** an invalid or empty timezone string is submitted, **When** validation occurs, **Then** the system rejects invalid IANA timezone identifiers with HTTP 400 or defaults safely to `"America/New_York"`.

---

### User Story 2 - Backend Booking & Availability Linked to Configured Time Zone (Priority: P1)

As a customer or AI voice assistant booking an appointment, I want calendar availability, operating hours, and the 4-hour advance booking restriction to be evaluated against the configured business time zone, so that booking logic respects the shop's true local clock.

**Why this priority**: Booking conflicts, invalid slot generation, and lead-time violations occur if the backend checks against UTC or an unlinked fixed offset.

**Independent Test**: Request availability with the business timezone configured to Eastern Time (`America/New_York`). Verify slot availability strictly falls within 7:00 AM - 6:00 PM Eastern, and the 4-hour lead time restriction enforces `now_eastern + 4 hours`.

**Acceptance Scenarios**:
1. **Given** current wall-clock time is 9:00 AM Eastern Time, **When** a caller asks for an appointment at 11:00 AM on the same day, **Then** the system rejects it because it is within the 4-hour lead-time window in Eastern Time.
2. **Given** a business timezone configured as Eastern Time (`America/New_York`), **When** availability slots are generated for a given date, **Then** the slots are anchored to Eastern wall-clock hours (e.g. 7:00 AM to 6:00 PM ET) and correctly handle DST (EDT UTC-4 vs EST UTC-5).
3. **Given** an appointment is booked for "2026-10-15 10:00:00" in Eastern Time, **When** stored and synced to Google Calendar, **Then** the event timeZone is explicitly `"America/New_York"` and its start ISO string reflects the proper offset.

---

### User Story 3 - Quiet Hours & Reminder Escalation Linked to Configured Time Zone (Priority: P1)

As a customer and technician, I want SMS notifications and reminder escalation to respect the shop's quiet hours and business operating hours in the configured business timezone, so that messages are never dispatched in the middle of the night.

**Why this priority**: Principle V and Principle II require reliable notifications and respecting quiet hours based on the business's actual operational timezone.

**Independent Test**: Evaluate quiet hours at 10:00 PM Eastern Time when `business_timezone` is `"America/New_York"`. Verify quiet hours evaluation returns `True`, and messages are held until 8:00 AM Eastern the next morning.

**Acceptance Scenarios**:
1. **Given** current time is 22:30 in the configured business timezone, **When** a notification is evaluated by `quiet_hours.py`, **Then** it is identified as inside quiet hours (21:00 - 08:00 business local time) and deferred.
2. **Given** deferred notifications awaiting morning release, **When** the scheduled release time arrives at 08:00 in the configured business timezone, **Then** notifications are released for delivery.
3. **Given** a technician SLA timer configured for shop operating hours, **When** calculating deadline cutoffs, **Then** elapsed operating hours are computed based on the shop's local opening and closing times in the configured business timezone.

---

### User Story 4 - Consistent Time Display Across All Portal Views (Priority: P1)

As a shop manager viewing the portal from any device or time zone, I want all appointment dates, call logs, SMS thread messages, and audit trail entries to display consistently in the shop's configured business time zone, so that I see the exact times that technicians and customers experience.

**Why this priority**: Without timezone-linked display, managers viewing the portal from a different timezone see shifted appointment times, causing missed appointments and dispatch errors.

**Independent Test**: Mock the browser timezone to Pacific Time (`America/Los_Angeles`). Open an appointment booked for 2:00 PM Eastern (`America/New_York`). Verify the dashboard table, appointment card, and drawer display "2:00 PM", explicitly in Eastern Time (or with an ET badge/indicator).

**Acceptance Scenarios**:
1. **Given** an appointment booked for 2:00 PM Eastern Time, **When** rendered in the Appointments Table, Calendar View, or Details Drawer, **Then** the displayed time is "2:00 PM" formatted in the configured business timezone.
2. **Given** an inbound customer call received at 14:15 UTC (10:15 AM Eastern), **When** rendered in the Call Logs table, **Then** the timestamp displays "10:15 AM" in the business timezone.
3. **Given** the business timezone is configured to Eastern Time, **When** an administrator updates the timezone in Settings to Central Time, **Then** all displayed times across the portal update to reflect Central Time.

---

## 3. Edge Cases & Boundary Conditions

1. **Daylight Saving Time (DST) Transitions**:
   - In Spring (clocks move forward 1 hour): 2:00 AM becomes 3:00 AM. Appointment slots around this transition must be valid wall-clock times in `zoneinfo.ZoneInfo("America/New_York")`.
   - In Autumn (clocks fall back 1 hour): 1:00 AM to 2:00 AM repeats. The system must disambiguate or store ISO timestamps with proper UTC offset (e.g. `2026-11-01T10:00:00-05:00`).
2. **Invalid or Unrecognized Time Zone String**:
   - If an admin submits an invalid string (e.g., `"Invalid/Zone"` or `"ET"`), the backend must reject it with HTTP 400 or fallback gracefully to `"America/New_York"` with a clear log warning, never crashing server processes.
3. **Legacy Data Without Timezone Offsets**:
   - Existing database records with naive strings (e.g., `"2026-10-09 10:00:00"`) must be interpreted as wall-clock times in the configured business timezone rather than assumed UTC.
4. **Offline & Network-Isolated Environment**:
   - Python's standard `zoneinfo` module reads system `tzdata`. If running in restricted containers without system tzdata, ensure `tzdata` PyPI package is available or fallbacks operate reliably.
5. **Concurrent Configuration Updates**:
   - If the business timezone is updated while an appointment is being booked, atomic transactions and refreshed config ensure subsequent lookups immediately use the updated timezone.

---

## 4. Requirements

### Functional Requirements

- **FR-001**: System MUST store and manage `business_timezone` (default: `"America/New_York"`) in `config.json`.
- **FR-002**: System MUST expose `business_timezone` via `GET /config` and allow updating it via `POST /config`.
- **FR-003**: System MUST provide a dedicated "Business Time Zone" configuration control in Portal Settings with support for standard IANA timezones (including Eastern, Central, Mountain, Pacific, Alaska, Hawaii, and UTC).
- **FR-004**: System MUST validate configured timezone strings against valid IANA timezones using Python's `zoneinfo` module before persisting.
- **FR-005**: System MUST provide a centralized timezone helper module (`serviceBot/services/timezone_service.py`) that returns the active business `ZoneInfo` instance and helper methods for converting naive wall-clock datetimes, UTC datetimes, and formatting ISO strings.
- **FR-006**: Availability checking in `serviceBot/services/calendar_availability.py` MUST resolve operating hours and the 4-hour lead time buffer using the centralized `business_timezone`.
- **FR-007**: Appointment booking in `serviceBot/services/booking.py` MUST parse and validate requested appointment slots in the configured `business_timezone`.
- **FR-008**: Quiet hours evaluation in `serviceBot/services/quiet_hours.py` MUST evaluate windows and morning release times using the configured `business_timezone` instead of static `TIMEZONE_NY`.
- **FR-009**: SMS reminders and escalation scheduling in `serviceBot/services/sms_reminders.py` and `serviceBot/api/portal.py` MUST compute deadlines and cutoff windows in the configured `business_timezone`.
- **FR-010**: Google Calendar integration (`google_calendar.py`, `calendar_sync.py`) and Gmail notifications (`gmail.py`) MUST use the configured `business_timezone` identifier and accurate dynamic DST offset.
- **FR-011**: Frontend Portal (`app.js`) MUST retrieve the configured `business_timezone` and format all displayed timestamps (Appointments, Call Logs, SMS threads, Audit Traces) using `Intl.DateTimeFormat` configured with that timezone.
- **FR-012**: If no timezone is set or an unrecognized string is present, the system MUST default safely to `"America/New_York"`.

---

## 5. Key Entities & Data Schema

### 5.1 Configuration (`config.json`)
```json
{
  "business_timezone": "America/New_York",
  "business_name": "Davidson Car Care",
  "business_hours_start": 7,
  "business_hours_end": 18
}
```

### 5.2 Common Supported Timezones
| IANA Identifier | Display Label | Standard Offset |
|---|---|---|
| `America/New_York` | Eastern Time (ET) - Default | UTC-5 / UTC-4 (DST) |
| `America/Chicago` | Central Time (CT) | UTC-6 / UTC-5 (DST) |
| `America/Denver` | Mountain Time (MT) | UTC-7 / UTC-6 (DST) |
| `America/Phoenix` | Mountain Time - Arizona (No DST) | UTC-7 |
| `America/Los_Angeles` | Pacific Time (PT) | UTC-8 / UTC-7 (DST) |
| `America/Anchorage` | Alaska Time (AKT) | UTC-9 / UTC-8 (DST) |
| `Pacific/Honolulu` | Hawaii-Aleutian (HST) | UTC-10 |
| `UTC` | Coordinated Universal Time | UTC+0 |

---

## 6. Success Criteria

### Measurable Outcomes
- **SC-001**: 100% of date/time operations in booking, availability, quiet hours, and reminders link dynamically to the configured `business_timezone`.
- **SC-002**: Portal Settings updates to `business_timezone` persist across server restarts and propagate immediately without requiring application reboot.
- **SC-003**: 100% of displayed appointment times and timestamps in the Portal UI match the business timezone regardless of client browser local timezone.
- **SC-004**: Zero DST transition errors during standard-to-daylight shifts (dynamic `zoneinfo` replaces static `timedelta(hours=-4)`).
- **SC-005**: All existing and newly authored automated unit and integration tests under `./run_tests.sh` pass cleanly with zero regressions.

---

## 7. Assumptions & Dependencies
- Default business timezone is Eastern Time (`America/New_York`).
- Python 3.9+ built-in `zoneinfo` module is available and used for all timezone operations.
- The browser environment supports standard `Intl.DateTimeFormat` with the `timeZone` option (supported in all modern browsers).
- Database appointments table stores `booking_time` as ISO strings or timestamp fields; any naive representations are anchored to the configured business timezone.
