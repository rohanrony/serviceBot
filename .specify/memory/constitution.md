<!--
Sync Impact Report
Version change: 1.2.0 -> 1.3.0
Modified principles: none (strict behavioral TDD and offline isolation retained)
Modified sections:
- Development Workflow and Quality Gates: add bug-fix, small-change and full Spec-Kit routes;
  restore custom checklist review in the full path; share complete offline publication gates.
- Governance: record route-selection rationale and compatibility with existing feature artifacts.
Templates reviewed: spec-template.md, plan-template.md, tasks-template.md and
test-coverage-template.yaml remain applicable; small records reuse the coverage template.
Compatibility: existing features retain their artifacts; bounded changes need no new full cycle.
Diagnostic setup uses existing read access only; no new access grants or production mutations.
Deferred fields and follow-up TODOs: none
-->

# VoiceAI Constitution

## Core Principles

### I. Simple Architecture and Clear Ownership

Each business rule MUST have one service owner shared by voice, portal, and background
workflows. Routes MUST validate inputs and delegate operations to that owner. New abstractions
and infrastructure MUST address a documented requirement. This prevents competing decisions
across entry points and keeps the application understandable.

### II. Reliable State and Provider Operations

Booking and rescheduling MUST use atomic, durable reservations. Rejected operations MUST leave
related state unchanged. Unknown availability MUST NOT produce a confirmed booking. Provider
effects MUST be idempotent and recoverable, with bounded retries and explicit failure states.
Success messages MUST reflect recorded outcomes. These rules prevent double booking, partial
updates, duplicate effects, and false confirmations during provider failures.

### III. Privacy and Trusted Integrations

Production administrative operations MUST require authorization, and provider callbacks MUST be
authenticated before mutation. Credentials MUST remain outside version control and logs. Logs
MUST redact sensitive customer content. Production call-data storage MUST have a documented
retention policy. These controls protect customer information and prevent untrusted requests
from changing business state.

### IV. Strict Test-First Development and Contract Coverage

Every feature addition, bug fix, or behavioral modification MUST strictly adhere to Test-Driven
Development (TDD): a meaningful automated test that fails for the intended reason (Red) MUST be
authored before implementation code (Green), followed by necessary design improvements (Refactor).
Tests MUST assert observable business behavior and durable persisted state. Assertions MUST NOT
be weakened, skipped, or commented out merely to allow an implementation to pass.

Testing coverage MUST be evaluated through comprehensive behavioral contract coverage across all
documented functional requirements (including happy paths, boundary conditions, concurrent races,
and error rollbacks), rather than superficial line-coverage statistics. Every resolved defect MUST
retain permanent regression test coverage. Automated test suites MUST run entirely offline with
external services mocked or captured, preventing unintended network side-effects and ensuring
repeatable, deterministic execution.
Every behavioral update MUST add or update tests for each affected acceptance contract; existing
coverage alone is not sufficient when behavior changes. User-visible browser flows MUST have
browser-based end-to-end coverage in `e2e/` in addition to focused lower-level tests. Browser
tests MUST verify observable outcomes (including notification delivery or visible notification
state when in scope), not merely that an action was submitted.

### V. Observable Calls and Human Recovery

Workflows MUST expose actionable outcomes for booking conflicts, provider failures, rejected
callbacks, and exhausted retries. Caller responses MUST distinguish pending, confirmed, and
failed operations. Unsupported or unresolved requests MUST offer a supported human-handoff or
callback path. Latency-sensitive changes MUST define and verify measurable budgets in their
feature specifications. These requirements let callers and operators recover from failures
without relying on misleading success messages or unmeasured performance claims.

## Operational and Testing Constraints

Automated testing and live-provider acceptance MUST remain strictly separated. The project
maintains two distinct, non-overlapping automated test layers with isolated lifecycles:
1. Fast unit and integration tests under `tests/`, utilizing localized test database instances and
   mocked external services (Google Calendar, Gmail, Twilio, ElevenLabs, OpenAI).
2. End-to-end acceptance tests under `e2e/`, exercising Chromium browser automation, real HTTP
   transports, domain services, and dedicated disposable loopback PostgreSQL databases
   (`voice_e2e_<random>_test`).

Test suites MUST execute with zero external network dependencies:
- External provider interactions (Twilio dispatch, Google Calendar/OAuth, ElevenLabs) MUST be
  stubbed via isolated mocks or captured SDK HTTP boundaries.
- Time-dependent logic (operating-hours deadlines, horizon reminder cadences, 4-hour lead times,
  cutoff calculations, and quiet-hour releases) MUST use deterministic simulated clocks; timing
  sleeps (`time.sleep`) MUST NOT be used in automated tests.
- Knowledge-base and temporary file operations MUST redirect to isolated scratch directories.
- Passing tests with mocked or captured providers MUST NOT be presented as evidence of live
  provider delivery. Separate operational and live-acceptance gates apply.
