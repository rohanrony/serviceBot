# Tiered live conversation tests

## Run against the deployed app (no ngrok)

The deployed workflow uses the existing app at
`https://servicebot-w6hm.onrender.com`. It starts no local app, database or tunnel
and does not edit deployed staff, Google configuration or existing bookings.
It creates an owned ElevenLabs agent copy and tests; the standard profile remains
unchanged. Real business effects go through the native deployed voice tools.

A private config has been prepared at `scratch/live-simulations.deployed.json` for
this checkout, with the designated phone and Gmail recipients. On another checkout:

```sh
cp live_simulations/deployed.example.json scratch/live-simulations.deployed.json
```

Set the reference `agent_id` (or export `ELEVENLABS_AGENT_ID`), export the standard
`ELEVENLABS_API_KEY`, and fill in designated contacts and verified budget values.
The runner never loads `.env`. The JSON contains environment variable names, never
credential values. Billing units and estimates must be verified as described below;
these remain unset until verified. Configuring Gmail does not establish billing
readiness or current WhatsApp enrollment/window.

From a new terminal tab:

```sh
cd /Users/rohanroy/Coding/voiceService

# Read-only deployment/provider readiness checks. No paid submissions.
./run_live_simulations.sh --target deployed --tier minimal --check

# Once readiness passes, run the six appointment/callback lifecycle conversations.
./run_live_simulations.sh --target deployed --tier minimal --live
```

The same commands accept `--tier medium|full`, `--cases C01` and `--repeat N`.
Preview without network traffic by omitting both `--check` and `--live`.
The minimal tier exercises creation, rescheduling and cancellation for appointments
and callbacks. Medium/full catalog selections remain cumulative; a selection that
needs additional deployed state assertions, fixture SQL, occupied slots, restarts
or controlled faults is blocked before paid submission with the exact case IDs. Use isolated mode below for those fixtures;
the deployed runner never silently reduces a tier or resets live data. The deployed
state adapter currently supports C01–C06; C07–C50 retain their isolated assertions.

**Readiness checks all reachable notification destinations.** If the deployed
technicians or Gmail sender/recipient differ from the designated allowlist, fix
those settings deliberately in the app or supply the intended allowed recipients
in the private config. Selecting a technician is not an enforced delivery fence;
background assignment/escalation can reach other active technicians. Existing active
bookings for the customer also block execution. The workflow will not change those
records to make a test pass. A failed cancellation can leave a test booking active;
review its report before another run. No automatic paid retry occurs.

**Evidence and exit status:** this mode is a deployed conversation/API smoke run.
Each result includes `functional_status`, provider evaluation and fresh booking API
checks. Missing scoped database/reservation, browser, native calendar, signed
WhatsApp callback, inbox and tool-trace evidence is listed explicitly. Even successful
smoke cases therefore report overall `incomplete` (exit **3**), rather than a full
end-to-end acceptance pass. Budget/configuration blocks exit **2**; functional
failures exit **1**. The isolated runner below retains its stronger evidence checks.

The command prints its run ID and `scratch/live-simulations/<RUN_ID>/report.md`.
Inspect reports or reconcile an ambiguous charge without rerunning it:

```sh
.venv/bin/python -m live_simulations report --config scratch/live-simulations.deployed.json --run-id RUN_ID
.venv/bin/python -m live_simulations reconcile --config scratch/live-simulations.deployed.json --run-id RUN_ID
```

Explicit `cleanup --live` with the same config/run ID removes only recorded
ElevenLabs test/clone resources after billing settles. Deployed bookings, calendars,
messages and account settings are retained. Never use an isolated prepared run ID
for a deployed campaign. A new live command generates a fresh deployed run ID;
attempted IDs cannot be replayed.

For both offline suites followed by deployed smoke, use the config's target field:

```sh
./run_tests.sh --verify --live-tier minimal --live-config scratch/live-simulations.deployed.json
```

## Explicit deployed campaign ceiling

When a user explicitly authorizes a complete deployed six-case campaign beyond
the normal tier ceiling, private configuration can include:

```json
"campaign_authorization": {
  "authorization_id": "a-unique-approval-id",
  "credit_ceiling": 8160
}
```

