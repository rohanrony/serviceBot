# Implementation Plan: OAuth-only admin mail

**Date**: 2026-10-19 | **Spec**: [spec.md](spec.md)

## Summary
Remove the SMTP option, payload fields, transport implementation, and routing branches. Keep the existing Google API owners and OAuth lifecycle.

## Technical Context
Python/FastAPI/Pydantic, plain JavaScript and HTML; existing JSON configuration and PostgreSQL Google accounts. Pytest and Chromium acceptance tests run offline against isolated configuration and disposable PostgreSQL. No dependency, service, or database schema additions. No latency behavior changes.

## Constitution Check
Pre-design and post-design: passes I–V. Existing mail service owns delivery; rejected requests have no effects; no credentials are logged or migrated outside configuration; test-first API/service and browser coverage; truthful test failures. No new schema or migration. Real provider operations are excluded.

## Project Structure
- `serviceBot/api/portal.py`: OAuth-only payload (Literal selector default oauth2; forbidden extras), settings output/defaults, legacy field cleanup on save, Google-only test endpoint.
- `serviceBot/services/gmail.py`: remove SMTP helper/import; always use system Google for booking fallback and admin first attempt; retain connected staff fallback.
- `serviceBot/static/index.html`, `serviceBot/static/app.js`: remove selector, SMTP/sender controls and legacy help; show existing Google status/help; send oauth2 payloads.
- `serviceBot/config.json`: remove only obsolete SMTP fields and update selector without exposing or changing other values.
- `tests/test_gmail_oauth_only.py`, existing Gmail/subtab/escalation tests: invalid requests, persisted cleanup and credential preservation, delivery routing and failure paths.
- `e2e/test_admin_mail_oauth.py`: legacy settings render, save/reload, connection status and test outcome with only Google HTTP transport captured; verify decrypted token headers and decoded MIME content.
- `e2e/test_admin_mail_delivery.py`: real database credentials, system/staff Google routing and failure outcomes, with exact provider requests and unchanged persisted state asserted.
- `e2e/test_voice_and_reporting.py`: replace obsolete app-password round trip with Google credential masking contract.
- `docs/specs/api_spec.md`: reconcile published settings contract and migration impact.

## Phases
1. Define bounded requirements and contracts.
2. Add failing service/API and browser contracts; capture intended failures.
3. Remove legacy paths and update obsolete tests without weakening supported behavior.
4. Run full relevant mail/subtab/escalation suites and browser/API acceptance, static validation, then converge.

## Complexity Tracking
No exceptions or new infrastructure. Code graph indexing/coverage is unavailable because this root is excluded; source searches and exact reads supply evidence.
