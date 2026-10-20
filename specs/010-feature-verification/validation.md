# Validation: feature testing and merge readiness

Implementation verification passed on 2026-10-19. This record describes the isolated candidate
before publication. The publication helper reruns verification for the actual committed SHA
against the current remote target; its fresh receipt is at `scratch/verification/<head>-<base>/receipt.json`
in the publication checkout. The earlier receipt below does not cover a different commit or
unrelated dirty application changes.

## Exact candidate and results

- Candidate: `3c94a9dda8f1f67988b302987092db2229ad4034`
- Baseline: `4a1f6faedba7b0679f1e151d5f62f06526c5bff6` (workspace HEAD used for local implementation validation)
- Run: `857c8ec36da6490b973276056e9a423c`
- Started: `2026-10-19T20:17:40.731316+00:00`
- Finished: `2026-10-19T20:21:56.783723+00:00`

| Suite | Passed | Failed/errors/skipped/xfail/xpass |
| --- | ---: | --- |
| Unit/integration | 1,855 | All zero |
| Complete E2E | 558 | All zero |
| Chromium browser subset within E2E | 95 | All zero |

The 39 gate regression cases are included in unit/integration. They exercise failed/static/
setup/teardown results, missing browser execution/JUnit/manifests, stale JUnit with matching
counts, filtering, skips/xfail/xpass, wrong head/base, tampered artifacts, already committed
work, explicit file selection, changed targets, multiple refs, protected-branch updates,
custom integration targets, synthetic credential boundaries, external DNS, Git metadata,
UTF8 database preflight and the CI aggregate. The tests assert receipt validity and actual
Git ref/index effects. Existing application assertions were retained.

All seven recorded commands passed: local clone, exact detached checkout, installed dependency
inventory, static checks, independent unit collection, independent E2E collection and canonical
`./run_tests.sh --verify`. Collection/execution IDs, complete phases, JUnit run IDs and artifact
hashes were checked. The actual CI aggregate script also passed locally against this full receipt.

## Retained evidence

- [Full receipt](../../scratch/verification-validation/final-application/receipt.json)
- [Summary and candidate scope](../../scratch/verification-validation/summary.json)
- [Candidate construction manifest](../../scratch/verification-validation/candidate.json)
- [Command logs, JUnit and manifests](../../scratch/verification-validation/final-application/runs/857c8ec36da6490b973276056e9a423c/verify.log)
- [Sample publication read-back](../../scratch/verification-validation/sample-feature/readback.json)

The sample used an actual temporary Git repository, canonical runner and a disposable local
bare remote. Its feature ref matched the verified SHA and the target remained unchanged.
The copied sample receipt passed `--check` again after retention. Other regression cases prove
unrelated staged files remain staged and that failed gates do not publish refs.

## Reproduction

The isolated candidate remains at `/private/tmp/voice-verification-candidate-9ql59nnb`.
The full run used disposable UTF8 PostgreSQL on loopback port 55483 with CREATEDB permission,
synthetic credentials, isolated HOME/runtime files and installed Chromium. The database was
stopped after verification; restarting or reprovisioning it is required for another full run.

```sh
# From the isolated candidate, with disposable PostgreSQL running:
TEST_DATABASE_URL=postgresql://offline@127.0.0.1:55483/voice_service_test \
  ./scripts/verify_change.sh --base 4a1f6faedba7b0679f1e151d5f62f06526c5bff6 \
  --head 3c94a9dda8f1f67988b302987092db2229ad4034 \
  --output /Users/rohanroy/Coding/voiceService/scratch/verification-validation/final-application
```

The source checkout stayed on `dev-v0.19.2-medium-native-recovery` at its original HEAD with
an empty index. The existing date-stability change in `tests/test_staff_calendars.py` was
included as a validation prerequisite and left unchanged. Other unrelated dirty work was
excluded from the candidate. Evidence files are ignored local artifacts.

## Convergence and remaining operational gates

Bounded source review reconciled all five functional requirements and six acceptance scenarios
with the final implementation; no actionable implementation gap remains. Static checks, YAML
validation, diff whitespace checks and the full offline gate passed. See `analysis.md` for
the test-quality review and fixes discovered during validation. Graph coverage was unavailable;
direct source inspection and executable checks were used.

The local pre-push hook is installed. The GitHub workflow and proposed **Merge readiness**
required check/review settings are present as files, but hosted CI has not run. Read-back still
reports main as unprotected and no repository rulesets. Enabling remote protection requires
separate maintainer authorization; no remote access settings were changed.

**Offline:** verified for the isolated SHA above. **Live:** not required for these workflow
changes; no live-provider execution performed. **Merged:** no. **Deployed:** no.
At the time of the implementation run, no source-checkout commit or GitHub push had been made.
Publication uses explicit files in a separate worktree based on remote main and verifies the
actual publication SHA again. Merge
readiness additionally requires current hosted CI, resolved review findings and server rules.
