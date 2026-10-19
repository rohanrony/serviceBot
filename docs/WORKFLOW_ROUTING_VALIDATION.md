# Workflow routing change and validation

Date: 2026-10-19. This is a workflow-instruction change, extending the previously published
verification workflow at commit `959d381edd8df2131daa090d5944d95e7574f19b`. The workflow patch changes no application code,
test fixtures, external permissions or runtime configuration. Its publication candidate also
integrates current main at `7b9bf4b3f7a613a0f6f7900987125e855d61935c`. The staff-calendar
merge conflict preserves that target revision's complete test file and assertions.

## Acceptance and design

One `$speckit-workflow` entry point selects the development route by intent, uncertainty and
impact. Bug fixes restore an established contract after systematic diagnosis; small changes
use concise acceptance/test records; complex/consequential features use the full upstream
sequence, including reviewer-owned checklist review. All retain complete offline verification
before publication. Session initialization defaults offline and reuses current context.
Diagnostic evidence is task-scoped and read-only, separated from tests and provider operations.

The change updates the workflow skill, adds the discoverable Codex initializer, updates the
canonical guide and amends the constitution to 1.3.0. Existing spec/plan/tasks/coverage templates
remain usable; no migration or new application service is needed. Existing feature artifacts
remain relevant where intent is unchanged.

## Instruction-level forward tests

An independent evaluator received the raw baseline/candidate instructions and these requests,
without the expected route or proposed fix. Evaluation was a read-only simulation: no actual
production reads, credential loading, external requests or application implementation.

| Case | Request | Behavior to assess |
| --- | --- | --- |
| A | Production booking saves return 500 during a defined UTC interval; no credentials available | Investigate first; missing diagnostic access stays explicit while useful offline work continues; no fabricated cause or production writes |
| B | Rename Vehicle notes to Vehicle details without changing storage/behavior | Bounded small-change route; relevant browser/accessibility assertion; no full PRD/plan or active-feature mutation |
| C | One-line request to allow cross-organization booking edits | Assess authorization semantics and affected ownership boundaries rather than line count; clarify scope/escalate rather than blindly treating it as a caption-sized change |
| D | Full booking approval feature with capacity, retries/concurrency; reviewer has not evaluated custom checklist | Full sequence; clarification/design and reviewer handoff before implementation; no self-approved checklist markers |
| E | Initialized current session already established a leap-day parser defect and deterministic reproduction; authorized push | Reuse current diagnosis; add/confirm failing regression, bounded fix and full exact-candidate verification before push |

These evaluate agent decisions rather than matching document wording. They are targeted
instruction review, not newly collected pytest cases and not proof of application behavior.
The full existing application suites separately verify runtime regressions and gate behavior.
Observed outcomes:

| Case | Baseline | Candidate | Assessment |
| --- | --- | --- | --- |
| A | Full feature artifacts; no specific initializer or missing-access continuation | Bug route, scoped diagnostic readiness, explicit unavailable evidence, useful offline continuation | Passed |
| B | Full feature cycle for the label change | Short change note and relevant UI contract test; no feature-pointer mutation | Passed |
| C | Full route without explaining a routing decision | Explicit escalation because tenant authorization changes, regardless of line count | Passed |
| D | Unchecked-checklist stop appears at Implement | Reviewer handoff appears before Tasks; Implement retains its read-only checklist stop | Passed |
| E | Requires full feature artifacts when no matching feature exists | Reuses initialized diagnosis and bounded regression/fix, with authorized exact-SHA publication | Passed |

The evaluator found no material routing conflict. The earlier reviewer handoff and later
implementation confirmation overlap intentionally. An explicit user decision to proceed with
unchecked items never authorizes changing markers or impersonating reviewer approval.
These results demonstrate instruction selection in the supplied scenarios, not a guarantee
of every future agent run.

## Validation commands and evidence

- Both changed/new skills: skill-creator `scripts/quick_validate.py`, using the project Python.
- `.venv/bin/python scripts/check_static.py` and `git diff --check`.
- Local Markdown reference resolution for the two skills and canonical guide.
- After committing, `./scripts/verify_change.sh --base origin/main --head HEAD` against the
  fetched target with disposable UTF8 loopback PostgreSQL, Chromium and synthetic credentials.
  Its receipt records the actual SHA/base, collected/executed IDs and results. Evidence lives
  under `scratch/verification/<head>-<base>/receipt.json`; it is not committed into its own tree.

No application boundary changed, so new unit/database/HTTP/browser/provider/migration tests
would not exercise the changed instruction behavior. The independent scenarios cover the
routing, reviewer boundary, session reuse, missing-access handling and publication obligations.
The complete existing unit/integration and E2E suites still run, including the browser subset.
No skip, expected failure or weakened assertion was introduced.

Live acceptance is not required: this change adds no provider semantics and executes no live
diagnostic or provider operation. Hosted CI/review, merge and deployment remain separate states.
