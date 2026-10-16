# Pre-Implementation Review Checklist: Catalog Service Agent Tagging & Multi-Service Scheduling

**Purpose**: Requirements-quality validation ("Unit Tests for English") covering Portal UI, Scheduling Engine, State Integrity, Telephony, and Calendar Sync before implementation
**Created**: 2026-10-15  
**Feature**: [spec.md](file:///Users/rohanroy/Coding/voiceService/specs/006-catalog-service-agent-tagging/spec.md) | [plan.md](file:///Users/rohanroy/Coding/voiceService/specs/006-catalog-service-agent-tagging/plan.md)  

**Review Ownership**: This checklist is a reviewer-owned requirements-quality review artifact. Mark an item `[x]` only when the reviewer confirms that the corresponding requirement in `spec.md` or `plan.md` is clearly, completely, and unambiguously specified.  
**Marker Semantics**: `[x]` indicates reviewer approval of requirements quality. It does NOT mean the code has been written or verified. Newly generated items MUST remain `[ ]` until reviewed.

---

## 1. Catalog Service-to-Agent Tagging & Portal UI

- [ ] CHK001 Are data model requirements for the many-to-many relationship (`service_staff_agents`) explicitly defined with cascading rules? [Completeness, Spec §4.1, Plan §1]
- [ ] CHK002 Is the fallback behavior for untagged catalog services unambiguously defined as open to any active staff agent? [Clarity, Spec §1.2, Spec §3]
- [ ] CHK003 Are visual display requirements defined for assigned technician badges in the Services Catalog table? [Clarity, Spec §2 US1, Plan §4]
- [ ] CHK004 Are interactive form requirements specified for multi-selecting staff agents in both Add Service and Edit Service drawers? [Completeness, Spec §2 US1]
- [ ] CHK005 Is the API contract for creating and updating service tags defined with explicit request/response schemas? [Traceability, Contracts §portal-service-tagging-contract]
- [ ] CHK006 Does the specification define what happens to existing appointment records when a tagged technician is deleted from the platform? [Edge Cases, Spec §3]

---

## 2. Multi-Service Scheduling & Allocation Logic

- [ ] CHK007 Is the priority rule favoring a single qualified technician at the customer's desired time slot clearly specified over multi-agent splits? [Clarity, Spec §1.2, Spec §2 US2]
- [ ] CHK008 Are contiguous back-to-back appointment requirements explicitly quantified with a 0-minute handoff buffer? [Clarity, Spec §2 US3, Spec §3]
- [ ] CHK009 Is the greedy partitioning algorithm for 3 or more services unambiguously specified to minimize bay and technician handoffs? [Completeness, Spec §Clarifications, Spec §3]
- [ ] CHK010 Are non-overlapping dual callback requirements specified with an explicit minimum separation window (>= 30 minutes)? [Measurability, Spec §2 US4, Spec §3]
- [ ] CHK011 Does the specification clearly define how mixed requests (1 in-shop appointment + 1 remote callback consultation) are split and scheduled? [Coverage, Spec §3]
- [ ] CHK012 Are availability search permutation rules documented when requested services have no mandatory operational sequence? [Consistency, Spec §3]

---

## 3. Dynamic Operating Hours & Closing Cutoff

- [ ] CHK013 Are closing boundary requirements dynamically derived from configured business hours rather than hardcoded 6:00 PM assumptions? [Clarity, Spec §1.2, Spec §2 US5]
- [ ] CHK014 Is the formula for evaluating multi-service duration against the closing hour explicitly defined ($T_{start} + \sum D_i \le T_{close}$)? [Measurability, Spec §2 US5, Plan §1]
- [ ] CHK015 Are non-operating days and weekend exclusions dynamically derived from `business_days` in `config.json`? [Completeness, Spec §2 US5]
- [ ] CHK016 Are minimum booking lead time requirements (4-hour preparation buffer) consistently enforced across multi-service visits? [Consistency, Spec §3]

---

## 4. State Integrity, Concurrency & Atomic Rollback

- [ ] CHK017 Are atomic transaction requirements specified with row-level locks on `mock_calendar_slots` across all technicians' segments? [Completeness, Constitution Principle II, Plan §2]
- [ ] CHK018 Is the rollback requirement explicitly defined to leave zero orphaned reservations if any technician's segment fails? [Edge Cases, Spec §3, Plan §2]
- [ ] CHK019 Is the linkage mechanism between companion appointments specified using both `linked_appointment_id` and a shared `visit_group_id`? [Traceability, Spec §4.2, Data-Model §4]
- [ ] CHK020 Are database migration and index requirements documented for high-concurrency lookups on `visit_group_id` and `service_staff_agents`? [Completeness, Plan §1, Data-Model §3]

---

## 5. Lifecycle Management: Revision, Cancellation & Decline

- [ ] CHK021 Is the customer mental model of a "single unified visit" clearly defined for cancellation and reschedule operations? [Clarity, Spec §Clarifications, Spec §3]
- [ ] CHK022 Are partial revision requirements specified for when a customer requests to drop one service while retaining the companion service? [Completeness, Spec §Clarifications, Plan §2]
- [ ] CHK023 Is the automated reassignment workflow documented when a technician declines (`D`) an appointment confirmation SMS? [Completeness, Spec §Clarifications, Spec §3]
- [ ] CHK024 Are supervisor escalation requirements explicitly defined when auto-reassignment cannot find an alternative technician free at that slot? [Recovery, Spec §3, Plan §2]

---

## 6. Telephony Prompts & Calendar Integration

- [ ] CHK025 Are natural language voice assistant prompt requirements specified to clearly announce both technicians and their respective start/end times? [Clarity, Spec §3, Contracts §multi-service-scheduling-contract]
- [ ] CHK026 Are dynamic closing time strings specified for telephony voice instructions to match the configured closing hour? [Consistency, Spec §2 US5, Plan §5]
- [ ] CHK027 Is the unified customer Google Calendar invite format specified with full visit duration and both technicians listed? [Completeness, Spec §3, Research §Decision 5]
- [ ] CHK028 Is the fallback requirement documented to generate two separate calendar events if unified multi-technician sync encounters provider errors? [Edge Cases, Spec §3, Plan §6]

---

## 7. Testability & Quality Gates

- [ ] CHK029 Are all automated tests required to run 100% offline with external mocks per project Constitution Principle IV? [Compliance, Constitution Principle IV, Plan §Technical Context]
- [ ] CHK030 Are explicit test scenarios specified covering single-agent assignment, back-to-back splits, dynamic closing boundaries, and atomic rollbacks? [Traceability, Quickstart §Scenario 1-5, Tasks §Phase 3]
- [ ] CHK031 Are regression safeguards defined to guarantee existing single-service bookings continue functioning without behavioral alteration? [Coverage, Spec §5 SC-005]

---

## Notes

- Mark items `[x]` only after reviewer examination confirms the requirement-quality criterion is satisfied in the specification.
- Leave items unchecked (`[ ]`) when requirements still require clarification or reviewer evaluation.
- `$speckit-implement` reads this checklist as a readiness gate and must not modify checkbox markers.
