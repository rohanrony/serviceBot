# Consistency and review record

Scope: five functional requirements, six acceptance scenarios, eleven implementation tasks,
the verification/push/CI scripts, test harness changes, coverage template and workflow guidance.
The supplied brief resolved material requirements before implementation. Initial artifact
analysis found a task for each requirement; no constitution exception was required.

## Behavior review

| Contract | Evidence and decision |
| --- | --- |
| Exact candidate | Isolated Git clone, detached SHA, tree/dependency/test manifests; dirty and staged sentinel work preserved. Git metadata remains available to runtime tests. |
| Complete offline suites | Independent collection, identical executed IDs and complete setup/call/teardown; AnyIO loaded explicitly; browser subset inside E2E. |
| Fresh evidence | Unique run ID in manifests and every JUnit case; exact JUnit IDs; artifact digests. Stale JUnit with matching counts was accepted in Red and rejected after the fix. |
| Failure gates | Failed/static/setup/teardown, skips/xfail/xpass, filtering, missing browser/JUnit/execution, wrong SHA/base and tampering are rejected. Both suites run after unit failure. |
| Publication | Clean commits verified; branch selection first; explicit file commits preserve unrelated index entries; main/master updates/deletion and unverified multi-ref pushes rejected. Selected custom target is shared with installed hook. |
| Offline environment | Synthetic environment and legacy dotenv file; developer dotenv sentinel preserved/excluded; import-time external DNS/connects blocked; UTF8 loopback PostgreSQL checked. Fixtures control application test mode. |
| Test realism | Only the downloadable encoder is replaced in unit fixtures; FAQ logic, real Chroma operations, routing, PostgreSQL transactions and existing assertions remain. Existing domain tests were not removed or weakened. |
| CI and live boundaries | Mandatory job result must be exactly success; missing/tampered reports fail aggregate. PR and merge_group triggers present. No production secrets referenced and no live workflow invoked. |

## Design corrections from actual execution

The archive prototype broke simulation tests that read Git revision metadata; an isolated
clone fixed the boundary. A global TESTING flag hid the bad-credential behavior and was removed.
An isolated HOME exposed uncaptured embedding downloads, now replaced at the encoder boundary.
The disposable cluster initially used SQL_ASCII; error logging identified emoji encoding
failures, and the verifier now requires UTF8. These failures were retained, not marked as skips.

The existing date-stability fix in `tests/test_staff_calendars.py` was included as a validation
prerequisite without changing that file. Other unrelated dirty work was excluded from the
candidate. Final numerical results and snapshot identity are recorded in `validation.md`.

## Operational boundaries

GitHub main protection and rulesets were read back as absent; proposed settings are documented
in `docs/MERGE_READINESS.md`. Hosted CI and remote protection activation follow authorized
publication and maintainer configuration. Local evidence is not a signed attestation and does
not replace review. No GitHub push, merge, deployment or paid provider execution was performed.

Graph indexing/coverage remained unavailable because this checkout was outside the MCP
server's allowed root. Verification used bounded direct source reads and executable tests;
no graph completeness claim is made.
