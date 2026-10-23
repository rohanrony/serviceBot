from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.queries import (
    get_sms_config,
    update_sms_config,
    get_or_create_sms_conversation,
    get_sms_messages
)


@pytest.fixture
def api():
    return TestClient(app)


@pytest.fixture
def db():
    from serviceBot.db.connection import dict_cursor, get_db_connection
    def execute(statement, parameters=()):
        with get_db_connection() as conn, dict_cursor(conn) as cursor:
            cursor.execute(statement, parameters)
            return [dict(row) for row in cursor.fetchall()] if cursor.description else []
    return execute


def test_cleared_helpline_does_not_send_unresolved_template(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    conv = get_or_create_sms_conversation("+15550100001")
    conv_id = conv["id"]

    update_sms_config({"auto_responder_template": "Thank you for reaching out! For urgent assistance call {support_number}."})
    assert api.post("/api/v1/portal/config", json={"support_phone_number": ""}).status_code == 200

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synthetic-review-message"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)

    result = handoff.trigger_human_handoff(conv_id, "+15550100001", "Please connect me")
    assert result["auto_responder_sent"] is True

    body = client.send_sms.call_args.kwargs["body"]
    assert "{support_number}" not in body
    assert body == "Message received."

    # Inspect persisted message
    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == body
    assert "{support_number}" not in messages[-1]["body"]


def test_failed_database_sync_does_not_resurrect_cleared_canonical_helpline(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    from serviceBot.services.sms_classifier import get_support_helpline
    from serviceBot.db import queries

    conv = get_or_create_sms_conversation("+15550100002")
    conv_id = conv["id"]

    assert api.post("/api/v1/portal/config", json={"support_phone_number": "+12025550999"}).status_code == 200

    def fail_update(data):
        raise RuntimeError("synthetic database write failure")

    monkeypatch.setattr(queries, "update_sms_config", fail_update)
    response = api.post("/api/v1/portal/config", json={"support_phone_number": ""})
    assert response.status_code == 200
    assert response.json()["saved"] is True
    assert get_support_helpline() == ""
    assert queries.get_sms_config()["support_phone_number"] == "+12025550999"

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synthetic-review-message"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: False)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)

    handoff.trigger_human_handoff(conv_id, "+15550100002", "Please connect me")
    body = client.send_sms.call_args.kwargs["body"]
    assert "+12025550999" not in body

    # Inspect persisted message
    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert "+12025550999" not in messages[-1]["body"]
    assert messages[-1]["body"] == body

    # Also verify in-hours handoff cannot resurrect cleared helpline
    conv_in_hours = get_or_create_sms_conversation("+15550100003")
    conv_in_hours_id = conv_in_hours["id"]
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    client.reset_mock()
    handoff.trigger_human_handoff(conv_in_hours_id, "+15550100003", "Please connect me during day")
    body_in = client.send_sms.call_args.kwargs["body"]
    assert "+12025550999" not in body_in
    assert body_in == "Message received."
    messages_in = get_sms_messages(conv_in_hours_id)
    assert len(messages_in) > 0
    assert "+12025550999" not in messages_in[-1]["body"]
    assert messages_in[-1]["body"] == "Message received."


def test_cleared_helpline_with_different_template_wordings(api, monkeypatch):
    from serviceBot.services import handoff_service as handoff

    assert api.post("/api/v1/portal/config", json={"support_phone_number": ""}).status_code == 200

    templates = [
        "Thank you! Our team has received your message. For urgent help, call {support_number}.",
        "Thank you for reaching out! For urgent assistance call {support_number}.",
        "We are currently busy. For direct assistance, call {support_number} right away."
    ]

    for i, tmpl in enumerate(templates):
        phone = f"+1555010001{i}"
        conv = get_or_create_sms_conversation(phone)
        conv_id = conv["id"]

        update_sms_config({"auto_responder_template": tmpl})

        client = MagicMock()
        client.send_sms.return_value = {"success": True, "sid": f"synth-msg-{i}"}
        monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
        monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
        monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

        result = handoff.trigger_human_handoff(conv_id, phone, "Help please")
        assert result["auto_responder_sent"] is True

        body = client.send_sms.call_args.kwargs["body"]
        assert body == "Message received."
        assert "{support_number}" not in body

        messages = get_sms_messages(conv_id)
        assert len(messages) > 0
        assert messages[-1]["body"] == "Message received."


def test_custom_template_without_helpline_placeholder(api, monkeypatch):
    from serviceBot.services import handoff_service as handoff

    assert api.post("/api/v1/portal/config", json={"support_phone_number": ""}).status_code == 200

    custom_tmpl = "Thanks for reaching out! A representative will review your message shortly."
    update_sms_config({"auto_responder_template": custom_tmpl})

    phone = "+15550100020"
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-msg-custom"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

    result = handoff.trigger_human_handoff(conv_id, phone, "Question about service")
    assert result["auto_responder_sent"] is True

    body = client.send_sms.call_args.kwargs["body"]
    assert body == custom_tmpl

    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == custom_tmpl


def test_configured_helpline_rendering_in_and_out_of_hours(api, monkeypatch):
    from serviceBot.services import handoff_service as handoff

    helpline = "+18005550144"
    assert api.post("/api/v1/portal/config", json={"support_phone_number": helpline}).status_code == 200

    # 1. In-hours with placeholder
    tmpl = "Hello! For immediate help, call {support_number}."
    update_sms_config({"auto_responder_template": tmpl})

    phone1 = "+15550100031"
    conv1 = get_or_create_sms_conversation(phone1)
    conv1_id = conv1["id"]

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-in-hours"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

    result = handoff.trigger_human_handoff(conv1_id, phone1, "Need assist")
    assert result["auto_responder_sent"] is True
    body = client.send_sms.call_args.kwargs["body"]
    assert body == f"Hello! For immediate help, call {helpline}."

    msgs = get_sms_messages(conv1_id)
    assert msgs[-1]["body"] == body

    # 2. Out-of-hours with configured helpline
    phone2 = "+15550100032"
    conv2 = get_or_create_sms_conversation(phone2)
    conv2_id = conv2["id"]

    client_ooh = MagicMock()
    client_ooh.send_sms.return_value = {"success": True, "sid": "synth-ooh"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client_ooh)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: False)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

    result_ooh = handoff.trigger_human_handoff(conv2_id, phone2, "Emergency help")
    assert result_ooh["auto_responder_sent"] is True
    body_ooh = client_ooh.send_sms.call_args.kwargs["body"]
    assert helpline in body_ooh
    assert "Live agent support is only available during our business hours" in body_ooh

    msgs_ooh = get_sms_messages(conv2_id)
    assert msgs_ooh[-1]["body"] == body_ooh


def test_legacy_fallback_when_canonical_setting_is_absent(monkeypatch):
    from serviceBot.services import handoff_service as handoff
    from serviceBot.api import portal
    from serviceBot.services.sms_classifier import get_support_helpline

    # Ensure config.json does NOT contain support_phone_number key
    cfg = portal.load_config()
    cfg.pop("support_phone_number", None)
    portal.save_config(cfg)

    legacy_number = "+15550198888"
    update_sms_config({
        "support_phone_number": legacy_number,
        "auto_responder_template": "Support line: {support_number}"
    })

    assert get_support_helpline() == legacy_number

    # In-hours handoff uses legacy database number
    phone = "+15550100041"
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-legacy"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

    result = handoff.trigger_human_handoff(conv_id, phone, "Need support")
    assert result["auto_responder_sent"] is True
    body = client.send_sms.call_args.kwargs["body"]
    assert body == f"Support line: {legacy_number}"

    msgs = get_sms_messages(conv_id)
    assert msgs[-1]["body"] == f"Support line: {legacy_number}"

    # Out-of-hours handoff uses legacy database number
    phone_ooh = "+15550100042"
    conv_ooh = get_or_create_sms_conversation(phone_ooh)
    conv_ooh_id = conv_ooh["id"]

    client_ooh = MagicMock()
    client_ooh.send_sms.return_value = {"success": True, "sid": "synth-legacy-ooh"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client_ooh)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: False)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

    result_ooh = handoff.trigger_human_handoff(conv_ooh_id, phone_ooh, "Need support after hours")
    assert result_ooh["auto_responder_sent"] is True
    body_ooh = client_ooh.send_sms.call_args.kwargs["body"]
    assert legacy_number in body_ooh

    msgs_ooh = get_sms_messages(conv_ooh_id)
    assert msgs_ooh[-1]["body"] == body_ooh


