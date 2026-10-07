import datetime as dt
from unittest.mock import patch, MagicMock
import pytest
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import (
    create_service_request,
    book_appointment,
    get_staff_agent_by_phone,
    escalate_service_request,
)
from serviceBot.services.sms_classifier import process_inbound_sms


@pytest.fixture(autouse=True)
def setup_agent_and_appointment():
    """Ensure a staff agent and service request exist for tests."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Ensure staff agent with known phone exists
            cursor.execute("SELECT id FROM staff_agents WHERE phone_number = '+19195551234';")
            agent = cursor.fetchone()
            if not agent:
                cursor.execute(
                    """
                    INSERT INTO staff_agents (name, role, email, phone_number)
                    VALUES ('Alex Rivera', 'lead_technician', 'alex.rivera@example.com', '+19195551234')
                    RETURNING id;
                    """
                )
                agent = cursor.fetchone()
            agent_id = agent["id"]

            # 2. Ensure customer exists
            cursor.execute(
                """
                INSERT INTO customers (name, phone)
                VALUES ('Marcus Vance', '+19195557788')
                ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """
            )
            customer = cursor.fetchone()
            customer_id = customer["id"]

            # 3. Ensure vehicle exists
            cursor.execute(
                """
                INSERT INTO vehicles (customer_id, make, model, year)
                VALUES (%s, 'Subaru', 'Outback', 2021)
                RETURNING id;
                """,
                (customer_id,)
            )
            vehicle = cursor.fetchone()
            vehicle_id = vehicle["id"]

            conn.commit()

    yield {
        "agent_id": agent_id,
        "agent_phone": "+19195551234",
        "customer_id": customer_id,
        "customer_phone": "+19195557788",
        "vehicle_id": vehicle_id,
    }


def test_agent_lookup_by_phone(setup_agent_and_appointment):
    agent = get_staff_agent_by_phone("+19195551234")
    assert agent is not None
    assert agent["phone_number"] == "+19195551234"
    assert "Alex" in agent["name"]


def test_agent_confirm_action(setup_agent_and_appointment):
    fixture = setup_agent_and_appointment
    agent_id = fixture["agent_id"]
    agent_phone = fixture["agent_phone"]

    # Create service request and book appointment assigned to this agent
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status
                )
                VALUES (%s, %s, 'Brake Inspection', 'Squeaking brakes',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_sms:
        mock_sms.return_value = {"status": "DELIVERED", "sid": "SM_MOCK_CONFIRM"}
        res = process_inbound_sms(
            from_phone=agent_phone,
            body="CONFIRM",
            twilio_message_sid="SM_INBOUND_001"
        )

    assert res["status"] == "processed"
    assert res["category"] == "agent_confirm"
    assert "confirmed" in res["reply"].lower()

    # Verify database state
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT confirmation_status, confirmed_at FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row["confirmation_status"] == "confirmed"
            assert row["confirmed_at"] is not None


def test_agent_decline_action_triggers_escalation(setup_agent_and_appointment):
    fixture = setup_agent_and_appointment
    agent_id = fixture["agent_id"]
    agent_phone = fixture["agent_phone"]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status
                )
                VALUES (%s, %s, 'Oil Change', 'Synthetic oil',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_sms, \
         patch("serviceBot.services.sms_reminders.dispatch_supervisor_escalation_alert") as mock_sup_alert:
        mock_sms.return_value = {"status": "DELIVERED", "sid": "SM_MOCK_DECLINE"}
        res = process_inbound_sms(
            from_phone=agent_phone,
            body="DECLINE",
            twilio_message_sid="SM_INBOUND_002"
        )

    assert res["status"] == "processed"
    assert res["category"] == "agent_decline"
    assert "declined" in res["reply"].lower()

    # Verify database state
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT confirmation_status, escalation_status, escalation_reason FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row["confirmation_status"] == "declined"
            assert row["escalation_status"] == "escalated"
            assert row["escalation_reason"] == "AGENT_DECLINED"

    mock_sup_alert.assert_called_once()


def test_late_confirm_accepted_prior_to_reassignment(setup_agent_and_appointment):
    fixture = setup_agent_and_appointment
    agent_id = fixture["agent_id"]
    agent_phone = fixture["agent_phone"]

    # Appointment timed out and escalated, but NOT yet reassigned to someone else
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status, escalation_reason
                )
                VALUES (%s, %s, 'Tire Rotation', 'Rotate all 4 tires',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'escalated', 'TIMEOUT_NO_RESPONSE')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_sms:
        mock_sms.return_value = {"status": "DELIVERED", "sid": "SM_MOCK_LATE"}
        res = process_inbound_sms(
            from_phone=agent_phone,
            body="C",
            twilio_message_sid="SM_INBOUND_003"
        )

    assert res["status"] == "processed"
    assert res["category"] == "agent_confirm_late"
    assert "late confirmation accepted" in res["reply"].lower()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT confirmation_status, escalation_status, confirmed_at FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row["confirmation_status"] == "confirmed"
            assert row["escalation_status"] == "resolved"
            assert row["confirmed_at"] is not None


def test_late_confirm_superseded_if_already_reassigned(setup_agent_and_appointment):
    fixture = setup_agent_and_appointment
    original_agent_phone = fixture["agent_phone"]

    # Create another agent who was reassigned
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents WHERE phone_number = '+19195559999';")
            t_row = cursor.fetchone()
            if not t_row:
                cursor.execute(
                    """
                    INSERT INTO staff_agents (name, role, email, phone_number)
                    VALUES ('Taylor Smith', 'technician', 'taylor.smith@example.com', '+19195559999')
                    RETURNING id;
                    """
                )
                t_row = cursor.fetchone()
            new_agent_id = t_row["id"]

            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status, escalation_reason
                )
                VALUES (%s, %s, 'Battery Replacement', 'Dead battery',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'reassigned', 'TIMEOUT_NO_RESPONSE')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], new_agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_sms:
        mock_sms.return_value = {"status": "DELIVERED", "sid": "SM_MOCK_SUPERSEDED"}
        res = process_inbound_sms(
            from_phone=original_agent_phone,
            body="CONFIRM",
            twilio_message_sid="SM_INBOUND_004"
        )

    # The appointment is assigned to Taylor, so Alex's late confirm is superseded
    assert res["status"] == "processed"
    assert res["category"] == "agent_confirm_superseded"
    assert "reassigned" in res["reply"].lower()

    # The appointment should remain reassigned to Taylor Smith
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT staff_agent_id, escalation_status FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row["staff_agent_id"] == new_agent_id
            assert row["escalation_status"] == "reassigned"


def test_booking_notification_includes_confirm_or_decline_instruction(setup_agent_and_appointment):
    """Verify that a new booking event sends the agent an alert with explicit confirm/decline instructions."""
    fixture = setup_agent_and_appointment
    agent_id = fixture["agent_id"]
    agent_phone = fixture["agent_phone"]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status
                )
                VALUES (%s, %s, 'Brake Inspection', 'Squeaking brakes',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    from serviceBot.services.sms_router import SMSNotificationRouter
    router = SMSNotificationRouter()

    with patch.object(router, "_dispatch_to") as mock_dispatch:
        mock_dispatch.return_value = [{"recipient": "agent", "channel": "WHATSAPP", "success": True}]
        result = router.process_event(
            event_type="BOOKING",
            appointment_id=sr_id,
            agent_phone=agent_phone,
            booking_time="2026-10-15 10:00:00",
            details={"service_type": "Brake Service", "customer_name": "Marcus Vance"}
        )

        assert mock_dispatch.called
        agent_call = next(c for c in mock_dispatch.call_args_list if c.kwargs.get("recipient_type") == "agent")
        body_sent = agent_call.kwargs.get("body", "")
        assert "Reply CONFIRM or C to accept, or DECLINE if unavailable" in body_sent


def test_whatsapp_inbound_confirm_receipt_sent_via_whatsapp(setup_agent_and_appointment):
    """Verify that when an agent responds with 'C' via WhatsApp (From: whatsapp:+...), the confirmation receipt is sent via WhatsApp."""
    fixture = setup_agent_and_appointment
    agent_id = fixture["agent_id"]
    agent_phone = fixture["agent_phone"]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status
                )
                VALUES (%s, %s, 'Brake Inspection', 'Squeaking brakes',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_whatsapp") as mock_wa, \
         patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_sms:
        mock_wa.return_value = {"success": True, "status": "SENT", "channel": "WHATSAPP"}
        
        inbound_whatsapp_sender = f"whatsapp:{agent_phone}"
        res = process_inbound_sms(
            from_phone=inbound_whatsapp_sender,
            body="C",
            twilio_message_sid="SM_WA_CONFIRM_TEST"
        )

        assert res["status"] == "processed"
        assert res["category"] == "agent_confirm"
        assert "confirmed" in res["reply"].lower()

        # Receipt must be dispatched via WhatsApp, not plain SMS
        assert mock_wa.called
        assert not mock_sms.called
        call_kwargs = mock_wa.call_args.kwargs
        assert call_kwargs["to"] == inbound_whatsapp_sender
        assert f"Appointment #{sr_id} confirmed" in call_kwargs["body"]


def test_agent_confirm_matches_shared_phone_across_multiple_agents(setup_agent_and_appointment):
    """Verify that if multiple staff agents share a phone number, confirmation matches the assigned agent's appointment."""
    fixture = setup_agent_and_appointment
    agent_phone = fixture["agent_phone"]

    # Create a second agent sharing the exact same phone number
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO staff_agents (name, email, phone_number, role)
                VALUES ('Second Agent Shared Phone', 'shared_agent@example.com', %s, 'Service Advisor')
                RETURNING id;
                """,
                (agent_phone,)
            )
            second_agent_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status
                )
                VALUES (%s, %s, 'Tire Rotation', 'Rotate tires',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], second_agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_whatsapp") as mock_wa:
        mock_wa.return_value = {"success": True, "status": "SENT", "channel": "WHATSAPP"}
        res = process_inbound_sms(
            from_phone=f"whatsapp:{agent_phone}",
            body="C",
            twilio_message_sid="SM_SHARED_PHONE_TEST"
        )

        assert res["status"] == "processed"
        assert res["category"] == "agent_confirm"
        assert res["appointment_id"] == sr_id

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT confirmation_status FROM service_requests WHERE id = %s;", (sr_id,))
            assert cursor.fetchone()["confirmation_status"] == "confirmed"


def test_agent_decline_via_whatsapp_triggers_supervisor_escalation(setup_agent_and_appointment):
    """Verify that an advisor declining via WhatsApp updates DB and triggers supervisor escalation."""
    fixture = setup_agent_and_appointment
    agent_id = fixture["agent_id"]
    agent_phone = fixture["agent_phone"]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, staff_agent_id, confirmation_status, escalation_status
                )
                VALUES (%s, %s, 'Transmission Inspection', 'Slipping gears',
                        'pending', 'appointment', %s, 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (fixture["customer_id"], fixture["vehicle_id"], agent_id)
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_whatsapp") as mock_wa, \
         patch("serviceBot.services.sms_reminders.dispatch_supervisor_escalation_alert") as mock_sup_alert:
        mock_wa.return_value = {"success": True, "status": "SENT", "channel": "WHATSAPP"}
        mock_sup_alert.return_value = {"success": True, "dispatches": [{"channel": "SMS", "status": "DELIVERED"}]}

        inbound_whatsapp_sender = f"whatsapp:{agent_phone}"
        res = process_inbound_sms(
            from_phone=inbound_whatsapp_sender,
            body="DECLINE",
            twilio_message_sid="SM_WA_DECLINE_TEST"
        )

        assert res["status"] == "processed"
        assert res["category"] == "agent_decline"
        assert "declined" in res["reply"].lower()

        # Decline acknowledgement sent back to advisor on WhatsApp
        assert mock_wa.called
        assert mock_wa.call_args.kwargs["to"] == inbound_whatsapp_sender

        # Supervisor alert was triggered
        mock_sup_alert.assert_called_once()
        call_kwargs = mock_sup_alert.call_args
        assert call_kwargs.args[0] == sr_id or call_kwargs.kwargs.get("service_request_id") == sr_id

    # Verify database state
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT confirmation_status, escalation_status, escalation_reason FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row["confirmation_status"] == "declined"
            assert row["escalation_status"] == "escalated"
            assert row["escalation_reason"] == "AGENT_DECLINED"

