# Preserve admin settings during Gmail token refresh

Route: bug fix, restoring the existing successful-save/reload contract.

A system Gmail token refresh reads configuration before waiting for Google.
Previously it saved that entire snapshot after the response. If an administrator
saved a different notification email while the request was in flight, the refresh
silently restored the previous email even though the admin save had succeeded.

The refresh now updates only its encrypted access token and expiry through the
shared configuration owner. A reentrant lock serializes the merge with portal
configuration reads and writes within the process; the provider request remains
outside the lock so administrators can save while it is in flight.

## Acceptance and tests

AC1 in `test-coverage.yaml` covers a successful email save during both successful
and rejected token responses, fresh JSON-file and HTTP reads, and a real browser
save followed by a complete page reload while a background refresh is pending.
The refresh token, routine-copy preference, and unrelated business settings are
preserved. The service test checks that only the two owned token fields are
submitted to the configuration updater. Fixtures use synthetic credentials,
per-test temporary configuration, deterministic interleaving, and captured Google
responses; no live email is sent.

The permanent API regression first failed for the intended reason: after a 200
save of the new email, the successful refresh restored the old address. The
rejected-refresh case passed. Focused and complete verification results are
recorded in the coverage matrix and the exact-candidate publication receipt.

## Scope and remaining work

This change fixes an in-process lost update. Configuration still uses the
existing JSON file format. Durable storage across hosting restarts/spin-down
remains unimplemented and requires separate work. The original production
incident was not correlated to a system Gmail refresh; the local regression
establishes this specific defect independently.

Google request semantics, notification routing, credentials, and delivery policy
are unchanged. No database migration or separately executed live-provider test
is required for this bounded fix. Publication does not authorize merge or deploy.

## Verification fixture correction

The independent branch's first full offline run exposed an existing real-clock
fixture failure in the duplicate-booking-notification test: its fixed appointment
was already in the past, so the scheduler correctly queued no future attempts.
The same three-line correction already present in the parallel change freezes
scheduling and worker clocks before that appointment. All dispatch counts,
persisted reminder statuses, and duplicate-prevention assertions remain intact.
No notification business rule is changed by this fixture correction.
