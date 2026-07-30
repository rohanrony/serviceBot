import pytest
import logging
from serviceBot.logger import get_logger, log_execution, mask_pii_data, set_request_id, get_request_id
from serviceBot.services.encryption import encrypt_key, decrypt_key
from serviceBot.services.twilio_sms import TwilioSMSClient

def test_pii_masking():
    raw_phone = "+15551234567"
    masked = mask_pii_data(raw_phone)
    assert "***" in masked
    assert "1234567" not in masked

    data_dict = {"api_key": "sk-proj-12345", "user": "test_user"}
    masked_dict = mask_pii_data(data_dict)
    assert masked_dict["api_key"] == "[MASKED]"
    assert masked_dict["user"] == "test_user"

def test_log_execution_decorator():
    logger = get_logger("test_decorator")
    
    @log_execution("test_decorator", re_raise=False)
    def failing_func():
        raise RuntimeError("Decorated error test")

    res = failing_func()
    assert res is None

def test_encryption_resilience():
    # Valid encryption/decryption
    encrypted = encrypt_key("test-secret-value")
    assert len(encrypted) > 0
    decrypted = decrypt_key(encrypted)
    assert decrypted == "test-secret-value"

    # Corrupt ciphertext handled gracefully without crashing
    bad_decrypted = decrypt_key("invalid-base64-ciphertext!!!")
    assert bad_decrypted == ""

def test_twilio_sms_service_resilience(monkeypatch):
    monkeypatch.setattr("serviceBot.services.twilio_sms.get_sms_config", lambda: {"environment": "TEST"})
    monkeypatch.setattr("serviceBot.services.twilio_sms.is_phone_whitelisted", lambda phone: True)
    monkeypatch.setattr("serviceBot.services.twilio_sms.log_sms_dispatch", lambda **kwargs: 1)

    sms_client = TwilioSMSClient()
    res = sms_client.send_sms(to="+15550199999", body="Test resilient SMS", template_type="test")
    assert "status" in res
    assert res["status"] == "SENT"
    assert "log_id" in res