def test_customer_name_template_is_not_dispatched_unresolved(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    from serviceBot.db.queries import update_sms_config, update_sms_conversation_state
    assert api.post("/api/v1/portal/config", json={"support_phone_number": "+12025550121"}).status_code == 200
    update_sms_config({"auto_responder_template": "Hi {customer_name}, for urgent assistance call {support_number}."})
    update_sms_conversation_state(1, "AUTOMATED", last_auto_responder_at=None)
    db("UPDATE sms_conversations SET last_auto_responder_at = NULL WHERE id = 1;")
    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synthetic-review-message"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)
    result = handoff.trigger_human_handoff(1, "+15550100001", "Please connect me")
    assert result["auto_responder_sent"] is True
    body = client.send_sms.call_args.kwargs["body"]
    print("CUSTOMER_NAME_TEMPLATE_BODY", body)
    assert "{customer_name}" not in body
    assert body == "Message received."


def test_customer_name_and_helpline_both_available(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    phone = "+15550100051"
    db("INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name;", ("Alice Smith", phone))
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    helpline = "+12025550121"
    assert api.post("/api/v1/portal/config", json={"support_phone_number": helpline}).status_code == 200
    update_sms_config({"auto_responder_template": "Hi {customer_name}, for urgent assistance call {support_number}."})

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-both"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

    result = handoff.trigger_human_handoff(conv_id, phone, "Need help")
    assert result["auto_responder_sent"] is True

    expected = f"Hi Alice Smith, for urgent assistance call {helpline}."
    body = client.send_sms.call_args.kwargs["body"]
    assert body == expected

    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == expected


def test_customer_name_only_template(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    phone = "+15550100052"
    db("INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name;", ("Bob Jones", phone))
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    assert api.post("/api/v1/portal/config", json={"support_phone_number": ""}).status_code == 200
    update_sms_config({"auto_responder_template": "Hi {customer_name}, our team will get back to you shortly."})

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-cust-only"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda p: True)

    result = handoff.trigger_human_handoff(conv_id, phone, "Question about service")
    assert result["auto_responder_sent"] is True

    expected = "Hi Bob Jones, our team will get back to you shortly."
    body = client.send_sms.call_args.kwargs["body"]
    assert body == expected

    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == expected


def test_missing_or_unknown_customer_name_falls_back_to_neutral(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    phone = "+15550100054"
    db("INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name;", ("Unknown Customer", phone))
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    assert api.post("/api/v1/portal/config", json={"support_phone_number": "+12025550121"}).status_code == 200
    update_sms_config({"auto_responder_template": "Hello {customer_name}! Call {support_number}."})

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-unknown"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)

    result = handoff.trigger_human_handoff(conv_id, phone, "Hello")
    assert result["auto_responder_sent"] is True

    body = client.send_sms.call_args.kwargs["body"]
    assert body == "Message received."
    assert "{customer_name}" not in body

    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == "Message received."


def test_unsupported_placeholder_template_falls_back(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    phone = "+15550100055"
    db("INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name;", ("Charlie Brown", phone))
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    assert api.post("/api/v1/portal/config", json={"support_phone_number": "+12025550121"}).status_code == 200

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-unsupported"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)

    update_sms_config({"auto_responder_template": "Hi {customer_name}, your balance is {account_balance}."})
    result = handoff.trigger_human_handoff(conv_id, phone, "Check balance")
    assert result["auto_responder_sent"] is True
    body = client.send_sms.call_args.kwargs["body"]
    assert body == "Message received."
    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == "Message received."


def test_malformed_template_syntax_falls_back(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    phone = "+15550100058"
    db("INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name;", ("Lucy Van Pelt", phone))
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    assert api.post("/api/v1/portal/config", json={"support_phone_number": "+12025550121"}).status_code == 200

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-malformed"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)

    update_sms_config({"auto_responder_template": "Hi {customer_name, call {support_number"})
    result = handoff.trigger_human_handoff(conv_id, phone, "Help please")
    assert result["auto_responder_sent"] is True
    body_malformed = client.send_sms.call_args.kwargs["body"]
    assert body_malformed == "Message received."
    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == "Message received."


def test_plain_text_template_preserved(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    phone = "+15550100057"
    db("INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name;", ("Eve Online", phone))
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    assert api.post("/api/v1/portal/config", json={"support_phone_number": "+12025550121"}).status_code == 200
    plain_text = "Thanks for contacting our support desk. An agent will respond shortly."
    update_sms_config({"auto_responder_template": plain_text})

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-plain"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)

    result = handoff.trigger_human_handoff(conv_id, phone, "General inquiry")
    assert result["auto_responder_sent"] is True

    body = client.send_sms.call_args.kwargs["body"]
    assert body == plain_text

    messages = get_sms_messages(conv_id)
    assert len(messages) > 0
    assert messages[-1]["body"] == plain_text


def test_missing_helpline_when_template_requires_it_falls_back(api, db, monkeypatch):
    from serviceBot.services import handoff_service as handoff
    phone = "+15550100056"
    db("INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name;", ("Dana Scully", phone))
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    # Ensure helpline is cleared
    assert api.post("/api/v1/portal/config", json={"support_phone_number": ""}).status_code == 200
    update_sms_config({"auto_responder_template": "Hi {customer_name}, for urgent assistance call {support_number}."})

    client = MagicMock()
    client.send_sms.return_value = {"success": True, "sid": "synth-missing-helpline"}
    monkeypatch.setattr(handoff, "TwilioSMSClient", lambda: client)
    monkeypatch.setattr(handoff, "is_within_business_hours", lambda: True)
    monkeypatch.setattr(handoff, "get_customer_opt_in", lambda phone: True)

    result = handoff.trigger_human_handoff(conv_id, phone, "I need assistance")
    assert result["auto_responder_sent"] is True

    body = client.send_sms.call_args.kwargs["body"]
    assert body == "Message received."
    assert "{support_number}" not in body
    assert "{customer_name}" not in body

    messages = get_sms_messages(conv_id)
    assert messages[-1]["body"] == "Message received."

