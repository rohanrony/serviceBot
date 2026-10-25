# Email business branding

## Route and requested outcome

Small change: replace application branding in recipient-visible email copy with the existing
configured business name. The requested Davidson display name is **Davidson CarCare**.
This changes presentation; booking, delivery routing and authorization semantics remain intact.

Stage: implemented and reviewed; preparing authorized branch publication. Follow `execution-handoff.md`.

## Workspace

- Worktree: `/Users/rohanroy/Coding/voiceService/.worktrees/email-business-branding`
- Branch: `codex/email-business-branding`
- Base: source `HEAD`, `33e08f753b81df255dbdee43cd1f4b82d067b9b8`
- Source: `dev-v0.19.3-prompt-and-catalogue-sync`; unrelated working changes were not copied.
- Scope owner: email formatting in `serviceBot/services/gmail.py`, the Gmail test endpoint in
  `serviceBot/api/portal.py`, and invitation copy in `serviceBot/services/google_calendar.py`.

## Evidence and boundaries

Source inspection at the base revision found:

- Both Gmail senders construct `From: serviceBot Notification <address>` (`gmail.py:112,165`).
- Booking email subjects use `[serviceBot]`; booking/admin HTML footers contain serviceBot
  (`gmail.py:236,352,536`). Plain bodies currently omit business identity.
- `/api/v1/portal/gmail-config/test` uses `[BayFull] Gmail Integration Test Email`
  (`portal.py:2500`). The existing browser test decodes the sent MIME but checks only a substring.
- Agent calendar invitations use BayFull in appointment titles and descriptions, including the
  multi-service helper (`google_calendar.py:264-268,347,363,411`). Admin invitations use
  serviceBot (`gmail.py:638-642`). `sendUpdates=all` on the single-event paths requests attendee
  invitations. The multi-service helper's notification behavior must remain as currently coded.
- The outbox calls these email/calendar adapters (`outbox_worker.py:418,431,449,623`), so updating
  only direct emails would leave old branding in Calendar invitation emails.
- The existing Business Name setting supplies `business_name`. Its default is `Davidson Car Care`
  (`portal.py:354`), with a space. Do not silently rewrite saved business settings. For exact
  Davidson CarCare acceptance, the target's existing Business Name must have that exact value;
  verifying/changing a live setting is a separate operational step. Other configured names must
  continue to work. No new per-email brand setting or universal Davidson hardcode is needed.

Graph evidence was unavailable: the project was absent from `list_projects`; indexing was refused
because this repository is outside the graph server's allowed roots. A coverage request did not
complete and was cancelled. These findings use direct source inspection, not graph completeness.
Production configuration, delivered emails and provider accounts were not inspected.

## Acceptance contracts

| ID | Observable result | Tests to extend before implementation |
| --- | --- | --- |
| EB/AC1 | With Business Name `Davidson CarCare`, both system and connected-agent MIME senders identify Davidson CarCare while preserving the sender address. Booking and admin emails include that name in subjects, HTML and plain text; generated branding contains neither BayFull nor serviceBot. Preserve admin urgency/copy labels and all booking details. | Gmail MIME/service tests; existing OAuth routing, suppression and failure tests. Add a transport assertion for the connected-agent sender if existing tests mock it. |
| EB/AC2 | Clicking Test Email after saving/reloading settings sends a MIME message with `[Davidson CarCare] Gmail Integration Test Email` and matching sender/body branding. Success/failure/disconnected UI outcomes remain truthful. | Existing Gmail endpoint test and parameterized browser journey, decoding the actual captured Gmail transport payload. |
| EB/AC3 | New agent/admin appointment and callback invitation titles/descriptions use Davidson CarCare. Multi-service unified and fallback event copy follows the same rule. Preserve event IDs, times, durations, attendees, cancellation lookup compatibility and notification flags. | Existing agent/admin event payload and multi-service tests; extend callback/fallback assertions. |

Use one shared resolver for the existing business name, trimming surrounding whitespace and
using neutral `Service Notifications` when absent, blank or non-string. Never restore the old
product names as a fallback. Escape the name for HTML; safely format the MIME display name and
remove CR/LF from header values. Test a second business name to prevent hardcoding Davidson.
Assertions about forbidden branding concern generated copy, not arbitrary customer-entered text.

Unchanged behavior is part of acceptance: same recipient addresses and send count; disabled mail
and disabled routine admin copies send nothing; escalation remains eligible; provider errors do
not become success; no configuration writes during rendering/sending; booking persistence and
calendar identity/cancellation rules remain intact. No backfill or rename of existing events.
SMS, WhatsApp, voice prompts, portal navigation branding and repository/package names are outside
this change. There is no new product UI; extend the existing Test Email browser journey.

## Validation and execution gates

`test-coverage.yaml` maps the implemented assertions to each contract. The executor recorded
Red/Green results; the reviewer confirmed the cleanup regression is fixed in both adapters. Run unit/API and browser suites separately, followed by
the complete offline `./run_tests.sh --verify`. The destination needs its own offline environment;
the source virtualenv was used only for collection, with a sanitized environment and no fixtures run.

Maintained manual provider cases are EB01–EB03 in `live-scenarios.md`. They require separate
environment/recipient/budget authorization and independent Gmail/inbox/Calendar reads. Before
implementation handoff, also refresh the affected shared `live_simulations/scenarios.json`
C01/C02/C04 assertions so the existing campaign cannot accept stale branding. Paid runs remain
separate. Unknown provider costs block live readiness.

Implementation review: no remaining review findings. The business-name-only calendar deletion
match was removed; permanent agent/admin regression assertions preserve unrelated meetings.
Shared C01/C02/C04 scenario assertions were updated. Prior executor full-suite results are recorded
in the coverage matrix; the exact outgoing commit and current target require fresh verification.
Live Business Name confirmation and EB01–EB03 execution remain separately pending.

Planning validation on 2026-10-25: sanitized `pytest --collect-only -q -p no:cacheprovider`
collected 76 unit/API cases across the five named test modules and 4 browser cases in
`e2e/test_admin_mail_oauth.py`, in separate successful processes. An initial combined collection
was rejected by the suite lifecycle guard and was corrected; no fixtures/tests executed.
YAML parsing, 3 acceptance mappings, 15 referenced source test definitions, 3 linked manual
scenario IDs and whitespace checks on all four documents passed. No application code changed.

- Offline: pending exact-candidate publication verification; prior executor suites and focused reviewer checks passed.
- Live: pending; no provider calls or independent delivery read-back.
- Committed: no. Pushed: no. Merged: no. Deployed: no.
