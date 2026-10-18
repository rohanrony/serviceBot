# Live intake follow-up validation — 2026-10-18

Spec/plan/tasks T047–T049 reconciled the omitted-type exact catalog contract before
implementation. Red: 2 failures / 4 passes; Green: 6 real-database E2E cases.
Final `./run_tests.sh --verify --tb=short`: 731 unit/integration and 289 E2E
passed with zero failures/errors/skips and command exit 0.

Convergence verified canonical service identity, 45-minute receipt and durable
reservation, three capacity segments, catalog pricing, explicit-type precedence,
uncataloged precedence, free text and ambiguous-match fallback. No remaining
implementation finding in this bounded path. No new schema or public API is added.
The repair is local; the deployed run retained its original generic 60-minute
booking. Publishing and rerunning are not included in local verification.

Evidence: scratch/live-campaign-20261018/report.md, intake-catalog-red.log,
intake-catalog-green.log, final-offline.log and final-{unit,e2e}-results.xml.
Graph tools were unavailable; exact source fallback was used.
