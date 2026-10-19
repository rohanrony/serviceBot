# Validation and requirement coverage

All automated checks use disposable loopback PostgreSQL, temporary config/knowledge files and mocked/captured external providers. No paid simulations or live delivery acceptance were run.

## Requirement-to-behavior coverage

| Contract | Evidence |
| --- | --- |
| FR-001 Agent terminology and compatibility | Browser Services header/form, analytics scorecard, legacy-role rendering; existing trace assertions and catalog/availability/staff browser regressions |
| FR-002/003 Profile configuration | Unit/API save/read/unrelated-save preservation; duplicate/invalid key, empty label, unsupported type, too many fields and malformed portal URL rejection with no save/sync; browser save/reload |
| FR-004 Durable generic intake | Browser create/edit/reload, optional number zero and clearing, historical answers after field removal and subsequent edit; no vehicle row; legacy automotive integration regressions |
| FR-005 Shared validation and atomic failure | Invalid values rejected before service/customer mutation; real DB snapshots compare customers, vehicles, requests, reservations and notification queue before/after rejected intake and conflicting edits; voice validation before customer lookup |
| FR-006 Prompt and tool contracts | Generated identity/greeting/labels, custom prompt preservation, operational policy resynchronization, get_service_fields schema and provider tool-definition compatibility tests; graph-intake regression |
| FR-007 Summary and notifications | Neutral summary prompt and link validation, durable outbox payloads for each multi-service leg, reminder data enrichment; existing customer/agent/admin notification tests |
| FR-008 Migration/recoverability | Forward migration retains existing rows and provides default object; rollback refuses nonempty intake without losing data and succeeds after explicit data removal; migration runner regression |

## Executed checks on the isolated branch

- `./run_tests.sh --all --tb=short --junitxml=/private/tmp/voice-business-unit.xml`: **1846 passed**, 15 dependency/deprecation warnings.
- Full `python -m pytest e2e -q --tb=short --junitxml=/private/tmp/voice-business-e2e.xml`: **563 passed, 2 failed** on its initial final-branch run. One failure was the old expected Technician wording in `test_portal_availability_loading`; that assertion was updated to Agent while retaining the lazy-loading/deduplication/serialization checks, and the complete seven-test file was rerun.
- Focused Config/intake, catalog and staff browser tests: **24 passed** before the additional optional-clearing/historical-edit checks; those additional checks also ran in the full E2E run.
- `./run_tests.sh --file e2e/test_business_profile.py e2e/test_portal_catalog_agent_tagging.py e2e/test_portal_recent_features.py e2e/test_portal_availability_loading.py -q --tb=short`: **31 passed in 24.49s**, including all seven new feature acceptance tests and complete affected browser regression files.
- `node --check serviceBot/static/app.js`, Python `compileall` for serviceBot and the updated tool-sync script, and `git diff --check`: **passed**. No project lint/type-check command is configured in this checkout.

## Existing baseline failure

`e2e/test_deployed_full_fixtures.py::test_c27_real_owned_inactive_staff_is_hidden_from_active_api_and_retained` fails during fixture arrangement with `SimulationError: Full catalog native read-back differs`. The simulation adapter compares a mapping including inactive staff against the API's active-staff catalog projection. The same test failed independently on an unchanged detached checkout of **4a1f6fa** (`1 failed in 3.43s`). No assertion was skipped or weakened and the unrelated simulation adapter was excluded from this feature commit. The full acceptance suite is therefore not reported as green.

## Analyze and convergence

Pre-implementation analysis mapped all eight functional requirements and three success criteria to implementation/test tasks with no unresolved requirement or design decisions. Test-first iterations exposed discarded profiles, mandatory automotive input, missing voice schema, stale generated operational policies, missing reminder/multi-service details and a changed analytics fetch path; those gaps were fixed and retained as regressions. Final task-directed convergence found no remaining feature gaps. Live-provider acceptance and the baseline C27 fixture defect remain explicitly outside the completed local behavior evidence.