This opt-in accepts only deployed minimal C01–C06, one pass, without `--cases`,
repetition or `calibration`. It retains verified billing units, normal case
estimates, the 20 percent reserve and all readiness/ledger checks. Authorization
and actual charges are retained; the same ID cannot fund another paid run.
Default tier limits and isolated mode are unchanged. A ceiling is admission
control, not a guaranteed provider-side cancellation cutoff.

The 2026-10-18 user approval covers one 8,160-credit campaign. It does not authorize
automatic paid retries, saved-agent edits, publication or cleanup.

## Isolated acceptance mode

The separate `live_simulations` package tests the actual ElevenLabs agent against
an isolated local app through your HTTPS tunnel. Its default `plan` operation is
offline. Paid conversations and live delivery require `run --live`.

| Tier | Cases | Per-invocation ElevenLabs ceiling |
| --- | --- | --- |
| minimal | C01–C06: book/move/cancel appointment and callback | 1% of monthly allowance |
| medium | C01–C16: core plus consent, corrections, availability and linked visits | 2% |
| full | C01–C50: all versioned scenarios | 5% |

These are ceilings, not spending targets. One repetition is the default. Twenty
percent is reserved for uncertainty. `--repeat N` repeats the selected coverage
within the **same** campaign budget and retains each result. No automatic paid
reruns occur. `--cases C03` includes C01/C02 as prerequisites and is reported as a
subset. Every required check must pass; unmet budgets and missing evidence cannot
produce a passing tier.

## Run every test layer with one command

```sh
# All offline unit/integration and E2E tests.
./run_tests.sh --verify

# Both offline layers, then one selected live tier if both pass.
./run_tests.sh --verify --live-tier minimal
```

`--live-tier` accepts `minimal`, `medium`, or `full` and explicitly enables paid
conversations and real test notifications. It is consumed by the runner and never
sent to pytest. Use `--live-config PATH` for a different private configuration and
`--live-run-id RUN_ID` to use an already prepared runtime. For example:

```sh
./run_tests.sh --verify --live-tier medium \
  --live-config scratch/live-simulations.local.json --live-run-id RUN_ID
```

Without a prepared run ID, the live stage opens guided setup in an interactive
terminal. Configure test credentials, receivers, tunnel and budget as described
below. Offline failures run both suites for diagnosis and skip the live stage.
Live stage exit status is preserved. Ordinary pytest flags pass only to offline
suites; help/collection-only modes cannot unlock live execution. The workflow
does not automatically retry live failures or clean up retained evidence.

## One-command workflow

Once you have created `scratch/live-simulations.local.json` and exported the
configured test credentials, run from the repository root:

```sh
# Offline preview; no provider requests or resource creation.
./run_live_simulations.sh --tier minimal

# Guided setup followed by the selected live campaign.
./run_live_simulations.sh --tier minimal --live
./run_live_simulations.sh --tier medium --live
./run_live_simulations.sh --tier full --live
```

Choose one live command per campaign. `--tier` defaults to `minimal` and accepts
only `minimal`, `medium`, or `full` (6/16/50 cases, 1/2/5% budget ceilings).
Use `--config PATH` for a different private config. The workflow prepares a fresh
runtime and prints its run ID, starts the isolated account-setup portal, and waits
for Enter. Complete the account/tunnel/knowledge setup below, then press Enter to
stop setup and start paid conversations. Leave the external tunnel running.
The workflow prints the report path and an exact cleanup command; evidence and
provider resources are retained until you explicitly clean them up.

If setup is interrupted, keep the printed run ID. Complete setup using `serve`
and then stop it before continuing with:

```sh
./run_live_simulations.sh --tier medium --run-id RUN_ID --live
```

A prepared `--run-id` skips guided setup and also works without interactive input.
An attempted campaign cannot be rerun under the same ID; prepare a new run instead.
Optional `--cases C03` and `--repeat 2` retain the runner's dependency and shared
campaign-budget semantics. Full acceptance still needs handset attestation and
its advanced fixture bindings; a missing binding blocks execution.

In Codex, the project skill accepts `$live-simulations minimal`,
`$live-simulations medium`, or `$live-simulations full`. Ask it to **run live**
when you want paid execution; otherwise it previews. Newly added skills may need
a fresh session to appear. The executable commands above are available immediately.

