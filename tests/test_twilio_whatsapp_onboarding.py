import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor, init_db
from serviceBot.db.queries import add_sms_whitelist, update_whatsapp_onboarding_status, get_sms_whitelist
from serviceBot.services.twilio_sms import TwilioSMSClient

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    try:
        init_db()
    except Exception as exc:
        print(f"Database setup skipped/warning in test fixture: {exc}")


def test_twilio_client_sandbox_credentials():
    twilio_client = TwilioSMSClient()
    info = twilio_client.get_sandbox_credentials()
    assert "sandbox_number" in info
    assert "join_code" in info
    assert "whatsapp_url" in info
    assert "qr_code_url" in info
    assert info["whatsapp_url"].startswith("https://wa.me/")


def test_twilio_client_send_whatsapp():
    add_sms_whitelist("+15550199999", friendly_name="Test User", twilio_verified=True)
    twilio_client = TwilioSMSClient()
    res = twilio_client.send_whatsapp(to="+15550199999", body="Test WhatsApp msg")
    assert res["success"] is True
    assert "sid" in res


def test_db_whatsapp_onboarding_helpers():
    record = add_sms_whitelist(
        phone_number="+15550198888",
        friendly_name="WhatsApp Test User",
        twilio_verified=True,
        whatsapp_onboarded=False,
        recipient_role="CUSTOMER"
    )
    assert record["phone_number"] == "+15550198888"
    assert record["whatsapp_onboarded"] is False
    assert record["recipient_role"] == "CUSTOMER"

    updated = update_whatsapp_onboarding_status(
        phone_number="+15550198888",
        whatsapp_onboarded=True,
        recipient_role="CUSTOMER"
    )
    assert updated["whatsapp_onboarded"] is True
    assert updated["whatsapp_onboarded_at"] is not None


def test_portal_twilio_sandbox_info_endpoint():
    response = client.get("/api/v1/portal/twilio/sandbox-info")
    assert response.status_code == 200
    data = response.json()
    assert "sandbox_number" in data
    assert "join_code" in data
    assert "whatsapp_url" in data


def test_portal_customer_onboard_endpoint():
    payload = {
        "phone_number": "+15550197777",
        "friendly_name": "Test Customer Onboard",
        "recipient_role": "CUSTOMER"
    }
    response = client.post("/api/v1/portal/twilio/customer-onboard", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["record"]["phone_number"] == "+15550197777"


def test_portal_whatsapp_test_ping_endpoint():
    add_sms_whitelist("+15550196666", friendly_name="Jane Test", twilio_verified=True)
    payload = {
        "phone_number": "+15550196666",
        "recipient_name": "Jane Test",
        "recipient_role": "CUSTOMER"
    }
    response = client.post("/api/v1/portal/twilio/whatsapp-test-ping", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["record"]["whatsapp_onboarded"] is True


def test_twilio_client_sandbox_credentials_role_support():
    twilio_client = TwilioSMSClient()
    info_admin = twilio_client.get_sandbox_credentials(role="ADMIN", phone_number="+15550191111")
    assert info_admin["role"] == "ADMIN"
    assert info_admin["recipient_phone"] == "+15550191111"
    assert "qr_code_url" in info_admin

    info_agent = twilio_client.get_sandbox_credentials(role="AGENT", phone_number="+15550192222")
    assert info_agent["role"] == "AGENT"
    assert info_agent["recipient_phone"] == "+15550192222"


def test_portal_twilio_qr_code_endpoint():
    response = client.get("/api/v1/portal/twilio/qr-code?data=https://wa.me/14155238886?text=join", follow_redirects=False)
    assert response.status_code == 307
    assert "api.qrserver.com" in response.headers["location"]

