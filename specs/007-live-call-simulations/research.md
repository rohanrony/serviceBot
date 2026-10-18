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