## First setup

1. Copy `live_simulations/config.example.json` into an ignored private location,
   such as `scratch/live-simulations.local.json`. Replace synthetic receiver
   placeholders with designated test contacts. List **all** receiving customer,
   staff, sender/admin inboxes and phone numbers in the allowlists. Use dedicated
   calendars and inboxes. Add your production agent IDs to `protected_agent_ids`.
2. Supply environment variables named by `secrets`, `app_environment`, and
   `database_admin_env`. The runner never loads the workspace `.env`. The database
   binding must point directly to loopback PostgreSQL with CREATEDB permission;
   its database name is connection configuration, never a reset target. Use
   unique encryption and cron secrets for this test installation.
3. Set `agent_id` to the intended ElevenLabs reference agent, including the
   standard agent already used by the app. Its display name is unchanged. The
   runner reads shared tool definitions, verifies materialized definitions agree,
   and copies tools inline into a new campaign agent. An empty start-only workflow
   is accepted; nontrivial workflows remain blocked pending a dedicated adapter. It creates a campaign-owned clone with inline tool URLs/headers pointing at
   the gateway and an explicit isolated post-call webhook. No reference agent
   or shared tool is patched. System
   transfer/dialing tools are rejected; `end_call` is allowed.
4. Enter a **verified monthly credit allowance**, remaining credits, current reset
   timestamp and conservative per-case upper estimates. Set
   `verified_credit_units: true` only after confirming the account's allowance and
   simulation credits use the same units. The subscription API still labels
   allowance fields as characters; do not substitute call minutes or a guessed
   TTS rate. Unknown quota/estimates block live runs. Estimates must include agent,
   simulated-user and evaluation costs. Explicitly authorize any calibration as
   a small selected campaign within its own verified budget; the runner never
   starts an unpriced calibration automatically.

Preview without any network traffic:

```sh
.venv/bin/python -m live_simulations plan \
  --config scratch/live-simulations.local.json --tier minimal
```

Prepare local-only resources and note the printed run ID:

```sh
.venv/bin/python -m live_simulations prepare \
  --config scratch/live-simulations.local.json
```

The fresh source snapshot includes current application source changes, a synthetic
knowledge file, separate configuration and a unique `voice_live_<id>_test` database.
It excludes workspace configuration, `.env`, existing databases and Chroma stores.
It does not replace the developer's database or app files. Prepare seeds only local
fixtures; it does not create bookings or send messages.

Start the isolated app for account setup:

```sh
.venv/bin/python -m live_simulations serve \
  --config scratch/live-simulations.local.json --run-id RUN_ID --live
```

`serve --live` enables normal application workers, including any pending effects
in this owned runtime. Open the printed **loopback portal**, connect both test
technician Google accounts, configure the test Gmail sender and enable email.
Upload the generated `app/kb_documents/simulation-services.txt` through the portal
to index it using the app's normal knowledge workflow. Any indexing/model expense
is separate from the ElevenLabs campaign budget. Configure sender credentials via
the isolated portal or explicit application environment bindings.

Point your tunnel at **gateway port 8010**, never the portal/app port 8011. The
gateway rejects portal/admin routes and requires a generated token on voice tool
requests. Twilio/ElevenLabs callback bodies and signature headers pass unchanged
to the real app for verification. Configure Twilio's WhatsApp status callback as
`https://YOUR-TUNNEL/sms/status` and inbound messages as `/sms/inbound`. Configure
the dedicated agent's post-call webhook as `/api/v1/telephony/webhook`, with its
correct webhook secret. Google OAuth can use the isolated loopback portal's
registered redirect URI; do not expose administrative OAuth routes through ingress.

Enroll each test recipient in the current WhatsApp sandbox and open its permitted
messaging window. Set `whatsapp_ready` after verifying enrollment/window. That
flag is a readiness declaration, not delivery evidence. Check the actual handset
during setup. The receiving Gmail token needs access to read the designated
`email_receiver` staff/admin inbox; it must not be a token used to inspect the
sender's Sent folder.

Stop `serve` before running a campaign; `run` owns its own app/gateway processes.
If the tested application source changes, prepare a new snapshot/run ID. Changing
only runtime account connections does not change the source fingerprint.

