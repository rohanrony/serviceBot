# Validated agent reassignment and truthful booking failures

The row agent control opens the existing reassignment dialog on its first click. Availability loading, failures and empty alternatives are visible and retryable. Unknown or busy candidates cannot be selected. Both assignment endpoints use the shared booking reservation owner; validation failure preserves assignments, all reservation segments and audit history. Supervisor notes survive successful reassignment.

Failed voice availability and booking tools provide explicit unconfirmed status and customer guidance. The prompt requires a successful saved request before the caller is told an appointment is booked. Notification effects remain queued and the portal does not claim delivery.

This branch is based on the earlier escalated-assignment recovery commit `4a1f6fa`, which is a prerequisite already present in the development checkout. It supersedes the earlier custom-picker proposal on `fix/agent-picker-booking-confirmation`; merge this branch instead of combining both UI implementations.

The original production conversation has not been identified. A missing technician calendar connection is a reproduced failure condition, not a confirmed diagnosis of that specific call. See `test-coverage.yaml` for observable acceptance criteria and remaining live verification.

Full-suite investigation also reproduced an expired-date calendar fixture and the C27 inactive-staff simulation fixture failure on the unchanged base. The calendar fixture is corrected here. The C27 adapter repair and the separate unpublished verification tooling are outside this product fix; publication remains gated until those prerequisites are resolved. No original customer conversation or live provider outcome is claimed.
