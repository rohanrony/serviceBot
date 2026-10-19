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

## Deployed full delta preparation (FR-062)

Keep the settled minimal/medium manifests, authorization provenance and common
usage ledger. Use the deployed target with the ordered explicit C17–C50 list once;
do not replay C01–C16. The full `--check` reads deployment/provider readiness and
reports every missing native case mechanism. Preview makes no network calls.

Full live admission is currently disabled before fixture/resource creation or paid
submission. Configuration `ready` flags and an old medium ceiling cannot enable it.
The 18 implemented fixture paths have offline coverage; they have no live full-case
acceptance yet. Missing native mechanisms are listed in the full-delta
contract and tasks. Native receiving-inbox verification remains unverified under
the user's manual-receipt choice. Handset4893 is the only designated delivery phone.

Run `./run_tests.sh --verify` for the full offline/API/browser gate against a
disposable loopback `TEST_DATABASE_URL`. Omit live options. Future paid admission
also requires a reviewed full-only ceiling, current quota/units, supported native
case mechanisms, exact owned fixtures and independent read-back/cleanup evidence.

## Approved grouped visits and service removal (FR-065/066)

New appointment services assigned to one technician share one appointment,
reservation and calendar entry with an ordered canonical duration snapshot.
Callbacks retain their separate behavior. Removing one explicitly selected service
requires consent: the selected appointment keeps its start and shortens its end by
that service's snapshotted duration. Other technicians' appointments keep their
booked times. Removing the last service cancels only the selected appointment;
ordinary whole-visit cancellation remains available with whole-visit consent.

The implementation and captured-provider tests are local preparation. Native use
requires the reviewed additive migration, deployed backend/UI, one owned cancel
tool revision attached only to the primary agent, and the separately versioned
prompt. Never run the broad provider sync script to apply this proposal. C25 and
C30 have offline native-fixture contracts; neither case has been submitted live.

C31 additionally checks separate 15-minute callbacks for distinct qualified
specialists with a 15-minute gap and independent reservation/calendar effects.
It is covered offline and remains unrun live.
