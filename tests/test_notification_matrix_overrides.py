import pytest
from fastapi.testclient import TestClient
from serviceBot.api.portal import router as portal_router
from serviceBot.db.queries import get_sms_matrix_rules, update_sms_matrix_rule
from serviceBot.services.sms_router import SMSNotificationRouter
from serviceBot.main import app

client = TestClient(app)


def test_get_and_update_matrix_rules_with_channels():
    # GET matrix rules
    res = client.get("/api/v1/portal/sms/matrix-rules")
    assert res.status_code == 200
    rules = res.json()
    assert isinstance(rules, list)

    # PUT matrix rule with channel override
    put_res = client.put("/api/v1/portal/sms/matrix-rules", json={
        "event_type": "BOOKING",
        "recipient_role": "admin",
        "channel": "EMAIL",
        "enabled": True
    })
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["event_type"] == "BOOKING"
    assert updated["recipient_role"] == "admin"
    assert updated["channel"] == "EMAIL"
    assert updated["enabled"] is True

    # Check that GET returns updated rule
    res_after = client.get("/api/v1/portal/sms/matrix-rules?channel=EMAIL")
    assert res_after.status_code == 200
    email_rules = res_after.json()
    matching = [r for r in email_rules if r["event_type"] == "BOOKING" and r["recipient_role"] == "admin"]
    assert len(matching) == 1
    assert matching[0]["enabled"] is True

    # Revert rule
    client.put("/api/v1/portal/sms/matrix-rules", json={
        "event_type": "BOOKING",
        "recipient_role": "admin",
        "channel": "EMAIL",
        "enabled": False
    })


def test_matrix_rule_dispatch_override(dummy_appointment_id):
    router = SMSNotificationRouter()

    # Enable Admin SMS/WhatsApp for BOOKING via DB rule
    update_sms_matrix_rule("BOOKING", "admin", True, channel="WHATSAPP")

    res = router.process_event(
        event_type="BOOKING",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550192831",
        agent_phone="+15550192832",
        admin_phone="+15550192834"
    )

    recipients = [d["recipient"] for d in res["dispatches"]]
    assert "customer" in recipients
    assert "agent" in recipients
    assert "admin" in recipients

    # Now override via channel_overrides in process_event call (disabling admin and customer, keeping only agent)
    res_overridden = router.process_event(
        event_type="BOOKING",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550192831",
        agent_phone="+15550192832",
        admin_phone="+15550192834",
        channel_overrides={
            "customer": False,
            "agent": True,
            "admin": False
        }
    )

    recipients_overridden = [d["recipient"] for d in res_overridden["dispatches"]]
    assert "agent" in recipients_overridden
    assert "customer" not in recipients_overridden
    assert "admin" not in recipients_overridden

    # Clean up DB rule
    update_sms_matrix_rule("BOOKING", "admin", False, channel="WHATSAPP")


def test_agent_confirm_default_no_customer_notification(dummy_appointment_id):
    router = SMSNotificationRouter()

    # Trigger AGENT_CONFIRMED event with default matrix settings
    res = router.process_event(
        event_type="AGENT_CONFIRMED",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550192831",
        agent_phone="+15550192832"
    )

    recipients = [d["recipient"] for d in res["dispatches"]]
    # Default rule: No customer notification when agent confirms
    assert "customer" not in recipients
    assert "agent" in recipients


def test_agent_confirm_customer_notification_override(dummy_appointment_id):
    router = SMSNotificationRouter()

    # Enable customer notification for AGENT_CONFIRMED via matrix rule override
    update_sms_matrix_rule("AGENT_CONFIRMED", "customer", True, channel="WHATSAPP")

    res = router.process_event(
        event_type="AGENT_CONFIRMED",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550192831",
        agent_phone="+15550192832"
    )

    recipients = [d["recipient"] for d in res["dispatches"]]
    assert "customer" in recipients
    assert "agent" in recipients

    # Revert back to default (False)
    update_sms_matrix_rule("AGENT_CONFIRMED", "customer", False, channel="WHATSAPP")
