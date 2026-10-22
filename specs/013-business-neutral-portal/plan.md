# Implementation Plan: Generalize Business Configuration and Simplify Portal

**Branch**: `feat/business-neutral-portal-20261021` | **Date**: 2026-10-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/013-business-neutral-portal/spec.md`

## Summary

Centralize business configuration in Business Settings (address, maps link, timezone, support helpline), implement generic intake classification (stable key, detail types, business labels, text/number types, requirements), enforce date-first availability slot booking in service requests, modernize the service catalogue with business-wide asset details, streamline portal pages (SMS inbox, Admin help, hidden API keys pane, removed duplicate phone whitelist), enforce strict staff contact validation, and update inbound message acknowledgments to use the configured helpline.

## Technical Context

**Language/Version**: Python 3.11+, Vanilla JavaScript (ES2022+), HTML5 / CSS3  
**Primary Dependencies**: FastAPI, Pydantic v2, PostgreSQL (psycopg2 / asyncpg), Playwright (for E2E browser tests)  
**Storage**: `serviceBot/config.json`, PostgreSQL (`sms_config`, `service_requests`, `staff_agents`, `services`)  
**Testing**: `pytest`, `pytest-asyncio`, `playwright`  
**Target Platform**: Linux / macOS server, modern desktop browser (Chromium)  
**Project Type**: Voice AI Web Service & Administrative Portal  
**Constraints**: Zero database schema migrations required; complete offline test isolation with synthetic credentials; no fabricated vehicle records.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Principle I (Simple Architecture and Clear Ownership): Single canonical owner for support number in Business Settings; shared booking service across portal and telephony.
- [x] Principle II (Reliable State and Provider Operations): Atomic reservation validation; explicit customer consent for reschedule; separate reporting of configuration save vs. provider sync.
- [x] Principle III (Privacy and Trusted Integrations): Sanitized contact info; no credentials in logs or version control.
- [x] Principle IV (Strict Test-First Development and Contract Coverage): TDD workflow; unit/integration tests in `tests/`, browser tests in `e2e/`; full coverage in `test-coverage.yaml`.
- [x] Principle V (Observable Calls and Human Recovery): Transparent failure states for unavailable providers; clear helpline guidance on unrecognized messages.

## Project Structure

### Documentation (this feature)

```text
specs/013-business-neutral-portal/
├── spec.md              # Requirements and prioritized acceptance scenarios
├── research.md          # Technical analysis and design decisions
├── data-model.md        # Entities, config schemas, and DB relations
├── quickstart.md        # Execution and verification guide
├── test-coverage.yaml   # Acceptance-to-test mapping and live obligations
├── contracts/
│   ├── business-profile.md
│   ├── portal-api.md
│   └── sms-acknowledgment.md
├── checklists/
│   └── requirements.md
├── plan.md              # Implementation plan
└── tasks.md             # Dependency-ordered tasks
```

### Source Code

```text
serviceBot/
├── services/
│   ├── business_profile.py   # Generic detail classification, prompt generation
│   ├── booking.py            # Prevent vehicle fabrication, slot validation
│   └── sms_classifier.py     # Message acknowledgment with support helpline
├── api/
│   ├── portal.py             # Config endpoints, staff validation, slot endpoints
│   └── telephony.py          # Generic intake handling in voice tools
├── static/
│   ├── index.html            # Portal markup updates (business, catalogue, inbox, admin)
│   ├── app.js                # Portal client logic, date-first slot flow, save confirmation
│   └── style.css             # Visual updates, responsive layouts
tests/
├── test_business_profile.py        # Generic intake, prompt instructions, legacy compatibility
├── test_portal_config.py           # Canonical business settings, save confirmation
├── test_staff_agent_validation.py  # Staff email/phone requirements
└── test_sms_acknowledgment.py      # Support helpline message receipts
e2e/
└── test_business_neutral_portal.py # Full browser verification across all 12 changes
```
