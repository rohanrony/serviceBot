import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.queries import get_sms_config, update_sms_config, get_sms_whitelist, add_sms_whitelist, delete_sms_whitelist

client = TestClient(app)


def test_get_and_update_sms_config():
    # 1. GET SMS Config
    res = client.get("/api/v1/portal/sms/config")
    assert res.status_code == 200
    data = res.json()
    assert "quiet_hours_enabled" in data

    # 2. PUT SMS Config
    update_payload = {
        "support_phone_number": "+18005559999",
        "quiet_start_time": "22:00",
        "quiet_end_time": "07:00",
        "environment": "STAGING"
    }
    res_put = client.put("/api/v1/portal/sms/config", json=update_payload)
    assert res_put.status_code == 200
    updated = res_put.json()
    assert updated["support_phone_number"] == "+18005559999"
    assert updated["quiet_start_time"] == "22:00:00" or updated["quiet_start_time"] == "22:00"
    assert updated["environment"] == "STAGING"


def test_sms_matrix_rules_api():
    # 1. GET matrix rules
    res = client.get("/api/v1/portal/sms/matrix-rules")
    assert res.status_code == 200
    rules = res.json()
    assert isinstance(rules, list)
    assert len(rules) > 0

    # 2. PUT matrix rule toggle (e.g. enable admin for BOOKING)
    put_res = client.put("/api/v1/portal/sms/matrix-rules", json={
        "event_type": "BOOKING",
        "recipient_role": "admin",
        "enabled": True
    })
    assert put_res.status_code == 200
    assert put_res.json()["enabled"] is True

    # Revert back
    client.put("/api/v1/portal/sms/matrix-rules", json={
        "event_type": "BOOKING",
        "recipient_role": "admin",
        "enabled": False
    })


def test_sms_whitelist_crud_and_caller_id_verify():
    phone = "+15550192831"

    # Add Whitelist Entry
    res = client.post("/api/v1/portal/sms/whitelist", json={
        "phone_number": phone,
        "friendly_name": "Test Whitelist Agent"
    })
    assert res.status_code == 201
    entry = res.json()
    assert entry["phone_number"] == phone
    entry_id = entry["id"]

    # Verify List contains phone
    get_res = client.get("/api/v1/portal/sms/whitelist")
    assert get_res.status_code == 200
    numbers = [x["phone_number"] for x in get_res.json()]
    assert phone in numbers

    # Verify Caller ID API Endpoint
    v_res = client.post("/api/v1/portal/twilio/verify-caller-id", json={
        "phone_number": "+15550199999",
        "friendly_name": "Verified Tester"
    })
    assert v_res.status_code == 200
    assert v_res.json()["success"] is True

    # Delete Whitelist Entry
    del_res = client.delete(f"/api/v1/portal/sms/whitelist/{entry_id}")
    assert del_res.status_code == 200
