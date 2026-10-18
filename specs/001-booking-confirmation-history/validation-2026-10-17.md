# Verification repairs — 2026-10-17

Completed T026–T036 under FR-007/008 and Constitution II/IV/V. Final command `./run_tests.sh --verify --tb=short`: 703 unit/integration and 283 E2E passed, zero failures/errors/skips. Regression tests were observed failing before implementation; final captured-provider, real database, transaction rollback and migration rollback/reapplication checks pass.

Convergence covered normalized capacity, source release, preserved domain failures, transactional calendar/reminder effects, exact provider identity, stale retry/failure ordering and durable deletion state. No remaining implementation findings in these repaired contracts. No extension hooks; requirements checklist 16/16 complete. Graph MCP was unavailable; exact source fallback was used, with no graph completeness claim.

Migration `0006_calendar_deletion_state.sql` and its explicit rollback are required for publication. No production migration or deployment occurred. API/CLI payloads remain compatible; calendar projection uses the already-emitted DELETED state now admitted by schema. Provider operations hold request/reservation row locks with the existing network timeouts; live contention/latency was not measured.

Full evidence is retained at `scratch/overnight-20261017/report.md`, `final.log`, `final-unit-results.xml`, `final-e2e-results.xml`, plus focused red/green logs. Cached Ruff found no introduced diagnostics; 37 existing diagnostics remain in larger untouched regions. Deployed C01–C06 acceptance remains budget-blocked, zero paid invocations/credits this session. Feature 007 T051 completes readiness/reporting, not live acceptance.
