# Project Spec-Kit Workflow

Trigger the complete cycle with **`$speckit-workflow`** and a feature description. Its project-local
skill is defined in `.agents/skills/speckit-workflow/SKILL.md`.

This document is the project's outer loop for using Spec-Kit. It connects the individual
commands into one repeatable, iterative process. The constitution is the governing policy;
this document is the operational guide. See the [official Spec-Kit workflow for evolving
projects](https://github.github.io/spec-kit/guides/evolving-specs.html) for upstream context.

## When to use it

Use this workflow for every feature, bug fix, or other change that alters application behavior.
For a small, bounded change, keep the artifacts and scope small; do not skip acceptance criteria,
test-first implementation, or verification. Documentation-only changes that do not affect behavior
can use document and diff validation without creating a feature cycle.

Start a new feature directory for a new body of work. For follow-up work on an existing feature,
first decide whether the accepted requirements are unchanged. If they are, continue its task and
convergence loop. If user-visible requirements or acceptance criteria changed, update the spec and
reconcile downstream artifacts; do not quietly treat changed intent as an implementation-only gap.
Keep prior feature artifacts as history unless the team explicitly chooses a living-spec approach.

## End-to-end sequence

1. **Constitution** — Read `.specify/memory/constitution.md` and honor its constraints. Run
   `$speckit-constitution` only when project-wide engineering policy itself needs to change.
2. **Specify** — Run `$speckit-specify` with the requested behavior. Capture user-visible
   outcomes, functional requirements, acceptance scenarios, edge cases, and measurable success
   criteria. Include notification outcomes explicitly when notifications are in scope.
3. **Clarify** — Run `$speckit-clarify` when requirements have material ambiguity, conflicting
   interpretations, or unresolved decisions. Update the spec with the resolved answers before
   planning. Do not implement assumptions that change the intended behavior.
4. **Plan** — Run `$speckit-plan` to define architecture, data changes, integrations, test layers,
   and implementation constraints. Identify which acceptance scenarios require browser automation
   in `e2e/` and which can be validated at unit or integration level.
5. **Tasks** — Run `$speckit-tasks` to produce an ordered, traceable implementation checklist.
   The spec/plan MUST make the TDD and affected test layers explicit so generated tasks include
   test-first work for each changed contract, including browser end-to-end tests for changed
   browser journeys. Schema changes include migration, verification, and rollback.
6. **Analyze** — Run `$speckit-analyze` before implementation. Resolve material contradictions,
   missing acceptance coverage, unsupported plan decisions, and task gaps. If the spec, plan, or
   tasks change, analyze again before implementation.
7. **Implement** — Run `$speckit-implement`. Follow Red-Green-Refactor: add or update a meaningful
   test first, confirm it fails for the intended reason, implement the smallest correct change,
   then refactor. Keep tests aligned to changed acceptance criteria, not just code paths. Run focused
   tests while iterating and the relevant complete suite before handoff. For user-visible browser
   behavior, run the relevant `e2e/` browser tests; unit/API coverage alone is insufficient.
8. **Converge** — Run `$speckit-converge` after implementation to compare the current code with the
   spec, plan, tasks, and constitution. Converge appends traceable remaining-work tasks to
   `tasks.md`; it does not change code or rewrite the upstream artifacts.

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

## Handoff record

For each completed cycle, report the feature/spec directory, the artifacts changed, any convergence
iterations completed, the test commands and outcomes (including browser tests when applicable),
and any remaining limitations. Do not claim browser coverage unless a browser test was added or
updated and actually executed.
