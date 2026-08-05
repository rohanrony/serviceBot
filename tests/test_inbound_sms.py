import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.services.sms_classifier import classify_inbound_message, process_inbound_sms
from serviceBot.db.queries import get_customer_opt_in, update_customer_opt_in

client = TestClient(app)


def test_tcpa_regulatory_keywords_classification():
    # Opt-Out keywords (Single Token)
    assert classify_inbound_message("STOP")["category"] == "tcpa_opt_out"
    assert classify_inbound_message("unsubscribe")["category"] == "tcpa_opt_out"
    assert classify_inbound_message("QUIT")["category"] == "tcpa_opt_out"

    # CANCEL must NOT be classified as TCPA opt-out
    assert classify_inbound_message("CANCEL")["category"] == "action_cancel"

    # Multi-word string containing STOP should NOT trigger TCPA opt-out
    assert classify_inbound_message("PLEASE STOP BY AT 2PM")["category"] == "free_text"

    # Opt-In keywords
    assert classify_inbound_message("START")["category"] == "tcpa_opt_in"
    assert classify_inbound_message("UNSTOP")["category"] == "tcpa_opt_in"

    # Help keyword
    assert classify_inbound_message("HELP")["category"] == "help"


def test_appointment_action_keywords_classification():
    assert classify_inbound_message("C")["category"] == "action_confirm"
    assert classify_inbound_message("confirm")["category"] == "action_confirm"
    assert classify_inbound_message("YES")["category"] == "action_confirm"

    assert classify_inbound_message("X")["category"] == "action_cancel"
    assert classify_inbound_message("cancel")["category"] == "action_cancel"
    assert classify_inbound_message("NO")["category"] == "action_cancel"


def test_inbound_opt_out_and_opt_in_execution():
    phone = "+15550197777"
    update_customer_opt_in(phone, True)

    # Send STOP
    res_stop = process_inbound_sms(phone, "STOP")
    assert res_stop["category"] == "tcpa_opt_out"
    assert get_customer_opt_in(phone) is False

    # Send START
    res_start = process_inbound_sms(phone, "START")
    assert res_start["category"] == "tcpa_opt_in"
    assert get_customer_opt_in(phone) is True


def test_inbound_webhook_endpoint():
    res = client.post(
        "/api/v1/telephony/sms/inbound",
        data={"From": "+15550192831", "Body": "HELP", "MessageSid": "SMtest_inbound_1"}
    )
    assert res.status_code == 200
    assert "xml" in res.headers["content-type"]
    assert "<Response></Response>" in res.text


def test_inbound_sms_cancel_action():
    from tests.test_service_request_status_workflow import create_test_customer_and_request
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import get_or_create_sms_conversation

    sr_id, agent_id, cust_id, _ = create_test_customer_and_request(status="pending")
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT phone FROM customers WHERE id = %s;", (cust_id,))
            phone = cursor.fetchone()["phone"]

    # Cancel active appointment via SMS
    res = process_inbound_sms(phone, "CANCEL")
    assert res["category"] == "action_cancel"
    assert res["status"] == "processed"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status FROM service_requests WHERE id = %s;", (sr_id,))
            assert cursor.fetchone()["status"] == "cancelled"

            cursor.execute(
                "INSERT INTO service_requests (customer_id, service_type, issue_description, status) VALUES (%s, %s, %s, %s) RETURNING id;",
                (cust_id, "Brake Check", "Done test", "completed")
            )
            sr_id_2 = cursor.fetchone()["id"]

    # Explicitly link completed appointment to SMS conversation context
    get_or_create_sms_conversation(phone, context_appointment_id=sr_id_2)

    res2 = process_inbound_sms(phone, "CANCEL")
    assert res2["status"] == "error"
    assert "cannot be modified" in res2["error"] or "Invalid FSM transition" in res2["error"]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status FROM service_requests WHERE id = %s;", (sr_id_2,))
            assert cursor.fetchone()["status"] == "completed"

