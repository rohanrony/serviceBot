# Routine admin email copies

**Route:** Small change — a single saved notification preference controls routine admin email copies at the shared sender; no database schema change is needed.

## Scope and acceptance

- **AC-1:** Routine admin email copies for bookings, callbacks, reschedules, reassignments, and cancellations are suppressed by default, including when an older configuration has no preference stored.
- **AC-2:** The Admin Mail page lets an administrator enable or disable routine copies; the saved choice survives reload, and enabling it restores the existing routine-copy behavior.
- **AC-3:** With routine copies disabled, an admin calendar invitation is still created for a booking and the escalation email remains governed by the existing Gmail and escalation-email settings.
- Agent/customer notifications, SMS, calendar event creation, and escalation policy are otherwise unchanged.

## Test mapping

- AC-1: sender policy test across routine event types; missing-setting default from configuration read.
- AC-2: Gmail configuration API persistence and browser save/reload tests.
- AC-3: escalation sender regression and captured outbox/calendar provider-boundary test.
- Live scenarios C01 and C44 cover routine booking and escalation provider outcomes; live execution remains separately authorized.
