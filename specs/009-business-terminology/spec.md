# Feature Specification: Configurable business terminology and intake

Created: 2026-10-19 | Status: Accepted for local implementation
Feature branch: `codex/configurable-business-intake`. Delivery: commit and push; maintainer merges separately.
Input: Use Agent everywhere and support different businesses through Config.

## User Scenarios & Testing
### US1 - Consistent agent terminology (P1)
Operators see Assigned Agents in Services, and Agent in assignment, analytics, trace, and notification text.
Acceptance: browser Services header and assignment form use Agent; existing URLs and stored identifiers remain compatible.
### US2 - Switch business through Config (P1)
Operators save business name, industry, whether automotive details apply, and custom intake fields (label, text/number, required).
Acceptance: configuration survives reload; a general business creates and edits a request with its configured fields and no vehicle; recorded values survive reconfiguration.
### US3 - Consistent voice and integrations (P1)
Configured intake is described to voice tools and persisted with bookings. A business can generate a neutral greeting and prompt from Config; custom prompts remain editable.
Acceptance: missing or invalid required data fails before mutation; generic summaries and default notifications do not assume an automotive business. Existing automotive booking inputs remain accepted.

## Requirements
- FR-001: Use Agent in application-owned operator/customer text; preserve existing route, tool, SQL and DOM identifiers for compatibility.
- FR-002: Config exposes business name, industry, optional automotive intake, and at most 20 custom text/number fields with unique stable keys and nonempty labels.
- FR-003: Save/load and validate the profile; reject malformed configuration without changing persisted config or synchronizing a prompt.
- FR-004: Create/edit/list requests persist structured intake independently of vehicles; automotive details remain supported when enabled. Preserve historical values and records across profile switches.
- FR-005: Portal and voice share validation. Missing required values, unknown fields, wrong types, nonfinite numbers, and overlong values fail before booking/customer mutations.
- FR-006: Config can explicitly regenerate neutral voice instructions and greeting using business identity and intake; saving other settings preserves custom prompt text. Voice required-fields tool returns the configured schema.
- FR-007: Summaries, newly generated prompts and app-owned notification copy use business-neutral language. Existing business-specific catalog, knowledge, custom templates and prompts remain operator-controlled and their review is explained in Config.
- FR-008: Additive database changes have forward, verification, and safe rollback scripts. No production/external state changes during implementation.

## Edge Cases
Empty custom fields, optional fields, zero number values, duplicate keys, removed fields with historical values, legacy requests without intake, existing automotive requests after business switch, hostile labels rendered as text, and rejected writes leaving state unchanged.

## Key Entities
Business profile: industry, collect_vehicle_details, intake_fields. Intake field: key, label, type, required. Request intake: object of configured values, independent of optional legacy vehicle.

## Success Criteria
- SC-001: Browser can save a nonautomotive profile, reload, create/edit a request and reload its persisted values with no make/model/year requirement.
- SC-002: Offline tests prove rejected profile/intake writes preserve state and existing automotive behavior remains supported.
- SC-003: Source audit identifies remaining legacy schema/adapter names and configurable business content without implying live-provider acceptance.
