# Research decisions

- Current API: POST /v1/convai/agent-testing/create, POST
  /v1/convai/agents/{agent_id}/run-tests, GET
  /v1/convai/test-invocations/{id}, POST corresponding /cancel.
  Simulation discriminant type=simulation, simulation_scenario, success_conditions,
  simulation_max_turns, dynamic_variables, explicit simulation_environment.
- Run statuses pending/passed/failed/cancelled; missing credits_used is unknown spend.
- https://elevenlabs.io/docs/api-reference/tests/create
- https://elevenlabs.io/docs/api-reference/tests/run-tests
- https://elevenlabs.io/docs/api-reference/tests/test-invocations/list
- Subscription character_limit is not silently treated as a compatible simulation
  credit limit. Require an explicitly verified credit allowance and period identity,
  cross-check current account reset and remaining usage during live preflight.
- The root pytest fixtures disable providers; live execution must be outside pytest.
- Current config/KB paths are file-relative; copy source into an isolated directory.
- Tool sync script updates prod and dev and is never executed by the runner.
- Codebase graph tools unavailable in this session. Targeted current source inspected;
  graph generation and coverage cannot be asserted.

- Workspace post-call callbacks can be inherited. Pin the dedicated webhook ID via
  platform_settings.workspace_overrides.webhooks; resolve its enabled HMAC URL
  through GET /v1/workspace/webhooks?include_usages=false. Preserve other platform
  settings; inspect GET /v1/convai/settings for unsafe initiation hooks and re-read
  the owned clone. Sources: https://elevenlabs.io/docs/api-reference/webhooks/list
  and https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks
  and https://raw.githubusercontent.com/elevenlabs/elevenlabs-python/main/src/elevenlabs/types/agent_workspace_overrides_input.py

Standard-agent read-back: GET agent succeeded. The workflow contains one start
node with no edges/subgraphs, plus 11 shared IDs and fully materialized webhook
tools. GET /v1/convai/tools/{id} supplies the same tool_config shape. Shared tool
resolution is read-only and never edits the source. GET /v1/user/subscription
returned 401 missing_permissions explicitly naming user_read; no quota was inferred.
Sources: https://elevenlabs.io/docs/api-reference/tools/get and
https://github.com/elevenlabs/skills/blob/main/setup-api-key/SKILL.md .


## FR-019/020 follow-up
The completed two-turn calibration billed 126 credits (81 LLM,45 platform), while the subscription counter remained unchanged. Do not assert credit-unit mapping from that observation. Use an explicit separately capped single-case calibration. Baseline preservation is already checked after cases, so opt-in admission and before-submission validation extend the same owner.

## Remaining full delta observations (2026-10-19)

Read-only native rechecks at 01:40 UTC returned healthy HTTP200, 21,904 remaining
credits and valid reference-agent/tools/deployed HMAC configuration. Earlier
aggregate health/provider errors did not reproduce; they are retained as failed
readiness observations, not diagnosed as application or credential faults.

The draft 900-credit-per-case estimate is a conservative configuration assumption,
not a measured bound. Across 34 new cases it totals30,600; the20% reserve would
require a38,250 ceiling. Current balance is8,696 below the estimate. Neither the
medium authorization nor a draft plan authorizes new full-stage spending.

The initially deployed booking owner creates three per-service rows for the
three-service candidate, while C25's catalog expects two grouped rows. C30's
selective removal also conflicts with that deployed whole-group cancellation.
The owner has since approved grouping per technician and selective removal,
correcting the latter to keep the selected start and shorten its end. The local
implementation preserves the original C25 two-row/150-minute expectation and
checks explicit C30 selected-only cancellation with an unchanged companion.
These product decisions are resolved; deployed migration, tool, prompt and native
fixture evidence remain separate prerequisites.

Same-handset permission covers authorized delivery, but cannot prove distinct
customer phone ownership, an unenrolled recipient or distinct staff sender after
reassignment. Real windows, elapsed deadlines and actual inbound/provider history
are prerequisites; local fault fixtures and fabricated signatures cannot replace
native evidence. Production messaging and system Gmail changes remain deferred.

The Google fixture uses a deterministic owned event, no attendees, conditional
ETag deletion and a durable ambiguous-write stop. Captured provider tests exercise
these boundaries; actual account scopes, cache behavior and deployed free-to-busy
causality remain live prerequisites. Primary references:
https://developers.google.com/calendar/api/v3/reference/events/insert and
https://developers.google.com/calendar/api/guides/version-resources and
https://developers.google.com/identity/openid-connect/openid-connect.

The full draft initially retained the historical medium-only
`owned_agent_policy` transformation. Its exact guard rejects an already promoted
canonical-plus-linked prompt because the v1 policy is no longer the prompt suffix.
That failure reproduces offline and explains the aggregate provider-readiness
message despite successful direct provider checks. Remove the obsolete draft-only
transformation; do not weaken the historical policy guard or edit the native agent.

Instance-replacement evidence: runtime logs show shutdown01:31:26UTC and a new
instance startup01:34:24UTC on the same deployed commit. Current Free-plan service
metadata and https://render.com/docs/free document local file loss on idle
spin-down/restart. The app's reverted prompt fingerprint exactly matches the
pre-promotion proposal source; other-config fingerprint is unchanged and saved
primary prompt remains204af4. Five authored KB backups match exactly, while the
generated catalog misses12 of46 native service names. File rollback after instance
replacement is supported by these observations; no settings write was issued in
this phase. Rebuild only derived catalog artifacts from PostgreSQL at startup,
then verify native restoration after the reviewed app deployment.

The selective tool proposal copies the currently referenced native cancel tool,
retaining its authentication and all existing fields, and changes only the
reviewed description plus optional `service_name`. The proposed attachment patch
replaces one primary-agent tool ID; the original shared tool is preserved. Source
and candidate fingerprints plus complete dependent-agent pagination are retained
in the private proposal. No tool creation, agent patch or paid submission has
occurred. Omitting `service_name` is permitted only with explicit whole-linked-
visit consent or for an unlinked appointment; consent for one technician's block
does not authorize cancelling companion appointments.

C31 now has a source-owned separated-callback fixture and strict offline oracles:
two designated qualified technicians, two 15-minute callbacks starting30minutes
apart, independent reservations/projections and no merged appointment. Read-only
native availability, actual business policy and owned cleanup remain prerequisites.

The remaining messaging cases have additional source constraints. Staff routing
precedes customer STOP handling for shared handset4893, and late-confirmation
routing pools all staff IDs sharing that phone. This handset cannot establish
independent customer opt-out or distinct original/replacement senders. Voice and
customer booking triggers also explicitly bypass quiet hours, and the outbox
propagates that flag. C41's expected deferral therefore needs an owner decision
about the applicable flow; waiting alone cannot prove it. Preserve these blockers
without changing the deferred production messaging configuration.
