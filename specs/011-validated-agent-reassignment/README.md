# Validated agent reassignment and truthful booking failures

The row agent control opens the existing reassignment dialog on its first click. Availability loading, failures and empty alternatives are visible and retryable. Unknown or busy candidates cannot be selected. Both assignment endpoints use the shared booking reservation owner; validation failure preserves assignments, all reservation segments and audit history. Supervisor notes survive successful reassignment.

Failed voice availability and booking tools provide explicit unconfirmed status and customer guidance. The prompt requires a successful saved request before the caller is told an appointment is booked. Notification effects remain queued and the portal does not claim delivery.

This branch is based on the earlier escalated-assignment recovery commit `4a1f6fa`, which is a prerequisite already present in the development checkout. It supersedes the earlier custom-picker proposal on `fix/agent-picker-booking-confirmation`; merge this branch instead of combining both UI implementations.

Read-only production investigation matched the reported appointment. The booking had been saved, but its customer confirmation and reminders failed because the messaging sandbox rejected the destination. The voice transcript nevertheless claimed the confirmation had been sent. A later supervisor reassignment returned success even though the replacement technician's Google account was disconnected. These are separate failure stages; the original booking was not lost because of the later technician change.

Full-suite investigation also reproduced an expired-date calendar fixture and the C27 inactive-staff simulation fixture failure on the unchanged base. The calendar fixture is corrected in the product commit. Separate prerequisite commits include an order-independent exact-membership check for the simulation catalog and tooling to verify the complete committed candidate before publication. The simulation repair still rejects missing, extra and duplicate staff bindings.

See `test-coverage.yaml` for observable acceptance criteria. Offline verification does not establish delivery by live providers. Deployed browser and voice acceptance remain pending separate merge, deployment and bounded live-test authorization.
