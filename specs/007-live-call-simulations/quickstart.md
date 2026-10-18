# Quickstart

See ../../docs/LIVE_SIMULATIONS.md for local configuration, setup, tunnel, account
readiness, budget calibration, live opt-in, receiver proof and cleanup commands.
Offline validation: ./run_tests.sh --file tests/live_simulations
Browser evidence: ./run_tests.sh --e2e -k live_simulation
No command here automatically launches a paid simulation.

Guided entrypoint after private configuration: ./run_live_simulations.sh --tier minimal --live
Choose minimal, medium or full. Omit --live for offline preview. Use --run-id UUID
for a previously prepared runtime; new live setup otherwise pauses in a terminal.
Project agent workflow: $live-simulations minimal (add an explicit live-run request).

All layers: ./run_tests.sh --verify --live-tier minimal
Choose minimal, medium or full. Omit --live-tier for offline-only verification.
Optional --live-config PATH and --live-run-id UUID apply only to the live stage.


## FR-019/020 follow-up
For one bounded deployed calibration, prepare a private config with preserve_existing_bookings=true and calibration credit_ceiling/case_upper_estimate/source_run_id. Preview/check then run with --target deployed --tier minimal --cases C01 --live. Do not rerun an attempted or ambiguous submission. Report actual credits and baseline checks.
