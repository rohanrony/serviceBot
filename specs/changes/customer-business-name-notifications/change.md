# Customer business name in appointment notifications

## Route and scope

Small change: appointment notifications are formatted in the router and reminder worker, and the configured business name is already available. Add the name to customer, agent, previous-agent, admin, and supervisor messages sent by SMS or WhatsApp, including booking, reschedule, cancellation, status, and reminder messages. If the business name is blank or missing, keep the current message format.

## Acceptance

- Customer and internal lifecycle/reminder message bodies begin with the configured business name when one is present.
- Each notification recipient role receives the same configured business-name prefix.
- Missing/blank names do not add an empty or placeholder prefix.
- Notification routing, opt-in, delivery status, persistence, and retry behavior remain unchanged.

## Behavior-to-test mapping

See `test-coverage.yaml` (AC1). No schema or provider request changes; delivery remains an existing SMS/WhatsApp boundary.

## Validation and review

Red/Green, focused tests, complete offline verification, review, live status, and publication status are recorded in `test-coverage.yaml` before handoff.
