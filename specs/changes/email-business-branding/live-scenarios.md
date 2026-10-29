# Maintained manual email acceptance scenarios

Definition status: ready for execution planning, **not authorized to run**. These manual cases
exercise the email boundary without requiring an ElevenLabs call. Keep the shared campaign's
C01/C02/C04 branding assertions current during implementation as a separate maintenance step.

For every case, record target/environment/commit, case variant, timestamp/timezone, synthetic run
marker, approved account/recipient/calendar IDs, starting fixtures, configuration snapshot with
secrets redacted, expected provider requests and prohibited effects. The target Business Name
must be exactly `Davidson CarCare`. Do not silently change a live setting to make a case pass.
Use a non-production sandbox or separately approved test accounts; no unrelated customer data.

Costs are currently **unknown**, so live readiness is blocked. Before execution, document current
provider units and currency, account-specific estimate basis, uncertainty, per-case/total cap and
explicit authorization. No spending is authorized here. Stop on ambiguous charges or delivery,
retain the ledger and correlate provider IDs before any retry. Keep message acceptance, recipient
delivery and calendar persistence as distinct outcomes.

## EB01 — Direct notification branding

- Prerequisites: approved system and connected-agent Gmail accounts/scopes, independent inbox
  reader, one synthetic appointment, allowlisted agent/admin recipients, declared copy settings.
- Variants: system booking email; connected-agent booking email; admin copy enabled; admin
  copy disabled; escalation with routine copies disabled. Reuse the synthetic booking rather
  than creating an unrelated reservation for every email. Authorize each triggering operation.
- Action: trigger one corresponding notification per variant through supported application paths.
- Expected: From display identity, subject and generated HTML/plain text use Davidson CarCare;
  sender address, recipients, urgency markers and appointment details are correct. No generated
  BayFull/serviceBot branding. Disabled routine copies produce no separate admin-copy message.
- Read-back: retain sender Gmail message ID/RFC Message-ID and independently fetch recipient
  inbox MIME correlated by those IDs/run marker. Confirm expected number of messages, including
  absence of a prohibited admin copy within the declared observation window; disclose its limits.
- Cleanup: retain redacted MIME evidence and IDs; remove only approved run-owned messages and
  booking fixtures. Recover partial delivery by ID; do not replay an ambiguously sent message.

## EB02 — Portal Gmail test email

- Prerequisites: approved connected system account, allowlisted test recipient and inbox reader;
  Business Name configured correctly and freshly reloaded in the portal.
- Action: click Test Email exactly once. Do not book an appointment or invoke a voice provider.
- Expected: `[Davidson CarCare] Gmail Integration Test Email`; correct From display identity and
  body branding; one email; truthful application result; no booking/calendar/configuration mutation.
- Read-back: correlate sender message ID/RFC Message-ID to independently retrieved recipient MIME.
  Inspect Subject, From, To, HTML and plain text; a toast or Sent-folder row alone is insufficient.
- Cleanup: preserve redacted evidence, then remove only the run-owned test message if authorized.

## EB03 — Calendar invitation branding

- Prerequisites: approved agent/admin calendars, attendee inbox access, run-owned test slots,
  stable event identifiers and cleanup permissions; exact cases/triggering mutations authorized.
- Variants: agent and admin appointment; agent and admin callback; multi-service unified and
  fallback events. Inspect transport flags offline; do not inject live provider failures solely
  to force fallback. Exercise live fallback only if a supported, separately approved setup exists.
- Expected: Davidson CarCare in event titles/descriptions, correct services/times/durations and
  attendees, stable event identity and existing notification flags. Invitation emails are expected
  only where the original path requests attendee updates; do not add mail sends to obtain evidence.
- Read-back: independently fetch each event by calendar ID/event ID; correlate invitation ICS UID
  and attendee inbox MIME to that event and run marker. Inspect title/description branding in both.
  Do not use application rows or transcript text as proof of an invitation's arrival.
- Cleanup: save redacted event/inbox evidence; delete only recorded run-owned events using exact
  IDs and approved flags, then release owned booking fixtures. List every unremoved resource for
  recovery. Never search-and-delete unrelated events by branding or rewrite historical events.
