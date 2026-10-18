"""Provider callback registration must survive both supported public-base settings."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.parametrize("setting", ["TWILIO_WEBHOOK_BASE_URL", "RENDER_EXTERNAL_URL"])
def test_twilio_dispatch_registers_trusted_delivery_callback(monkeypatch, setting):
    from serviceBot.services.twilio_sms import TwilioSMSClient

    for key in ("TESTING", "PYTEST_CURRENT_TEST", "TWILIO_WEBHOOK_BASE_URL", "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(setting, "https://voice.example.test/")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "synthetic-token")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550100999")
    sdk = MagicMock()
    sdk.messages.create.return_value.sid = "SMsynthetic"
    with patch("serviceBot.services.twilio_sms.get_sms_config", return_value={"environment": "PRODUCTION"}), \
         patch("serviceBot.services.twilio_sms.log_sms_dispatch", return_value=1), \
         patch("twilio.rest.Client", return_value=sdk):
        result = TwilioSMSClient().send_sms("+15550100001", "Original booking details")
    assert result["success"] is True
    assert sdk.messages.create.call_args.kwargs["status_callback"] == "https://voice.example.test/api/v1/telephony/sms/status"
