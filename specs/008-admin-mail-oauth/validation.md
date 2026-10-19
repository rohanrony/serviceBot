# Validation and convergence

Date: 2026-10-19. Tests use isolated local services and captured providers. No deployment, real email, account change or credential revocation. The user separately authorized committing and pushing the admin-mail branch without merging.

## Test-first evidence

- `./run_tests.sh --file tests/test_gmail_oauth_only.py`: before application edits, 26 failed / 8 passed. Failures demonstrate legacy selector exposure/acceptance, missing Google default and SMTP delivery selection. Evidence: `scratch/admin-mail-red-unit.log`.
- `./run_tests.sh --e2e e2e/test_admin_mail_oauth.py -x`: before application edits, browser fails because the legacy selector exists. Evidence: `scratch/admin-mail-red-browser.log`. The runner collects all e2e paths; final focused validation uses `--file`.
- Initial sandbox attempts could not reach local PostgreSQL (`Operation not permitted`); the same offline tests ran successfully with loopback access. Tests own disposable databases and isolated config; external providers were stubbed.
- Initial browser result assertions used the wrong toast ID; corrected to the existing `#app-toast` without weakening outcome assertions.

## Final results

- `./run_tests.sh --file tests/test_gmail_oauth_only.py tests/test_gmail_service.py tests/test_gmail_integration.py tests/test_portal_subtabs.py tests/test_sla_escalation_admin_email.py`: **69 passed**, one existing Starlette/httpx deprecation warning. Evidence: `scratch/admin-mail-final-unit.log`.
- `./run_tests.sh --file e2e/test_admin_mail_oauth.py e2e/test_voice_and_reporting.py e2e/test_integrations.py`: **35 passed**, including four actual Chromium settings journeys and existing Google callback/provider contracts. Evidence: `scratch/admin-mail-final-browser.log`.
- `node --check serviceBot/static/app.js`, Python AST parsing for all nine touched/new Python files, JSON parsing, config comparison preserving every unrelated value, and `git diff --check`: passed.
- `uvx --offline ruff check tests/test_gmail_oauth_only.py e2e/test_admin_mail_oauth.py`: passed. New test files formatted with Ruff.
- Ruff on existing touched Python files: no introduced diagnostic signatures against HEAD; 271 pre-existing diagnostics remain, with six removed. Full files are not lint-clean. Evidence: `scratch/admin-mail-ruff.json`, `scratch/admin-mail-ruff-comparison.json`.

## Requirement review

| Requirement | Evidence |
| --- | --- |
| FR-001 | Browser proves no SMTP/auth selector and visible Google status/help; save/reload persists recipient/enabled/agent selection. |
| FR-002 | Legacy config reads normalize to Google; invalid selectors/SMTP fields reject without writes/sends; saves remove old fields and preserve tokens, sender and unrelated config; Google secrets remain encrypted/masked. |
| FR-003 | API and browser assert connected success, send failure, disconnected rejection, and API provider exceptions. |
| FR-004 | Service contracts exercise missing/legacy/Google selectors, disabled/missing addresses, staff-first booking delivery, system fallback, and admin staff fallback success/failure/absence, with no SMTP connection. |
| FR-005 | Test-first evidence and final complete affected unit/API/browser suites above. |

## Convergence pass 1

Reviewed five functional requirements, three success criteria, five user-story acceptance scenarios, the plan's API/UI/delivery/storage/test boundaries, and all five constitution principles in the bounded scope. No missing, partial, contradictory, or unrequested work found. All tasks completed; no convergence tasks appended. This review uses direct source evidence: graph indexing and coverage calls were unavailable because the repository is excluded by the graph server's allowed-root configuration. No graph completeness claim is made.

## Operational limits

Old app-password-only installations must connect Google before sending. Existing Google credentials and staff-account fallback are preserved. Old clients selecting SMTP or submitting SMTP fields receive 422. Live Google delivery was not exercised; offline provider mocks prove routing and outcome handling only. The wider repository contains unrelated work, which was preserved.


## Test sufficiency review and convergence pass 2

The admin-mail patch was isolated from all other pending work and applied to a separate worktree based on current `origin/main` (074939e), on `refactor/admin-mail-oauth-only`. The original checkout and other issue commits were preserved.

- Service/API tests validate legacy, missing and Google selectors; rejected requests with no writes/sends; disabled/missing-address gates; Google credential preservation including client ID/secret; staff-first booking and system fallback; explicit failed/exceptional booking delivery; admin staff fallback success, denial and missing accounts.
- Browser tests perform actual local HTTP save/reload and assert persisted preferences. Connection tests execute the actual Google token/MIME/send path, intercepting only Google's HTTP transport, and verify Bearer headers, recipients, sender identity, subject/body and truthful success/failure UI with an enabled test button afterward.
- New database/provider acceptance exercises actual encrypted system and staff credentials with a disposable PostgreSQL database. It checks exact Google routing on success/403, decoded email contents, zero SMTP calls, unchanged credentials and unchanged stored configuration.
- Existing Google callbacks, secret encryption/masking, escalation notifications and worker/provider contracts remain in the full affected suites. Initial red tests prove the removal regression is observable. No new concurrency owner or schema was introduced; unrelated load/race suites would not test this removal contract.

Final exact-branch commands (run from `/private/tmp/voice-admin-mail-oauth-20261019`):

- `./run_tests.sh --file tests/test_gmail_oauth_only.py tests/test_gmail_service.py tests/test_gmail_integration.py tests/test_portal_subtabs.py tests/test_sla_escalation_admin_email.py`: **71 passed**, one existing deprecation warning. Original-workspace evidence: `scratch/admin-mail-branch-unit.log`.
- `./run_tests.sh --file e2e/test_admin_mail_oauth.py e2e/test_admin_mail_delivery.py e2e/test_voice_and_reporting.py e2e/test_integrations.py`: **39 passed**, including four Chromium journeys and four additional persisted Google delivery scenarios. Original-workspace evidence: `scratch/admin-mail-branch-acceptance.log`.
- `uvx --offline ruff check tests/test_gmail_oauth_only.py e2e/test_admin_mail_oauth.py e2e/test_admin_mail_delivery.py` and `node --check serviceBot/static/app.js`: passed. Test files formatted with Ruff.

Reconciled plan, quickstart and T011–T013 with the stronger tests. Reviewed all five functional requirements, three success criteria, five acceptance scenarios and plan boundaries again: no remaining actionable gaps. All 13 tasks complete. Live Google delivery remains outside offline test evidence.
