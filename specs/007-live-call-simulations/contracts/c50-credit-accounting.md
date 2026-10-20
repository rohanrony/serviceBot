# C50 native conversation accounting completion

## Scope and acceptance (2026-10-19)

Complete the existing FR-062 genuine-session reader and common-ledger wiring.
This bounded change adds no pricing conversion or paid-execution authority.
Existing owner/customer/nonce/terminal-conversation checks remain prerequisites.

1. After an operator independently verifies that this account's native
   `metadata.cost` is measured in the same credits as its declared allowance,
   a compiled reader accepts only an explicit nonnegative JSON integer total on
   a terminal (`done` or `failed`) conversation. Zero is an observed zero total,
   not evidence of no minute, free-allowance or separate-provider consumption.
2. Missing/null/negative/boolean/string/float/nonfinite totals, malformed metadata
   and nonterminal conversations remain unknown. No USD, duration, subscription
   delta or charging-component arithmetic substitutes for the exact total.
3. Before any new signed URL, intent or socket, require both existing credit-unit
   verification flags, an explicitly pinned verified subscription tier, a fresh
   active monthly subscription matching that tier/allowance/reset, and enough
   fresh headroom. A rollover, changed tier or unavailable quota denies admission
   without writing an intent or ledger entry. Never increase the caller's known
   remaining budget from a newer quota observation.
4. A known genuine conversation settles the common ledger using its billing ID;
   preserve exact charge source and units, make repeated reconciliation idempotent,
   reject changed settled totals, and stop after any unknown charge. A failed
   conversation may settle its actual charge while its functional result fails.
5. Reconciliation remains bounded GET-only for the existing conversation; it
   neither refreshes admission quota nor opens a signed URL/socket. It must remain
   possible after billing rollover and must not replay uncertain work.
6. Wire the reader into normal C50 execution and reconciliation. Replace the
   source-reader-absent prerequisite with actual compiled support plus observed
   account/quota readiness. Other callback, calendar, message and campaign gates
   remain independent. No real-account verification flag is set by this change.

## Provider evidence and limits

Inspected on 2026-10-19:
- Official [conversation metadata SDK model](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/types/conversation_history_metadata_common_model.py)
  declares optional integer `cost`; `cost_fiat` is a USD total and its fiat analogue.
- Official [charging SDK model](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/types/conversation_charging_common_model.py)
  has optional integer charge fields and separate price/free-allowance fields.
  No summation or alias formula is established; do not sum them or infer equality.
- Official [subscription reference](https://elevenlabs.io/docs/api-reference/user/subscription/get)
  labels character counts/limits as characters. This alone does not verify native
  conversation credit equivalence.
- Official [Agents pricing](https://elevenlabs.io/pricing/agents?price.platform=agents_platform)
  describes minute-based plans. This implementation cannot infer a mapping from
  their minutes or USD values to the existing campaign's credit ceiling.

Accordingly, `budget.native_session_credit_units_verified: true` is a separate,
account-specific prerequisite, not established by source schemas, a numeric
ceiling, or this implementation. Pin `native_session_credit_subscription_tier`
to the independently verified account tier, in addition to `verified_credit_units`,
`monthly_credits`, `reset_unix` and the existing stage authorization. Keep both
verification flags false until an authoritative account-specific billing contract
establishes the units. If no such contract is available, live C50 stays blocked.

## Verification

Captured REST/socket tests use synthetic explicitly verified accounting contracts.
Cover exact-total parsing, zero, malformed/unknown fields, no fiat fallback,
quota/tier/reset failures before effects, terminal failed charges, persisted
ledger settlement, repeated GET-only reconciliation, changed-cost conflicts,
source-default execution/recovery, and outer Budget settlement once. Existing
browser journeys are regression coverage; no user-facing UI changes are made.
Full exact-candidate publication verification remains mandatory and depends on
publication of the other chat's verifier/CI workflow.
