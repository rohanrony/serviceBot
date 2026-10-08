---
name: speckit-workflow
description: Run the project's complete Spec-Kit feature workflow, including test-first implementation and iterative convergence. Use for a feature or behavior change; not for documentation-only edits.
compatibility: Requires this project's .specify/ setup and Spec-Kit skills.
---

# Project Spec-Kit Workflow

Run this skill with a feature or behavior-change description, for example:
`$speckit-workflow Add browser notifications when an appointment is confirmed`.
Treat the user's request as the source of intent. For an existing feature, continue its spec/task
cycle when intent is unchanged; create a new feature only for new work. Do not run this workflow
for documentation-only changes that do not alter behavior.

Follow [the project workflow](../../../docs/SPECKIT_WORKFLOW.md) and the detailed instructions in
each corresponding `speckit-*` skill. Respect their prerequisites, hooks, artifact boundaries, and
validation rules. Do not bypass a stage just because a later stage can proceed without it.

## Workflow

1. Read `.specify/memory/constitution.md` and identify the active feature directory, if any. If
   there is no active feature for this request, use `$speckit-specify` to create one.
2. Run `$speckit-clarify` before planning when material ambiguity or unresolved decisions remain.
   Resolve those questions in the spec; do not turn an assumption into acceptance criteria.
3. Run `$speckit-plan`, then `$speckit-tasks`. Ensure the spec and plan identify each changed
   behavior contract and its needed test layers. User-visible browser journeys require tests in
   `e2e/`; notification scenarios must assert the expected observable notification outcome.
4. Run `$speckit-analyze` after tasks exist. Resolve critical inconsistencies and missing test
   tasks before implementation; rerun analysis after changing the spec, plan, or tasks.
5. Run `$speckit-implement` using Red-Green-Refactor. For each behavioral change, first add or
   update a meaningful test and confirm it fails for the intended reason, then implement, refactor,
   and run focused validation. Before handoff, run the relevant complete test suite, including
   browser `e2e/` tests for affected browser journeys. Report exact commands and results.
6. Run `$speckit-converge` after implementation. If it finds actionable gaps, use the feedback
   routing below; do not stop after reporting or appending tasks.

## Converge feedback loop

Return to the earliest artifact that owns each finding:

- Missing implementation or regression/acceptance coverage with approved requirements and design:
  keep the converge task traceable, add/fix the test first, run `$speckit-implement`, then converge
  again.
- Missing test layer for a browser journey: add the browser test task, implement it before any
  related behavior change, run the relevant browser suite, then converge again.
- Wrong, incomplete, or changed requirement: update the active spec and clarify it; reconcile the
  plan and tasks, rerun analyze, implement, then converge.
- Incorrect architecture, data model, or integration decision: update the plan and reconcile tasks;
  also revisit the spec if user-visible behavior changes. Rerun analyze before implementation.
- Artifact inconsistency: fix the earliest inconsistent artifact, reconcile downstream artifacts,
  analyze again, then implement.

The converge command is append-only and must not edit code or upstream artifacts. If upstream
changes require task regeneration, preserve completed work and valid IDs where possible; explicitly
mark obsolete convergence findings as superseded rather than silently dropping or blindly retaining
them. Repeat implementation and convergence until there are no actionable findings and all tasks
are complete. If the loop uncovers a decision that requires the user, ask a focused question and
pause that dependent work; continue independent safe work when possible.

## Completion

Report the feature directory, spec/plan/tasks changes, convergence iterations, remaining
limitations, and validation results. Do not claim completion if tasks remain, converge reports
actionable gaps, or affected browser tests were not run. Offline mocks do not prove live-provider
delivery; keep live acceptance separate. Do not commit, push, deploy, or perform external actions
unless separately requested.