- Database schema changes MUST include migration, verification, and rollback scripts.

Numerical latency targets MUST remain in feature specifications, defining the measured operation,
its budget, and its acceptance measurement.

## Development Workflow and Quality Gates

All behavioral changes MUST follow the mandatory TDD execution protocol:
1. **Requirement & Contract Analysis**: Define explicit acceptance criteria, state transitions,
   and boundary conditions based on feature specifications or PRDs.
2. **Red Phase**: Write unit/integration tests in `tests/test_<name>.py` (or acceptance contracts
   in `e2e/`) that fail for the targeted reason prior to any application changes.
3. **Green Phase**: Implement the minimal correct application logic in `serviceBot/` necessary to
   satisfy the test assertions.
4. **Refactor & Verification**: Refactor for clarity, efficiency, and resource cleanup. Validate
   locally using `./run_tests.sh` (e.g., `--file <path>`, `--service <name>`, or `--all`).

Development MUST use a route proportional to intent, uncertainty and impact, as documented in
`docs/SPECKIT_WORKFLOW.md`. The workflow MUST announce the chosen route and reason:
- Bug fixes restoring established behavior use systematic investigation, a failing regression,
  the bounded fix/refactor and review. Reuse current relevant initialization and diagnosis.
- Small clear changes use a concise acceptance/test record, appropriate test updates,
  implementation and review; a full PRD or new feature directory is not required.
- Complex or consequential features use the full Spec-Kit path: read constitution, specify,
  clarify, plan, reviewer-owned checklist, tasks, read-only analyze, implement and converge.
  Unknown root cause alone requires investigation; new intent or substantial design decisions
  discovered during investigation require escalation. Explicit full-path requests MUST be honored.

Every route MUST retain meaningful tests and acceptance-to-test mapping. Before publication,
the exact candidate and current target MUST pass static checks and the complete offline
`./run_tests.sh --verify` through `./scripts/verify_change.sh --base <target-ref> --head <commit-sha>`.
Changed source/target invalidates evidence. Current CI/review remain required before merge.
Only pure documentation changes without behavioral impact may use the documented reviewed exemption;
configuration, prompts, workflows and test infrastructure are not automatically exempt.

Diagnostic log/database access MUST be bounded, read-only and relevant to the task. Keep it
separate from offline test credentials/data. No production repair or paid/provider mutation
is authorized by initialization. Missing access MUST remain an explicit evidence limitation.

For Spec-Kit runs, custom checklists MUST remain reviewer-owned; implementation MUST NOT change
checklist markers and MUST ask before proceeding with unchecked items. Specify/Clarify may
maintain the built-in requirements checklist. Converge MUST remain append-only: implementation
or test gaps return to tasks/implementation, requirement changes to Specify/Clarify, and design
changes to Plan. Reconcile downstream artifacts and rerun Analyze after upstream changes.
Repeat implementation/convergence until all tasks complete and no actionable findings remain.

Before declaring any behavioral change complete:
- Contributors MUST run focused test validation for the affected service and ensure the full
  relevant suite passes cleanly without regressions.
- Code reviews MUST assess test sufficiency against acceptance criteria, verifying failure paths,
  concurrent races, and contract boundaries. Test counts or a green status alone MUST NOT substitute
  for contract verification.
- Documentation-only changes MUST receive document and diff validation; application tests are not
  required when application logic remains unchanged.

For every update, validation MUST cover the changed behavior at the lowest useful level and at each
affected integration boundary. If a user journey is performed in a browser, the relevant browser
end-to-end test MUST be included in validation; unit or API tests alone do not cover that journey.

## Governance

This constitution governs project engineering, testing standards, and release requirements.
Conflicts with legacy project documentation or informal practices MUST be explicitly resolved
in favor of this constitution. Reviews MUST evaluate changes against this constitution and block
any PR or commit that bypasses these principles.

Amendments MUST document their rationale, compatibility impact, and transition requirements, and
must be approved by project maintainers. Each amendment MUST update the version, last-amended date,
and Sync Impact Report. The original ratification date MUST remain unchanged.

Constitution versions MUST follow semantic versioning:
- MAJOR increments apply to incompatible principle changes, removals, or redefinitions.
- MINOR increments apply to new principles, new sections, or substantive guidance additions.
- PATCH increments apply to clarifications and other changes that do not alter obligations.

Version 1.3.0 adds proportional development routes and scoped diagnostic initialization while
retaining strict behavioral TDD, browser contract coverage and complete exact-candidate offline
publication verification. Full Spec-Kit runs include reviewer-owned checklist review and iterative
convergence; existing feature artifacts and valid evidence remain reusable where still applicable.

**Version**: 1.3.0 | **Ratified**: 2026-10-03 | **Last Amended**: 2026-10-19
