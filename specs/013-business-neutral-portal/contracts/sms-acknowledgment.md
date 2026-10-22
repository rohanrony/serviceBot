# Contract: Inbound SMS / WhatsApp Acknowledgment

## Trigger
Inbound unrecognized or free-text message from a staff agent or customer where no specific command (e.g. TCPA opt-in/opt-out, CONFIRM, CANCEL) was recognized.

## Acknowledgment Text Resolution
1. Fetch canonical support helpline from configuration / `sms_config`:
   `support_number = config.get("support_phone_number") or sms_config.get("support_phone_number")`
2. If `support_number` is present and non-empty:
   `reply_text = f"Message received. For urgent scheduling assistance, please call {support_number.strip()}."`
3. If `support_number` is absent, None, or empty:
   `reply_text = "Message received."`

## Invariants
- Prohibit hardcoded placeholder numbers (e.g. `+18005550199`) if no helpline is configured.
- Prohibit referring to "dispatch" in automated receipt.
- Sender classification, agent confirmation actions, and outbound SMS logging are preserved.
