# ElevenLabs call simulation planning brief

## Objective

Test the ElevenLabs agent through repeatable simulated conversations, then verify
the resulting bookings, calendar effects, portal state and notifications. The
agent saying an action succeeded is not sufficient.

This is a seed for a separate GitHub Spec-Kit planning session, not authorization
to run paid simulations, create live bookings, send messages or deploy changes.

## Starting context

The earlier local suites passed, but capture or block provider traffic. The user
has since pushed the fixes; verify the actual deployed commit and agent
configuration before live testing. WhatsApp delivery remains an explicit gate.

Reuse [the existing test plan](../e2e/TEST_PLAN.md) and
[project Spec-Kit workflow](SPECKIT_WORKFLOW.md); extend rather than replace coverage.

## Scope

- In: a small opt-in runner, versioned scenarios, environment checks, repeatable
  test data, outcome assertions, cleanup and a readable evidence report.
- Out: application behavior fixes, production load testing, unrestricted outbound
  calls/messages, or claiming API simulations alone prove real phone/audio behavior.

| Layer | Purpose | Boundary |
| --- | --- | --- |
| Mocked simulations | Check multi-turn reasoning, consent and tool arguments before deployment | Use controlled tool responses; fail closed on missing mocks and inspect non-mockable tools for side effects |
| Live backend simulations | Exercise real tools against the intended deployed backend | Prefer isolated staging data and sandbox integrations; require explicit approval for production effects |
| Real phone smoke test | Check actual audio/telephony and receiver-confirmed notifications | Separate, explicitly authorized calls and designated recipients |

Use the current create-test/run-tests APIs. ElevenLabs documents the older
`simulate-conversation` endpoint as deprecated, with removal on October 31, 2026.
Recheck API schemas during planning; do not build against a retired endpoint.

## Initial scenario coverage

- New and returning customers: collect correct identity, vehicle and issue details;
  preserve customer ownership and avoid duplicate bookings on corrections/retries.
- Availability and booking: valid booking, lead time, business hours, timezone,
  unavailable slots and unknown/failed calendar responses.
- Multiple services: qualified technicians, contiguous linked appointments,
  unavailable second specialist and atomic failure without partial bookings.
- Callbacks, rescheduling and cancellation: required consent, preserved callback
  type, whole-visit changes, released capacity and correct downstream messages.
- Conversation quality: recording disclosure, ambiguous requests, FAQ unknowns,
  refusal, handoff and attempts to bypass business rules.
- Failures and recovery: tool timeout, dependency rejection, repeated tool calls,
  notification failure, delayed callbacks and interrupted conversations.

## Evidence and acceptance

Define each scenario's preconditions, caller behavior, expected/forbidden tool
calls, state changes, side effects and cleanup. Repeat critical scenarios within
an agreed budget and retain every failure.

Retain run/scenario IDs, backend commit, agent version/configuration, timestamps,
transcript, tool arguments/results and request/visit IDs. Verify fresh state reads
and browser reloads; include calendar IDs, notification SIDs, delivery callbacks
and handset confirmation when enabled. Redact secrets and personal details.

Require no unauthorized mutation, incorrect booking, partial visit, duplicate
effect or false success claim. Provider acceptance, connected badges and outbox
`DELIVERED` labels do not prove message delivery. Mark unsupported/unrun checks
explicitly; distinguish synthetic webhooks from genuine provider callbacks.

## Planning action items

- [ ] Inspect the constitution, existing tests and current ElevenLabs testing API.
- [ ] Verify deployed code, agent version, tool URLs, authentication and caller-context variables.
- [ ] Choose the isolated environment, allowlisted recipients and sandbox accounts.
- [ ] Define scenario fixtures and the requirement-to-test coverage matrix.
- [ ] Design the runner's explicit live opt-in, run/cost/turn/time limits and abort behavior.
- [ ] Specify persisted-state, browser, calendar and delivery assertions, including safe cleanup of only run-owned data.
- [ ] Determine whether simulations produce normal call-history records and post-call webhooks; document gaps requiring a real call.
- [ ] Generate traceable test-first tasks, reporting requirements and staged acceptance gates; run artifact analysis before implementation.

Live preflight must check WhatsApp enrollment/messaging-window requirements and
worker availability across idle periods/restarts. Do not replay the entire outbox,
silently fall back to production, or repeatedly retry an ambiguous mutation.

## Decisions for the planning session

1. Which deployment, database, agent and test accounts will live runs use?
2. Which external effects and recipients are approved, and what are the run/cost limits?
3. What repetition count, pass criteria, artifact retention and cleanup rules are required?

## Prompt for the next session

> Plan ElevenLabs call simulation testing from
> docs/LIVE_CALL_SIMULATION_BRIEF.md. Read the constitution and existing coverage.
> Run the project's Spec-Kit specify, clarify, plan, tasks and analyze stages.
> Separate mocked, live-backend and real-phone acceptance; resolve environment,
> recipients, budget and side effects. Produce spec.md, plan.md and tasks.md with
> traceable criteria and test-first work. Stop for review before implementation,
> paid runs, production changes, calls or messages. Do not create GitHub issues
> or push changes without a separate request.

## Official references

- [ElevenLabs agent testing](https://elevenlabs.io/docs/eleven-agents/customization/agent-testing)
- [Run tests API](https://elevenlabs.io/docs/api-reference/tests/run-tests)
- [Legacy simulation API deprecation](https://elevenlabs.io/docs/eleven-agents/api-reference/agents/simulate-conversation)
