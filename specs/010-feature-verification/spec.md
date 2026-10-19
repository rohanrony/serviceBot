# Feature Specification: Feature testing and merge readiness

**Created**: 2026-10-19
**Status**: Implemented locally; isolated offline candidate verified; publication/hosted CI pending
**Input**: Feature testing and merge-readiness workflow supplied in this conversation.

## User Scenarios & Testing

### US1 — Verify the intended candidate (P1)

A contributor selects a committed candidate and target. Verification preserves dirty work,
collects and executes both complete offline suites, including browser journeys within E2E,
and retains evidence that identifies the candidate and environment.

Acceptance: AC1 full success produces a receipt; AC2 failures, missing execution/reports,
filtering, skips, expected failures, or stale/wrong-candidate evidence block publication.

### US2 — Publish without bypassing verification (P1)

Acceptance: AC3 already committed work is verified; branch selection precedes verification;
only explicit files are committed; neither bypass flags nor direct main publication are supported.
AC4 a pre-push hook validates every updated branch against the current remote target.

### US3 — Review behavioral coverage and merge evidence (P1)

Acceptance: AC5 each changed contract maps observable success, failure, preconditions,
invariants, tests, layers and remaining live proof; generated placeholders fail.
AC6 CI uses the same gate with synthetic credentials, disposable PostgreSQL and Chromium;
an aggregate check rejects missing/failed mandatory jobs and reports.

### Edge Cases

Dirty/staged unrelated files; deleted refs; tags; renamed/deleted tests; clean commits;
changed base; interrupted execution; deselection; xfail/xpass; stale artifacts; missing
browser execution; setup/teardown errors; missing dependencies; fork PRs; merge queue.

## Requirements

- FR-001: AC1–AC2 require isolated exact-commit verification and fresh, complete evidence.
- FR-002: AC3–AC4 require exact-SHA publication gates without automatic main updates.
- FR-003: AC5 requires acceptance-to-test matrices and behavior-based test review.
- FR-004: AC6 requires complete offline CI and a proposed protected-branch aggregate check.
- FR-005: All stages retain explicit offline/live/merged/deployed states. Live execution
  and remote protection mutations require separate authorization.

### Key Entities

Candidate (head + target SHAs), coverage matrix, collection manifest, execution manifest,
verification receipt, hashed artifacts, review and remaining live acceptance.

## Success Criteria

- SC-001: Every specified invalid-evidence scenario is rejected by regression tests.
- SC-002: A disposable sample feature can verify and publish to a local bare remote while
  preserving unrelated changes; main remains unchanged.
- SC-003: Full application verification is attempted and exact outcomes are retained;
  any existing application failures remain explicit blockers.

## Assumptions

The supplied brief resolves the requirements; no material clarification is needed. Full
verification is the default even for docs; reviewed documentation exemptions are manual
review policy, with no automatic bypass added. Local receipts are integrity-checked
developer evidence, not signed attestations. Server rules and review provide enforcement.
