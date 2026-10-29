# Admin notification email persistence

Route: bug fix. Restore the established save/reload contract without changing
notification recipients, delivery policy, credentials, or provider requests.

## Evidence and scope

- Reported on the deployed `/portal/#config/gmail` page on 2026-10-25:
  Save reports success, but a refresh shows the previous admin email.
- A bounded read of the deployed Gmail configuration API returned the same
  previous email displayed by the page. No production configuration was changed.
- The existing local browser save/reload test and an isolated API/file read-back
  both pass for a sequential save.
- A deterministic offline reproduction confirms a lost update:
  `refresh_gmail_token` reads the full configuration before requesting a token;
  an admin saves a newer email while that request is in flight; refresh then
  writes its older snapshot back with the token. The email save returned 200
  before its value was overwritten.
- This confirms a local defect, not the cause of the reported deployed incident.
  The user subsequently authorized read-only ADS Render diagnosis. The save and
  following read returned 200 on the same instance; no system Gmail refresh was
  logged in the queried window. The service runs on Free compute and its local
  configuration is also lost across spin-down/restart. See `diagnosis.md` for
  bounded query parameters, timestamps, log IDs, observations, and limitations.
- Graph discovery was attempted, but this checkout is outside the graph server's
  allowed roots. Evidence comes from direct source reads and offline executions.

## Acceptance and invariants

AC1: A successful admin email save survives an overlapping Gmail token refresh,
a fresh API/file read, and a complete browser reload. A successful refresh stores
its new access token and expiry without replacing newer notification settings.
A rejected refresh leaves the saved email and existing token fields unchanged.
The refresh token, business settings, notification policy, and external request
payload are preserved. Saving configuration must not send notifications.

Only local configuration persistence is changed. No production repair,
publication, deployment, recipient change, or live provider call is authorized.

## Validation

Tests and Red/Green evidence are tracked in `test-coverage.yaml` under AC1.
The permanent API regression first failed because a fresh read returned the old
email after a successful save; the rejected-refresh case passed. After the fix,
the focused browser interleaving test passed. A first combined focused run found
test configuration leaking into a later default-setting assertion; the new test
now uses per-test temporary configuration and prompt files.

The complete `./run_tests.sh --verify --tb=short -q` then passed all 2,488
unit/integration cases and all 716 E2E cases, with both suite exits zero. This
includes both refresh response cases, token-only update assertions, ordinary
save/reload, and the overlapping background-refresh browser journey. Logs and
JUnit evidence are retained in `scratch/admin-email-persistence-verify.log`,
`scratch/unit-results.xml`, and `scratch/e2e-results.xml`. Python compile checks,
coverage YAML validation, and scoped whitespace checks also passed; Ruff is not
installed in the existing environment.

Offline: the recorded working tree based on
`c04d72c8b237820ef72e7c5da2c5bf747327b54f` passed. Current candidate verification
is pending after a concurrent workflow changed HEAD to `33e08f753b81df255dbdee43cd1f4b82d067b9b8`.
Live-provider acceptance: not required
for this local persistence contract; no provider request or delivery behavior
changes. Production diagnosis has a confirmed lifecycle-durability gap. After the
user explicitly designated the recipient and authorized one save, the deployed
browser save and full-page reload succeeded at 19:17 UTC, with matching 200-status
server logs. Other visible configuration values were unchanged. The original
immediate failure was not reproduced; the lifecycle-durability gap remains.
Committed/Pushed: the shared portal helper was included in the concurrent
workflow's `33e08f7` commit; the complete Gmail fix and regressions remain
uncommitted and are not published. Merged: no complete fix. Deployed: no complete
fix; the latest live deploy was independently rechecked at 17:57 UTC.

## Implementation and limits

- Google refresh now merges only its encrypted access token and expiry into the
  latest configuration, instead of saving the snapshot taken before the request.
- A shared reentrant lock serializes portal configuration reads/writes and the
  merge across this process's request handlers and background threads.
- The existing file format, Google request, refresh token, and recipient policy
  are preserved. The token-refresh fix alone needs no database migration.
- This lock is in-process. It does not establish durable or shared configuration
  across Render restarts or separate instances. Current deployed topology is one
  Free instance; the configuration's lifecycle-durability gap is confirmed.
- Scope review checked the token-only patch, lock reentrancy, real persisted
  read-back, deterministic interleaving, isolated fixtures, retained assertions,
  and preservation of the checkout's unrelated dirty work. No actionable review
  findings remain within the bounded token-refresh persistence fix. The broader
  deployed persistence problem remains unresolved: durable storage is missing,
  and the original POST's intended/submitted email was not captured.


## Current integration candidate status — 2026-10-27

The token-only Gmail refresh behavior and its API/browser regression coverage are included in the local `integrate/recent-prior-changes-20261027` candidate through the Oct 25 admin-refresh branch snapshot (`b7854c3`, merged at `2abb0ed`). The snapshot tree matches the Oct 25 remote commit tree. The combined candidate has not been pushed, merged, or deployed. Exact-candidate offline verification remains pending; the standalone receipt below does not verify this combined candidate.

## Durable recipient persistence follow-up — 2026-10-28

The repeated reversion is explained by the Free service storing the recipient in
its local `serviceBot/config.json`. That filesystem is not durable across Render
spin-downs, restarts, or deploys. The token-refresh merge fix above addresses a
separate in-process lost-update race and does not cover this lifecycle reset.

The local follow-up adds a singleton PostgreSQL setting for the admin recipient.
The settings API reads this value in preference to the JSON copy and writes it
before returning success. The JSON value remains a one-time fallback until the
first durable save, which preserves the existing initial configuration. Admin
email and Google Calendar attendee paths read the same database-backed value.
The migration enables RLS and revokes direct API-role access to the table.

The new API regression reproduced the reset locally before the implementation:
after Save returned 200, restoring the pre-save JSON file made a fresh GET return
`old-admin@example.test` instead of `new-admin@example.test`. The new migration,
API/provider/browser assertions, and focused verification are tracked under AC2
in `test-coverage.yaml`. No live database migration, production write, commit,
push, merge, or deployment was performed in this follow-up.
