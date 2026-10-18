# CLI and configuration contract

python -m live_simulations plan --config PATH --tier minimal|medium|full [--cases C01,C02]
python -m live_simulations prepare --config PATH
python -m live_simulations serve --config PATH --run-id UUID --live
python -m live_simulations run --config PATH --run-id UUID --tier minimal --live
python -m live_simulations cleanup --config PATH --run-id UUID [--live]

plan is offline/read-only. prepare creates only owned local resources. serve starts
local processes with real provider workers, so it requires --live. run requires
--live before any provider HTTP. cleanup requires
--live to delete recorded external resources; local artifacts/evidence remain.
Config fields and validation are documented in docs/LIVE_SIMULATIONS.md. Secrets are
referenced by environment variable name, never included in committed examples.
Exit codes: 0 passed/planned, 1 failed, 2 blocked/configuration, 3 incomplete.
Only all required checks passing can yield a passing selected tier.

Workflow: ./run_live_simulations.sh --tier minimal|medium|full [--config PATH]
[--live] [--run-id UUID] [--cases C01,C02] [--repeat N]. Equivalent Python entry:
python -m live_simulations workflow <same options>. Config defaults to
scratch/live-simulations.local.json. Default is offline preview; fresh live setup
requires a terminal and pauses for account readiness; a prepared run ID skips setup.
Reports and cleanup instructions survive interrupted setup. Attempted run IDs are
never overwritten. Project skill: $live-simulations TIER (preview unless live requested).

Combined entrypoint: ./run_tests.sh --verify [--live-tier minimal|medium|full]
[--live-config PATH] [--live-run-id UUID] [pytest options]. Consume live flags before
pytest invocation, run both offline layers, skip live if either fails, otherwise
invoke the existing workflow --live. Missing/invalid live options fail with exit 2
before suites start. Live exit status survives unchanged. No live tier stays offline;
non-executing pytest modes are incompatible with a live tier.


Deployed workflow: `workflow --target deployed --tier TIER [--check | --live]`.
Default config: scratch/live-simulations.deployed.json. No local Runtime or gateway.
Omitting both flags previews offline. --check reads readiness without provider
writes; --live creates owned provider resources against native deployed tools.
Unverified budgets/recipients or unsupported fixture profiles block before paid
submission. Successful functional smoke remains incomplete acceptance (exit 3).
Deployed config also dispatches report/reconcile/cleanup without a local database;
cleanup --live removes only owned provider resources, retaining deployment data.
