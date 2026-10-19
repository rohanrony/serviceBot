# Validation

Use the existing `.venv`, local disposable PostgreSQL fixtures and installed Chromium. No real Google mail or other provider calls are permitted.

1. `./run_tests.sh --file tests/test_gmail_oauth_only.py` before implementation must fail at the intended contracts.
2. `./run_tests.sh --file tests/test_gmail_oauth_only.py tests/test_gmail_service.py tests/test_gmail_integration.py tests/test_portal_subtabs.py tests/test_sla_escalation_admin_email.py` must pass after implementation.
3. `./run_tests.sh --file e2e/test_admin_mail_oauth.py e2e/test_admin_mail_delivery.py e2e/test_voice_and_reporting.py e2e/test_integrations.py` covers browser status/save/reload/test outcomes and existing Google callbacks.
4. Validate changed Python and JavaScript syntax, Ruff changed-line findings, JSON and `git diff --check`.

Browser acceptance uses real local HTTP and configuration storage, with only the Google HTTP transport captured and asserted, including decoded MIME content, auth headers and persisted staff credentials. It is not proof of live delivery.