## Run and inspect

```sh
.venv/bin/python -m live_simulations run \
  --config scratch/live-simulations.local.json --run-id RUN_ID --tier minimal --live
.venv/bin/python -m live_simulations report \
  --config scratch/live-simulations.local.json --run-id RUN_ID
```

Preflight verifies the dedicated agent, tunnel ownership, recipients, Google
access, receiving inbox identity, billing reset and unit mapping before creating
paid tests. Billing-period identity and remaining allowance are checked again
before each paid conversation. Cases run sequentially. Independent cases get fresh local business
fixtures; C01–C03 and C04–C06 preserve their lifecycle chain. Fixtures may create
test bookings and notifications to arrange returning-customer cases; those effects
are separated from conversation evidence and can incur non-ElevenLabs charges.

Every case includes a caller persona, expected/forbidden tools, exact state checks,
required evidence and cleanup rules in `live_simulations/scenarios.json`. The
caller is told its objective and details, never tool names. The runner checks
PostgreSQL, reservations/segments, portal reloads, native Google event times,
Twilio message status **and** signed delivery callbacks, and receiving-inbox email
content. Outbox `DELIVERED` and agent success statements are insufficient.

Provider failure scenarios use explicit `case_bindings`. C22, C33, C35, C37–C45,
C48 and C50 require `ready: true` plus additional state assertions before full
execution. They involve actual account arrangements, another customer's fixture,
provider failure/recovery, real staff replies or native-history capabilities; the
runner cannot manufacture those facts. Bindings provide `before`/`after` actions
and additive `checks`. Supported action kinds are:

- `sql`: parameterized statements in the exact owned database.
- `http`: requests to an explicit local `/api/v1/` path.
- `restart`: restart the owned normal app and gateway.
- `wait_sql`: wait up to a bounded number of seconds for a real state transition.

State checks use `kind: "sql"`, `query`, `params`, `expect` and optional `op`
(`eq`, `ne`, `gt`, `ge`, `contains`) through a read-only database session. Fixture
variables use `{{name}}`. Extra checks supplement the immutable built-in checks;
they must establish the scenario's named behavior, not constant success. Set
`expect_notification_failure` only for rejection cases; optionally match the
actual `expected_error_code`. Provide exact `email_fragments` and
`whatsapp_fragments` when a case needs more specific message-content assertions.

For example, a genuine staff-confirmation case can use an `after` action that
waits for `confirmation_status='confirmed'` after the designated technician replies
on their phone, plus a matching state check. An injected local HTTP reply is
synthetic and cannot establish a genuine incoming provider message.

C23 injects an explicitly labeled failed availability tool response. C36 forwards
the real booking operation, records its result, then loses its first response.
These prove conversation recovery under controlled conditions; they do not prove
a native Google outage or telephony packet loss. C30 may reveal that the app's
visit-revision domain behavior lacks an exposed voice tool. Unsupported product
behavior remains a normal finding for a separate application change.

Full acceptance also needs an operator handset spot-check of a message recorded
in that run:

```sh
.venv/bin/python -m live_simulations confirm-handset \
  --config scratch/live-simulations.local.json --run-id RUN_ID --message-sid SM...
```

An unsettled or ambiguous paid POST is never retried automatically. Usage is
recorded before/after submission in `usage-ledger.json`; further paid work is
blocked until the existing invocation is reconciled:

```sh
.venv/bin/python -m live_simulations reconcile \
  --config scratch/live-simulations.local.json --run-id RUN_ID
```

Admission controls cannot guarantee an exact provider-side cutoff for work
already running or delayed billing. Pending cancellation does not imply that
active execution stopped. Reports retain all failures and actual sample counts;
one passing sample is not a statistical reliability claim.

## Cleanup and retention

```sh
.venv/bin/python -m live_simulations cleanup \
  --config scratch/live-simulations.local.json --run-id RUN_ID --live
```

Only provider test IDs and Google event IDs in the run manifest are deleted.
Pending invocations must settle before destructive cleanup. Database deletion
requires both the exact unique name and a matching PostgreSQL ownership comment.
Cleanup is retryable and retains evidence; messages cannot be unsent. Never replay
the production outbox or manually truncate another database.

