# Admin notification email persistence

The admin notification email saved in the portal could return to the checked-in
address after the service's local configuration file reset. The supplied
screenshot showed the admin notification settings and the value that kept
returning.

## Diagnosis

The Gmail settings API stored the recipient in `serviceBot/config.json`. The
Render Free service uses an ephemeral filesystem, so a restart, spin-down, or
deploy can restore the file to its initial value. An isolated regression
reproduces the behavior: after Save succeeds, restoring the pre-save JSON makes
a fresh API read return the old address. The original report's precise triggering
lifecycle event and submitted recipient were not captured.

A separate local race also existed: an in-flight Gmail token refresh could write
an old configuration snapshot after an admin save. The existing token-only
refresh fix addresses that race; durable storage addresses the repeated reset.

## Change

The portal now stores the admin recipient in a singleton PostgreSQL settings
row. A saved database value takes precedence over JSON and is used by system
admin email and Google Calendar attendee paths. JSON remains a fallback only
before the first durable save. API reads and writes return an error when the
settings database is unavailable instead of showing stale data or reporting a
successful save.

Migration `0012_admin_notification_settings.sql` enables row-level security and
revokes direct access from API roles. The migration has a rollback and a
read-only verification companion. Notification preferences, sender settings,
OAuth credentials, and provider request behavior remain unchanged.

Calendar events created by the service carry a stable private ownership marker.
Cleanup also recognizes narrowly shaped legacy generated events after a business
name change, while preserving unrelated meetings that only contain generic
words such as “Booking” or “Callback.”

## Acceptance and verification

AC1 covers a save during a Gmail token refresh, including successful and
rejected refresh responses and a complete browser reload. AC2 covers a saved
recipient after JSON reset, database failure behavior, provider recipient
selection, and migration structure. The detailed assertions and current full
suite results are recorded in `test-coverage.yaml`.

The exact candidate must pass `./scripts/verify_change.sh` against the current
`main` commit before publication. No live database migration or manual
deployment is part of this change.
