# VoiceService change workflow

Start a change with **`$speckit-workflow`** and describe the outcome or symptom. The same entry
point chooses a bug-fix, small-change or full Spec-Kit route and explains the choice. Its skill
is in `.agents/skills/speckit-workflow/SKILL.md`.

## Access the workflow

In a Codex session opened in this repository:

```text
$speckit-workflow Bug fix: investigate failed booking saves; use logs and DB evidence as needed.
$speckit-workflow Small change: rename the portal field from X to Y.
$speckit-workflow Full feature: add booking approvals with manager permissions.
```

Route labels are optional natural-language preferences, not CLI flags. Describe the problem
without a label when unsure. An explicit full-path request is honored. The workflow announces
its selected route and reason, and explains any later escalation.

In Codex CLI or the IDE extension, `/skills` opens the picker. Direct skill names use `$`;
this repository does not install a `/speckit-workflow` slash alias. See the
[official skills guide](https://learn.chatgpt.com/docs/build-skills).

Session setup is integrated. You may also invoke `$initialize-session` independently for offline
readiness or a scoped investigation. It is the Codex counterpart of the legacy `/init-session`
and `/initialize-session` IDE workflows; those aliases and their unconditional environment
sourcing are not invoked by this workflow.

To authorize publication as part of the request, add “Once verified, commit and push to a new
branch.” Use `$git-push-merge` for verified publication alone; merge requires separate
authorization. The terminal verification entry point is
`./scripts/verify_change.sh --base <target-ref> --head <commit-sha>`.

## Select the development route

Read the constitution, inspect workspace state, and identify relevant existing evidence first.
Do not let an unrelated active-feature pointer select the work. Choose by intent, uncertainty
and impact, not file/line count. No universal full-PRD requirement applies to bounded changes.

| Route | Appropriate scope | Sequence |
| --- | --- | --- |
| Bug fix | Restore established expected behavior | Systematic debugging → reproduce/failing regression → fix/refactor → review |
| Small change | Clear, bounded outcome with limited interactions, such as a caption rename | Acceptance/test note → test update → implementation → review |
| Full feature | Material product ambiguity, cross-component design, migrations, new authorization/provider semantics or consequential state changes | Specify → Clarify → Plan → Checklist review → Tasks → Analyze → Implement ↔ Converge |

A tiny security, ownership or booking-state change may need the full route. Unknown root cause
requires investigation first, not a new feature spec by itself. If diagnosis reveals new product
semantics or substantial design decisions, explain and escalate to the full route. Ask only for
missing material intent/access; continue independent work while dependent decisions are pending.
An explicit small/bug preference does not waive testing or justify guessing product requirements.

Reuse an existing feature when intent matches. For a bounded fix or small change without a
relevant feature, keep a short record at `specs/changes/<slug>/change.md` and a neighboring
`test-coverage.yaml`. Record route/reason, scope, expected results/failure cases/invariants,
test IDs and Red/Green evidence, review and live obligations; add root-cause evidence for a bug.
One acceptance row may suffice. Do not create spec/plan/tasks or alter `.specify/feature.json`
just to satisfy a route. Pure documentation changes without behavior impact need document/diff
validation; workflows, prompts, configuration and test infrastructure require appropriate
behavioral review and full publication verification.

### Bug-fix investigation and session setup

Use `systematic-debugging` before proposing a fix. Reuse current initialization and diagnosis
already supplied in the conversation; verify their environment, revision and relevance rather
than rerunning the entire bootstrap. Follow
[initialize-session](../.agents/skills/initialize-session/SKILL.md) for task-scoped setup.

Start offline. If the symptom needs operational evidence, enter diagnostic mode: establish the
environment/service, IDs and time window/timezone, then obtain bounded read-only logs and/or
fresh application-record reads using available authenticated tools. Missing credentials do not
block offline work. Do not source all secrets, load another project's credentials, perform
unrelated health probes or claim health from connectivity or a limited empty query.

Record query filters, observation time, limits and redacted evidence; distinguish event time
from ingestion time and confirmed cause from hypothesis. Use read-only database transactions
and timeouts, relevant columns and row limits. Do not modify production state to reproduce a
defect. Production repair, deployment, notifications and paid provider calls need separate
authorization. Create an isolated deterministic regression from minimal redacted evidence.
A permanent failing regression precedes the behavioral fix; verify persisted effects and
prohibited changes when relevant.

Production diagnosis can use external read access; normal tests, verification, hooks and CI
remain offline with synthetic credentials and disposable local databases. Diagnostic
credentials and production records must not leak into those test environments or Git artifacts.

### Small changes

A short acceptance/test record is sufficient for a bounded UI or configuration change with
clear intent. Update the appropriate observable contract; a label/accessibility change may
require an existing browser assertion, not invented business-rule tests. For a small feature
that benefits from durable design artifacts, use the shorter Spec-Kit path:
Specify → Plan → Tasks → Implement ↔ Converge. Respect invoked stages' prerequisites and
checklist gates; add quality gates if uncertainty or scope warrants them.

## Full Spec-Kit route

Read the existing constitution each run; establish or amend it only when project policy changes.
PRDs may supply business goals, stories, success metrics and open questions to Specify/Clarify;
their technical constraints inform Plan. Link the PRD rather than maintaining competing intent.
See the [upstream quickstart](https://github.com/github/spec-kit/blob/main/docs/quickstart.md)
and [command boundaries](https://github.com/github/spec-kit/blob/main/docs/reference/agentic-sdd.md).

1. **Constitution** — Read `.specify/memory/constitution.md`; invoke `$speckit-constitution` only
   for an authorized policy amendment.
2. **Specify** — Use `$speckit-specify` for observable outcomes, acceptance criteria, failure
   cases, exclusions and success measures.
3. **Clarify** — Use `$speckit-clarify` before planning to assess ambiguity and persist answers.
   Report when no meaningful ambiguity remains; do not invent questions or assume user intent.
4. **Plan** — Use `$speckit-plan` for research, design, data/contracts, constraints and test layers.
   Prepare `test-coverage.yaml` beside the spec using the project template before implementation.
5. **Checklist and review** — Use `$speckit-checklist` to evaluate requirements completeness,
   clarity and consistency. Generated custom items start unchecked and belong to the reviewer.
   An agent may help evaluate only when explicitly asked. Checked custom items mean requirements
   quality was reviewed, not implementation completion. Return gaps to Specify/Clarify and
   reconcile the plan before breaking work down.
6. **Tasks** — Use `$speckit-tasks` for dependency-ordered, acceptance-linked test-first work,
   including affected browser journeys and migration upgrade/verification/rollback where relevant.
7. **Analyze** — Use `$speckit-analyze` for a read-only consistency report. Fix the owning
   artifacts outside Analyze, then rerun after upstream changes until material findings resolve.
8. **Implement** — Use `$speckit-implement` and Red → Green → Refactor. Its checklist gate reads
   markers but never edits them; it asks before proceeding when any are unchecked.
   Specify/Clarify maintain only the built-in `checklists/requirements.md`; custom checklists
   remain reviewer-owned. Implementation marks completed tasks only in `tasks.md`.
9. **Converge** — Use `$speckit-converge` against code/spec/plan/tasks. It appends remaining work
   to `tasks.md`, without changing code or upstream intent. Follow the feedback loop below until
   all tasks are complete and there are no actionable findings.

## Shared testing, review and publication

All three routes retain the same quality and publication gates. Map each changed acceptance
contract to behavior, preconditions, success, failure, invariants, real test IDs, layers and live
requirements in `test-coverage.yaml`; explain omitted layers. Run focused tests while iterating.

1. **Review** — Assess meaningful assertions, fresh persistence/reloads, prohibited effects,
   deterministic fixtures and external-boundary mocks. Resolve findings. Review removals and
   weakened assertions; required behavior cannot remain a placeholder, skip or expected failure.
2. **Verify** — Before handoff run the complete offline `./run_tests.sh --verify`. For authorized
   publication, select the exact committed candidate and fetch/integrate the current target,
   then run `./scripts/verify_change.sh --base <target-ref> --head <commit-sha>`. Its static/full
   suite run satisfies the handoff test gate without redundant reruns. It independently collects
   `tests/` and `e2e/` and retains evidence; browser journeys are a subset of E2E.
3. **Push** — With publication authorization, use `scripts/git_push_merge.sh` and explicit files
   if committing. Both helper and installed hook require evidence for the exact outgoing SHA
   and current target, including already committed work.
4. **CI** — Require the current `Merge readiness` aggregate. Target/head changes invalidate
   evidence. It rejects skipped/failed mandatory jobs and absent/incomplete reports. See
   [MERGE_READINESS.md](MERGE_READINESS.md).
5. **Merge** — With separate merge authorization, require current CI/review, resolved findings,
   meaningful acceptance tests and explicit live obligations. Protected server rules enforce
   these requirements; local hooks alone cannot enforce them.

## Feedback loop after converge

Do not treat converge as a terminal report when it finds remaining work. Classify each finding by
the artifact that owns the decision, then return to the earliest stage that needs to change:

| Feedback | Return to | Next steps |
| --- | --- | --- |
| Missing behavior or implementation detail; requirements and design remain correct | Tasks / implement | Keep the appended task traceable. Add a failing regression or acceptance test first, implement, validate, then converge again. |
| Missing or inadequate test coverage | Tasks / implement | Add a test task for the uncovered contract. Write the test first, then implement any behavior it exposes; run the appropriate `tests/` and/or browser `e2e/` suite. |
| Requirements, acceptance criteria, or expected outcomes are wrong or incomplete | Specify / clarify | Amend the spec, clarify unresolved intent, then regenerate or reconcile plan and tasks, analyze, implement, and converge. |
| Architecture, data model, integration, or technical constraint is wrong | Plan | Update the plan, reconcile affected tasks, analyze, implement, and converge. Revisit the spec too if the design change alters user-visible behavior. |
| Artifact inconsistency or missing task discovered before code changes | Earliest inconsistent artifact | Correct the owning artifact and its downstream artifacts; rerun analyze before implementation. |
| No actionable findings | Exit loop | Record convergence, complete the required test and review gates, then hand off. |

When an upstream artifact changes, downstream artifacts are no longer presumed current. Reconcile
them in order (spec → plan → tasks), rerun analyze, then resume implementation. Never resolve a
requirement or design disagreement by appending an implementation task that contradicts the
approved intent. The converge command itself is append-only. When upstream changes require tasks
to be regenerated, retain valid task IDs and completed work where possible, and explicitly mark
obsolete convergence items as superseded rather than silently losing or blindly preserving them.
If converge reports no findings, it should leave `tasks.md` unchanged.

The loop is complete only when converge finds no actionable gaps, all tasks are complete, relevant
unit/integration and browser acceptance tests pass, and the implementation has been reviewed
against the acceptance criteria. A passing test run by itself is not proof that every contract is
covered. Live-provider delivery remains a separate operational acceptance gate; offline mocks do
not prove delivery to an external provider.

Every changed behavioral contract follows Red → Green → Refactor. Choose layers for the
changed behavior: unit rules/boundaries; database ownership/transactions/rollback/concurrency;
HTTP parsing/auth/status/persisted effects; browser visible actions/reload/error recovery;
realistic provider transports; composed existing-state/retry/partial-failure workflows;
migration upgrade/verification/rollback/preservation; and targeted accessibility/performance/
security checks where affected. A changed booking form requires browser coverage. Include
save/reload, validation, disabled controls, double submission, network failure and stale-response
cases when relevant. Composed bookings include canceled records, multiple technicians and retries.
Counts and coverage percentages support review; they do not replace behavior evidence.

Normal development, pre-push and CI remain offline. Provider behavior changes also update live
scenarios with recipients/calendars/permissions, expected effects and independent read-back,
cleanup/recovery, credit estimates, spending ceiling and unknown-charge handling. Live execution
requires separate authorization. Preserve valid differential coverage and rerun invalidated cases.
Always report **Offline verified · Live pending/verified/not required · Merged · Deployed** separately.

## Handoff record

For every route, report its choice/reason, feature or short change record, artifacts changed,
root-cause evidence when relevant, any convergence iterations, actual test commands/outcomes
(including browser tests when applicable), review findings and remaining limitations. Do not claim browser coverage unless a browser test was added or
updated and actually executed.
