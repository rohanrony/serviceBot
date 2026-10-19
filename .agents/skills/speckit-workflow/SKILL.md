---
name: speckit-workflow
description: Take a VoiceService change from investigation or requirements through implementation, meaningful tests and review. Select a bug-fix, small-change or full Spec-Kit route according to intent, uncertainty and impact.
---

# VoiceService change workflow

Start with `$speckit-workflow` and describe the outcome or symptom. Natural-language route
preferences are supported, for example `Bug fix: investigate failed booking saves using logs`,
`Small change: rename this field`, or `Full feature: add booking approvals`. These are chat
instructions, not command-line flags. The user need not choose a route.

Follow [the project workflow](../../../docs/SPECKIT_WORKFLOW.md). Its shared testing and
publication gates apply to every route. Documentation-only edits without behavioral impact
need document/diff validation; workflow, prompt and configuration changes need appropriate
behavioral review and publication verification.

## Start and select a route

1. Read `.specify/memory/constitution.md`, inspect branch/workspace state and relevant existing
   change artifacts. Preserve unrelated work. Do not select a feature merely because
   `.specify/feature.json` points to it; confirm that its intent matches this request.
2. Reuse applicable session initialization and diagnosis already completed in this conversation.
   Read [initialize-session](../initialize-session/SKILL.md) for local setup or, when needed,
   bounded read-only operational evidence. Default to offline setup; use diagnostic mode
   only for an actual investigation. Do not run legacy unconditional credential loading or
   health probes. Missing production credentials do not block offline development.
3. Choose by intent, uncertainty and impact, rather than file/line count. Announce the route
   and one concrete reason. Honor an explicit full-path request. An explicit bug/small preference
   does not justify guessing requirements or bypassing the shared gates; explain and escalate
   when investigation discovers broader requirements or design decisions.

| Route | Use when | Work sequence |
| --- | --- | --- |
| Bug fix | Restore established expected behavior | Systematic debugging → failing regression → fix/refactor → review |
| Small change | Clear, bounded intent with limited interactions | Short acceptance/test record → test update → implementation → review |
| Full feature | Material product ambiguity, cross-component design, data migration, new authorization or provider semantics, or consequential state changes | Specify → Clarify → Plan → Checklist review → Tasks → Analyze → Implement ↔ Converge |

Unknown root cause calls for debugging first; it does not by itself require a new feature spec.
A small-looking change affecting security, ownership or booking correctness can require the full
route. Clarify missing user intent before dependent work; continue independent work when possible.

## Bug-fix route

Use the installed `systematic-debugging` skill: collect evidence, reproduce, compare working
behavior, test a specific hypothesis, then fix the cause. If it is unavailable, follow that
sequence directly and disclose the fallback. Reuse a current, established diagnosis instead of
starting it again; validate its environment, revision and relevance to the symptom.

For logs/database investigation, follow `initialize-session` in diagnostic mode. Record the
environment, time window/timezone, relevant identifiers, bounded query, observations and limits.
Distinguish confirmed cause from hypothesis; absent access or absent logs is not proof of health.
Do not alter production state to reproduce a defect. Capture a redacted deterministic offline
fixture from the relevant evidence when useful, not production secrets or full customer records.

Record expected behavior, root-cause evidence, invariants, regression test and Red/Green results
in the existing relevant feature or a short change record. Do not create spec/plan/tasks merely
to fix a bounded defect. Add a permanent regression before changing behavior; include fresh
persisted reads/reload and prohibited effects where applicable. Escalate to the full route if
the fix requires new product semantics or substantial design decisions.

## Small-change route

Write a short scope/acceptance note and behavior-to-test mapping, using existing artifacts when
appropriate. No full PRD, technical plan or new active feature pointer is required for a label
rename or similarly bounded change. For a behavioral change, demonstrate the intended failure
before implementation and update the relevant boundary test. A label/accessibility change may
need an existing browser assertion updated; do not invent unrelated business-rule tests.

When a small new feature benefits from durable design artifacts, use the shorter Spec-Kit path:
Specify → Plan → Tasks → Implement ↔ Converge. Honor each invoked stage's prerequisites and
checklist gate. Add clarification, checklist review or analysis if scope or ambiguity warrants it.

## Full-feature route

Follow each corresponding `speckit-*` skill, including its hooks and artifact boundaries:

1. Read the existing constitution. Run `speckit-constitution` only for an authorized policy change.
2. `speckit-specify`: capture what/why, acceptance criteria, failure modes and exclusions.
3. `speckit-clarify`: assess ambiguity before planning. Ask material questions and persist answers;
   report when no meaningful ambiguity remains rather than inventing questions or answers.
4. `speckit-plan`: resolve technical uncertainties and document design/contracts/test layers.
5. `speckit-checklist`: generate requirements-quality items, then obtain reviewer evaluation.
   Custom items remain unchecked until reviewed; the agent may evaluate only when explicitly
   asked. Checked items mean requirements quality was accepted, not implementation completed.
   Return requirement gaps to Specify/Clarify and reconcile the plan before proceeding.
6. `speckit-tasks`: generate dependency-ordered test-first implementation work.
7. `speckit-analyze`: produce a read-only consistency report. Correct owning artifacts outside
   analysis and rerun until material findings are resolved.
8. `speckit-implement`: use Red → Green → Refactor. Treat checklist files/markers as read-only;
   ask before proceeding with unchecked items, as that skill requires. Only Specify/Clarify
   maintain the built-in `checklists/requirements.md`; custom checklist state is reviewer-owned.
9. `speckit-converge`: append remaining work to tasks, without editing code or upstream artifacts.
   Implement/test gaps return to tasks/implementation; requirement gaps return to Specify/Clarify;
   design gaps return to Plan. Reconcile downstream artifacts and rerun Analyze after upstream
   changes. Preserve valid task IDs/completed work; mark obsolete findings superseded. Repeat
   until all tasks are complete and no actionable convergence findings remain.

## Shared testing and publication gates

Every route maps acceptance criteria to appropriate tests and failure cases before implementation.
Use `test-coverage.yaml` beside the existing feature or short change record, following
`.specify/templates/test-coverage-template.yaml`; one acceptance row can suffice for a bounded fix.
Explain omitted layers. Review observable outcomes, fresh persistence/reload, prohibited effects,
deterministic fixtures and external-boundary mocks. Required behavior cannot remain a placeholder,
skip or expected failure. Review removed tests and weakened assertions.

Run focused tests while iterating. Before handoff run the complete offline `./run_tests.sh --verify`.
For authorized publication, select the exact committed candidate and current target first, then
run `./scripts/verify_change.sh --base <target-ref> --head <commit-sha>`; its full-suite run can
satisfy the handoff check. Browser tests are a subset of E2E. Changed head/target invalidates
earlier evidence, including for already committed work. Use explicit files with `git-push-merge`;
require current aggregate CI and resolved review findings before separately authorized merge.

Normal tests, verification, pre-push and CI stay offline with synthetic credentials; diagnostic
credentials and production data must never enter their environment. Provider changes also update
relevant live scenarios, effects/read-back, prerequisites, cleanup/recovery and spending bounds.
Reuse valid differential evidence. Live execution requires separate authorization.

Report the route/reason, change artifacts, diagnosis/acceptance evidence, actual tests/results,
review findings and remaining limits. Report Offline verified, Live pending/verified/not required,
Committed/Pushed, Merged and Deployed separately. Do not publish, merge, deploy or make external
mutations without authorization. Do not claim completed behavior with unresolved relevant gaps.
