---
name: initialize-session
description: Prepare a VoiceService session for offline work or a requested investigation using bounded read-only logs and database evidence. Reuse current initialization; load only task-required access and report evidence limits.
---

# Initialize a VoiceService session

Use `$initialize-session` on its own, or follow this skill from `$speckit-workflow`.
Default to offline setup. Diagnostic mode is selected by a task needing operational logs or
database evidence, for example `$initialize-session Investigate booking errors in production
between 14:00 and 14:15 UTC`. This is a chat instruction, not a shell command or CLI flag.

This is the Codex counterpart to legacy `/init-session` and `/initialize-session`. The new
workflow uses this version; those IDE aliases are not installed by this skill. Do not execute
the old unconditional cross-workspace environment sourcing or require every provider secret.

## Reuse and local setup

1. Establish the repository, branch/revision, dirty/staged state, task and existing session
   evidence. Reuse initialized tools and current relevant diagnosis; refresh only what is
   missing, stale or from another environment. Do not repeat the whole bootstrap on each turn.
2. Check the project Python environment and tools needed for this task. Use `.venv/bin/python`
   directly; shell activation and exported variables may not persist between tool calls.
3. Offline work requires no production credentials, Render/Supabase health checks or paid calls.
   Prepare isolated test files and disposable loopback PostgreSQL when testing needs them.
   Never overwrite the developer's `.env`, reset a shared database or start unrelated services.

## Diagnostic setup, only when needed

1. Establish the target environment/service, symptom, relevant IDs and time window with timezone.
   Infer these from the request/evidence where possible; ask only for a missing material scope.
   Logs and database reads are optional evidence sources, not mandatory probes for every bug.
2. Prefer connected read-only log/database tools and existing authenticated sessions. Discover
   available capabilities before claiming access. If an existing project reader is needed,
   inspect it for side effects and use it with a bounded scope. Authenticate only the required
   tool in that subprocess using configured credentials; never print values, connection URLs,
   full environments or secret-bearing errors. Report missing key names/access only. Do not
   inspect unrelated credential files or carry blanket permissions from legacy instructions.
3. Constrain log queries by service, time and relevant identifiers, with bounded pagination.
   Query application records only when needed to test a specific hypothesis, selecting relevant
   columns/IDs with a row limit. Use a read-only database role/transaction and statement timeout;
   for a direct PostgreSQL client, set the transaction read-only before application queries.
   A SELECT that invokes a mutating function is not an acceptable read-only query.
4. Record environment, query/filters, window, observation time, result limits and redacted
   evidence references. Distinguish log emission time from ingestion time. State missing access,
   retention gaps, truncation and incomplete pagination. Do not interpret a limited empty result
   as proof that no error occurred, or successful connectivity as application health.
5. Correlate logs with fresh database reads when the hypothesis needs both. Keep observed facts,
   hypotheses and confirmed cause separate. Use only the minimal redacted data needed to create
   an isolated deterministic regression fixture; keep sensitive evidence out of Git artifacts.

Diagnostic mode authorizes relevant reads within the user's task and existing access. It does
not authorize production writes, data repair, migrations, restarts, deployment, notifications,
provider calls or paid simulations. Explain and request separate authorization if the task
later needs a mutation. Missing access leaves that evidence pending; continue useful offline
investigation without claiming the production cause is proven.

## Handoff to implementation and tests

Report local readiness and diagnostic evidence/access limitations separately, including what
was reused. Return to systematic debugging before any bug fix. A confirmed local regression
is required before changing the behavior; evidence collection is not a substitute for a test.

Keep diagnostic access outside automated test execution. Never source the diagnostic environment
into `run_tests.sh`, verification, hooks or CI, and never point fixtures at production. Use the
sanitized exact-candidate verifier for publication. Offline results do not establish that a
production incident is resolved or a live provider operation succeeded.
