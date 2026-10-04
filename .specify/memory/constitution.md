<!--
Sync Impact Report
Version change: unadopted scaffold -> 1.0.0 (initial adoption)
Modified principles: none; all five principles replace undefined scaffold slots.
Added principles:
- I. Simple Architecture and Clear Ownership
- II. Reliable State and Provider Operations
- III. Privacy and Trusted Integrations
- IV. Strict Test-First Development
- V. Observable Calls and Human Recovery
Added sections:
- Operational Constraints
- Development Workflow and Quality Gates
- Governance (initial project rules)
Removed sections: none.
Template synchronization: dependent templates and commands read this constitution at runtime;
no template or command changes are required or included.
Deferred fields and follow-up TODOs: none.
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

### IV. Strict Test-First Development

Every behavioral change MUST begin with a meaningful test that fails for the intended reason,
followed by implementation and refactoring. Tests MUST assert observable behavior and persisted
outcomes where the operation changes stored state. Automated tests MUST use isolated test
databases and mocked providers. Assertions MUST NOT be weakened merely to make implementation
pass. The red-green-refactor sequence makes the requirement demonstrable before the change and
preserves it afterward.

### V. Observable Calls and Human Recovery

Workflows MUST expose actionable outcomes for booking conflicts, provider failures, rejected
callbacks, and exhausted retries. Caller responses MUST distinguish pending, confirmed, and
failed operations. Unsupported or unresolved requests MUST offer a supported human-handoff or
callback path. Latency-sensitive changes MUST define and verify measurable budgets in their
feature specifications. These requirements let callers and operators recover from failures
without relying on misleading success messages or unmeasured performance claims.

## Operational Constraints

Automated testing and live-provider acceptance MUST remain separate. Passing tests with mocked
providers MUST NOT be presented as evidence of live-provider behavior. Production releases MUST
satisfy portal-authentication and affected provider-validation gates, with recorded evidence of
the relevant checks. Database changes MUST document migration, recovery, and rollback procedures.

Numerical latency targets MUST remain in feature specifications. Those specifications MUST
define the measured operation, its budget, and its acceptance measurement so that performance
can be verified without imposing one undocumented measurement across every workflow.

## Development Workflow and Quality Gates

Behavioral changes MUST have explicit acceptance criteria and recorded red-green-refactor
evidence. Contributors MUST run focused validation for the affected behavior and the full suite
through `bash run_tests.sh --all` before declaring a behavioral change complete. Automated
validation MUST use test-only resources and MUST NOT contact live providers.

Reviews MUST assess test sufficiency against the acceptance criteria, including affected
failure paths, state transitions, and integration contracts. Test counts or a passing suite alone
MUST NOT substitute for this assessment. Reviews MUST verify constitution compliance and
identify any unmet production release gates.

Documentation-only changes MUST receive document and diff validation; application tests are not
required when application behavior is unchanged.

## Governance

This constitution governs project engineering and release requirements. Conflicts with older
project guidance MUST be identified and resolved explicitly rather than silently bypassing a
principle. Reviews MUST assess changes against the current constitution and record any conflict
or unmet requirement before acceptance.

Amendments MUST document their rationale, compatibility impact, and transition requirements and
receive project-maintainer approval. Each amendment MUST update the version, last-amended date,
and Sync Impact Report. The original ratification date MUST remain unchanged.

Constitution versions MUST follow semantic versioning:

- MAJOR increments apply to incompatible principle changes, removals, or redefinitions.
- MINOR increments apply to new principles, new sections, or substantive guidance additions.
- PATCH increments apply to clarifications and other changes that do not alter obligations.

Version 1.0.0 is the initial adoption of project-specific principles and governance, replacing an
unadopted scaffold.

**Version**: 1.0.0 | **Ratified**: 2026-10-03 | **Last Amended**: 2026-10-03