Manifests, raw callback/tool traces and app logs live in a private runtime directory;
share only the redacted `report.json`, `report.md` and case evidence files. Retain
evidence for 30 days, then delete the completed-cleanup run folder locally. Retain
the usage ledger until its unsettled entries are reconciled. No automatic folder
purge discards evidence from a failed campaign.

## Offline validation and real-phone gate

```sh
./run_tests.sh --file tests/live_simulations
./run_tests.sh --e2e -k live_simulation
```

These tests use captured providers. They do not establish live account readiness
or delivery. The live runner is never collected or launched by pytest.

Before release, separately authorize one real-phone call with a designated caller,
test agent, isolated backend, turn/time cap and separately agreed budget. Verify
recording disclosure, actual audio, interruptions, caller ID/context, booking
read-back, handset/email receipt, native call history and a genuine signed
post-call webhook. API simulations alone cannot satisfy this gate. If simulations
do not produce native history/webhooks, mark C50 unsupported for the simulation
layer and leave that acceptance requirement pending this phone gate.

API references: [create test](https://elevenlabs.io/docs/api-reference/tests/create),
[run tests](https://elevenlabs.io/docs/api-reference/tests/run-tests),
[invocation results](https://elevenlabs.io/docs/api-reference/tests/test-invocations/get),
[billing](https://elevenlabs.io/docs/api-reference/tests/test-invocations/list).

## Callback and resource isolation

Set `post_call_webhook_id` to an enabled HMAC workspace webhook whose URL is
exactly `tunnel_url` plus `/api/v1/telephony/webhook`. Set the corresponding
secret through `SIM_ELEVENLABS_WEBHOOK_SECRET`. The runner resolves the webhook
ID, preserves reference-agent privacy/evaluation settings, overrides post-call
routing, and reads back the newly created agent before paid execution. A configured
workspace or reference-agent initiation webhook blocks execution until an isolated
workspace is used; inherited initiation destinations are not assumed safe.

Set `email_receiver` to the designated staff/admin inbox that receives the
application's operational emails. It can differ from the synthetic customer's
email. The receiving OAuth token must belong to that allowlisted inbox.

Keep the artifact root and its `id-blocks.json` across campaigns. Reservation IDs
use persistent allocated ranges so deterministic Google event IDs do not collide
with earlier deleted events. Fixture resets preserve these sequences. Native
Google mutations are observed in the isolated process, including admin events
that the application does not persist; unidentified or unfinished effects block
cleanup/reset and retain evidence for review.

## Standard API key allowance permission

The existing standard API key may read an agent while lacking `user_read` for
`GET /v1/user/subscription`. Open https://elevenlabs.io/app/settings/api-keys,
edit that key and set **User → Read**, retaining its other permissions. Save, then
retry the allowance read. Changing an existing key's permissions does not require
putting its value into this configuration. Bind `secrets.elevenlabs_key` to the
exported `ELEVENLABS_API_KEY` name. Never paste credentials into reports.

Official references: https://github.com/elevenlabs/skills/blob/main/setup-api-key/SKILL.md
and https://elevenlabs.io/docs/api-reference/tools/get . Standard agent credentials
do not replace test recipient, tunnel/webhook, isolated database or verified-budget
setup. The application database configured in the current environment can be remote;
never use it as the disposable test database or reset target.

## Returning caller and one-case cost calibration

### Explicit identity and newly approved follow-up

If normalized caller records have several names, an explicit
`existing_customer_identity: {"id": 123, "name": "Existing Test Customer"}`
may select the intended existing profile. The harness freshly calls native
`verify_caller_identity` with `read_only: true`; both ID and name must match and
the name must occur in the scoped baseline. Every original row is still retained
and compared. No binding preserves the default ambiguity block.

A new user-approved follow-up may include `campaign_authorization.continuation_of`
with the retained ancestor run ID and its own new authorization ID. This does not
replay or rewrite the original run. Matching target/ceiling, settled ledger charges,
manifest totals, final state and pending-resource checks must agree. Prior charges
count against the same aggregate ceiling and reserve; another paid child cannot
fork the same history. Reports distinguish prior, current and aggregate spend.
Keep measured case-estimate provenance in the private config. Unknown usage blocks
further paid work. Unused credits alone are not a new approval.

When explicitly authorized to keep a designated existing caller, set
`preserve_existing_bookings: true`. The runner snapshots its original bookings,
provides their context and verifies their preservation before paid submission and
after the case. Existing appointments are never reset or cancelled by setup or cleanup.
For a nonempty preserved baseline, every row must carry the same exact nonblank
customer name. That existing name is used in the simulated persona and dynamic
context without a synthetic run suffix. Missing or conflicting names block
readiness and execution before provider setup; resolve the designated caller's
identity before another campaign. New callers retain synthetic run names. The
complete baseline row comparison still detects profile or booking changes.
This is an observation guard, not a provider-side write fence; a misbehaving tool
can still cause a failing case. Review all retained evidence before another run.

For an explicitly authorized exploratory cost sample, use a separate private config
with `calibration: {"credit_ceiling": 1500, "case_upper_estimate": 1008,
"source_run_id": "PRIOR_SAMPLE_RUN_ID"}`. The example estimate scales an observed
126-credit two-turn sample to eight turns with a 2x margin. Real tool/context costs
can differ, and provider billing cannot enforce an exact cutoff mid-invocation.
The absolute calibration ceiling uses billed test credits and leaves subscription
unit equivalence unverified; ordinary tier budgets are unchanged. The 20 percent
reserve, billing period, current headroom, durable ledger and no-retry rules apply.

Run preview, then --check, then --live using the same command and config:

```sh
./run_live_simulations.sh --target deployed --tier minimal --cases C01 \
  --config scratch/live-simulations.calibration.json
```

Calibration requires exactly C01 or C04, one repetition and minimal tier. It caps
the copied agent output at 256 tokens and case length at eight turns. This is a
single-case calibration smoke result, never a completed minimal tier or full
acceptance. A successful C01 can leave a real new appointment; cancellation and
cleanup are separate explicit operations.

### Verify the actual deployed reference

The selected `agent_id` must equal the active non-secret agent identity reported
by the deployed portal. Readiness checks `/api/v1/portal/secrets` and consumes only
`elevenlabs_agent.display_value`. A missing, unreadable or mismatched identity blocks
provider mutations and paid work. A locally exported agent ID can differ from the
deployment's configured agent; do not assume it is the same. No saved reference
agent or portal settings are edited by this check. Reports record the reference ID.

The runner creates and verifies an owned copy, then runs deployed tests against
its persisted configuration without a redundant `agent_config_override`. This
keeps the copy's registered `tool_ids` intact instead of overriding them with an
empty list and deprecated inline definitions. Original failed samples remain
evidence about their selected reference, not about a different deployed agent.

Deployed pricing evaluation uses facts retrieved from the deployed catalog/knowledge
base and requires the agent to quote those returned prices and durations before
booking. Fixed prices from the isolated synthetic catalog are not imposed on a
different deployment. Every other success criterion is retained.

## Approved targeted recovery

Deployed minimal conversations allow twelve caller turns, including ordinary
clarification, catalog quotation, acceptance and native mutation. Isolated recipes
retain their separately defined turn limits. A truncated conversation remains a
failure.

When targeted paid retests have been explicitly authorized, a fresh recovery
configuration may add `campaign_authorization.recovery_cases`, for example
`["C01", "C02", "C03"]`, alongside `continuation_of`. The runner expands lifecycle
prerequisites and requires every selected case to have failed or been blocked in
the immediate settled ancestor. Already-passed cases cannot be resubmitted.
Ancestry, all prior charges, quota, reserve, authorization reuse and fork checks
remain enforced. Do not change old manifests or reuse consumed authorization IDs.
A recovery subset is never reported as a complete tier; retain the original
failure and combine case outcomes only with explicit provenance.

An authorized recovery may set `campaign_authorization.resume_request_id` for a
request provably created by the immediate ancestor. Recorded latest evidence and
a fresh native row must agree; the runner checks the raw designated phone and
compares redacted saved fields. Only that owned row is removed from preservation
and seeded into the continuing lifecycle. Already-passed prerequisites can then
be omitted, without replay. For an already-applied failed reschedule, choose a
different target time so another real change is verified. Missing ownership,
changed state, original business records or a cancelled seed block admission.
