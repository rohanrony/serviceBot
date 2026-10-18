# Returning-caller single-case calibration

Private config opts in with preserve_existing_bookings=true and calibration={credit_ceiling,case_upper_estimate,source_run_id}. Exactly --tier minimal --cases C01 (or C04), --repeat 1 is admitted. Ordinary mode retains default tier budgets and empty-baseline guard. The calibration ceiling is denominated in provider test credits independently of the subscription counter; it does not verify unit equivalence.

Preview is offline. --check performs only reads. --live creates an owned cloned agent/test then submits one invocation. Output limits: eight turns, 256 agent tokens per turn. Reports retain subset/calibration identity, baseline, actual credits, source sample and missing native observations. Original request changes or missing rows fail the run; baseline mismatch before another submission prevents it. No automatic cancellation or paid retry.

## Preserved caller identity (FR-025)

A nonempty opted-in baseline must have one exact, nonblank customer name across
all scoped rows. Use that name unchanged in scenarios and dynamic context;
synthetic run suffixes apply only to new callers. Missing or conflicting names
block both readiness and execution before provider setup. Keep complete baseline
comparisons, including customer names; any original mutation still fails.

## Active reference fidelity
GET /api/v1/portal/secrets must return a nonempty elevenlabs_agent.display_value equal to configured agent_id; mismatch/read failure blocks all mutations. Only this non-secret identity is consumed. The verified owned clone is run by POST /v1/convai/agents/{owned_id}/run-tests with tests and repeat_count, omitting agent_config_override. Its persisted prompt and registered tools remain authoritative.
