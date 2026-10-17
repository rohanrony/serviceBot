# End-to-end acceptance tests

Run instructions: [Testing VoiceService](../docs/TESTING.md).
Journey checklist and feature matrix: [TEST_PLAN.md](TEST_PLAN.md).
Observed unmet requirements: [KNOWN_FAILURES.md](KNOWN_FAILURES.md).

```bash
export TEST_DATABASE_URL=postgresql://127.0.0.1/voice_service_test
./run_tests.sh --e2e                    # complete acceptance suite
./run_tests.sh --browser --e2e-headed   # watch only browser journeys
./run_tests.sh --features               # recent features and regressions
```

The suite uses real HTTP, PostgreSQL, domain services and browser actions.
Provider requests are mocked or captured; no live messages or calls are made.
Failed browser evidence is under `scratch/e2e-artifacts/`. Requirements remain
ordinary failures ready to turn green after their application fixes.

Existing cases cover navigation, request/catalog/knowledge/inbox workflows,
booking/capacity/history, Google OAuth, webhooks, reporting, reminders,
notification delivery/retry and recovery. The expansion adds technician-tag
editing, multi-service visits, staff deactivation/reassignment, multiple SMS
assignments, timezone settings, recording-disclosure greeting persistence/sync,
and permanent regressions for previously found gaps.

[ACCEPTANCE.md](ACCEPTANCE.md) provides requirement references.
[COVERAGE.md](COVERAGE.md) describes evidence boundaries. Historical counts and
failure lists refer to earlier checkouts; use the latest JUnit report for results.
