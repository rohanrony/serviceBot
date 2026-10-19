# Tasks: Configurable business terminology and intake

## Phase 1: Setup
- [x] T001 Investigate terminology/configuration boundaries and record spec, research, plan and contracts in specs/009-business-terminology/.

## Phase 2: Foundation
- [x] T002 Add failing profile/config/intake/compatibility tests in tests/test_business_profile.py and browser journeys in e2e/test_business_profile.py; run Red.
- [x] T003 Implement shared profile validation and guarded JSONB migration in serviceBot/services/business_profile.py and serviceBot/db/migrations/0010_business_intake.sql with verification/rollback.

## Phase 3: US1 — Agent terminology
- [x] T004 [US1] Generalize app-owned visible copy in serviceBot/static/, serviceBot/api/, serviceBot/services/, serviceBot/db/queries.py; preserve compatibility identifiers. Verify Services header in e2e/test_business_profile.py.

## Phase 4: US2 — Business configuration and intake
- [x] T005 [US2] Add Business config save/load and dynamic request fields in serviceBot/api/portal.py, serviceBot/static/index.html and serviceBot/static/app.js.
- [x] T006 [US2] Persist generic intake atomically in serviceBot/services/booking.py and serviceBot/db/queries.py, support no-vehicle requests, preserve historical data on edit.

## Phase 5: US3 — Voice consistency
- [x] T007 [US3] Add generated business prompts, neutral summaries, voice intake validation/schema and booking adapters in serviceBot/api/telephony.py, serviceBot/services/business_profile.py and scripts/sync_elevenlabs_tools.py.

## Phase 6: Validation
- [x] T008 Run focused and relevant complete unit/integration/browser suites, migration checks and syntax/lint validation; record exact results in specs/009-business-terminology/validation.md.
- [x] T009 Run convergence against FR-001..008 and SC-001..003; resolve actionable gaps and record audit/compatibility limits in specs/009-business-terminology/audit.md.

Dependencies: T001 -> T002 -> T003; US1 and US2 use foundation; US3 uses US2; validation/convergence after all stories. Independent test authoring for copy/profile can be parallelized; implementation is sequential to preserve shared dirty files. MVP is Services terminology, followed by full Config switching and voice parity.
