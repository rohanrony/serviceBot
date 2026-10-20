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
Update or add one row for every changed acceptance contract, including its automated test IDs
and relevant live scenario IDs (or a concrete `not_required` reason). One row may suffice for a
bounded change. Do not create spec/plan/tasks or alter `.specify/feature.json`
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
prohibited changes when relevant. Update the neighboring `test-coverage.yaml` regression row
and its live coverage even when the fix restores established behavior. Provider fixes must
also update the affected live scenario and the provider evidence/budget fields below.

Production diagnosis can use external read access; normal tests, verification, hooks and CI
remain offline with synthetic credentials and disposable local databases. Diagnostic
credentials and production records must not leak into those test environments or Git artifacts.

### Small changes

A short acceptance/test record is sufficient for a bounded UI or configuration change with
clear intent. Update the appropriate observable contract; a label/accessibility change may
require an existing browser assertion, not invented business-rule tests. For a small feature
that benefits from durable design artifacts, use the shorter Spec-Kit path:
Specify → Plan → Tasks → Implement ↔ Converge. Respect invoked stages' prerequisites and
checklist gates; add quality gates if uncertainty or scope warrants them. Update or add the
changed contract's `test-coverage.yaml` row and assess live coverage explicitly; a small-change
route does not waive scenario maintenance or the reason for `not_required`.

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
   Map every changed acceptance contract to automated tests and relevant live scenarios; plan
   provider effects, independent read-back, prerequisites, cleanup/recovery and budget fields.
5. **Checklist and review** — Use `$speckit-checklist` to evaluate requirements completeness,
   clarity and consistency. Generated custom items start unchecked and belong to the reviewer.
   An agent may help evaluate only when explicitly asked. Checked custom items mean requirements
   quality was reviewed, not implementation completion. Return gaps to Specify/Clarify and
   reconcile the plan before breaking work down.
6. **Tasks** — Use `$speckit-tasks` for dependency-ordered, acceptance-linked test-first work,
   including affected browser journeys and migration upgrade/verification/rollback where relevant.
   Include tasks to update the coverage rows and live scenarios. Keep live execution as a
   separate task gated by explicit authorization; preparing coverage does not authorize a run.
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

All three routes retain the same quality and publication gates. Before implementation, update
or add a feature-local `test-coverage.yaml` row for **every changed acceptance contract**, using
`.specify/templates/test-coverage-template.yaml`. Map behavior, preconditions, success, failure,
invariants, real automated test IDs, layers and live requirements; explain omitted layers.
The same requirement applies to bug fixes, small changes and full features. Run focused tests
while iterating.

Rows must name actual automated test IDs (collected pytest node IDs, including relevant
parameter cases), not filenames alone, invented names or planned tests. Add/update the tests
first and keep the mapping current through implementation. `live_acceptance.scenarios` must
name real IDs from `live_simulations/scenarios.json` or an explicitly linked maintained live
scenario definition. If no existing scenario covers the contract, add one and reference its ID.
For contracts with no live boundary, use `scenarios: []`, `status: not_required` and a concrete
reason. A missing scenario, blocked prerequisite or lack of run authorization means `pending`,
not `not_required`. A test/scenario ID establishes traceability, not proof of execution or
behavioral sufficiency.

### Maintain live coverage; authorize execution separately

For every provider behavior change, update the actual affected live scenario definition as well
as the coverage row. Reusing an ID without updating its stale assertions is insufficient. Record:

- The live scenario ID and definition path, relevant recipients/calendars/accounts/permissions,
  starting fixtures, environment and prerequisite scenarios.
- Expected external effects and prohibited effects, including duplicate prevention and partial
  failure behavior where relevant.
- **Independent read-back**: which provider/calendar/inbox/status source will be read, which
  event/message/request IDs correlate it to the run, and what proves the expected outcome.
  Application success responses, internal rows, queued work or a conversation transcript alone
  do not establish provider delivery. Distinguish provider acceptance from final delivery.
- Cleanup/recovery for run-owned resources and partial failures, retaining evidence and an
  explicit recovery path for resources the runner cannot safely remove.
- Estimated credits and/or monetary cost, units, estimate basis and uncertainty; an explicit
  spending ceiling and its authorization before execution. Unknown estimates remain a readiness
  blocker. Keep unknown-charge handling explicit: stop, retain the ledger and reconcile before
  retrying. An estimate or proposed ceiling is not authorization to spend.

Updating coverage rows and scenario definitions is required development work and can be completed
offline. **Executing live tests requires separate authorization** for the selected environment,
scenarios, recipients and spending ceiling. Normal development tests, verification, pre-push and
CI remain offline; do not add live execution to these gates. Offline/mock or captured-provider
tests cannot prove live provider delivery. Follow `docs/LIVE_SIMULATIONS.md` and the
`live-simulations` skill when live execution is separately requested. Reuse retained evidence only
when the scenario, implementation, target, bindings and provider contract remain applicable;
record why it is still valid and what invalidates it. Changed provider behavior invalidates
evidence for the affected assertions until they are verified again.

### Offline review and publication gates

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
| Missing or inadequate test coverage, including absent/stale live scenarios or provider evidence/budget fields | Tasks / implement | Add a coverage/test task for the uncovered contract. Update its matrix row and scenario definition, write automated tests first, then implement and run the appropriate offline suite. Keep live execution pending separate authorization. |
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

Coverage maintenance must be complete before development handoff even when live execution is
pending. Do not describe provider delivery as complete while its required live evidence is pending.

## Handoff record

For every route, report its choice/reason, feature or short change record, artifacts changed,
root-cause evidence when relevant, any convergence iterations, actual test commands/outcomes
(including browser tests when applicable), review findings and remaining limitations. Do not claim
browser coverage unless a browser test was added or updated and actually executed.

Report **Offline** and **Live** independently as `verified`, `pending` or `not_required`, each with
a reason and evidence reference. Report Committed/Pushed, Merged and Deployed separately.

| Status | Offline evidence | Live evidence |
| --- | --- | --- |
| `verified` | Required checks actually ran and passed for this change; name commands, results and revision. | Separately authorized cases passed with retained evidence of the required external effects, independent read-back and cleanup/recovery status for the applicable target/revision. A smoke/API result proves only its recorded scope. |
| `pending` | Required checks were not run, failed, were incomplete or are blocked; name the gap and next step. | Required live acceptance is unexecuted, failed, incomplete, invalidated or blocked; name scenario IDs, missing evidence/prerequisites, authorization/budget needs and next step. |
| `not_required` | Explain why the particular test layer does not apply, such as application suites for pure documentation edits; still report document/diff validation. | Explain why this contract has no relevant live boundary; keep the coverage row's scenarios empty. Missing access, budget or authorization is not this status. |

Include the coverage artifact path and changed acceptance IDs, updated automated/live IDs, and
whether live coverage definitions are current. Required live execution can remain `pending`
without inventing authorization, but missing/stale coverage definitions remain a development gap.
