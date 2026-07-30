"""
test_sms_notifications.py
=========================
Unit tests for the Twilio SMS notification wiring added across:
  - outbox_worker.py  (agent_reassignment + booking_notification handlers)
  - telephony.py      (voice tools: create_service_request, book_appointment,
                       request_callback, reschedule_appointment, post-call webhook)

All Twilio network calls are mocked — these tests run safely in CI / on deployment
without an active Twilio account.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_process_event_mock():
    """Return a MagicMock that simulates SMSNotificationRouter.process_event."""
    mock = MagicMock()
    mock.return_value = {"event_type": "BOOKING", "appointment_id": 101, "dispatches": []}
    return mock


# ===========================================================================
# 1. TwilioSMSClient — unit-level mock dispatch
# ===========================================================================

class TestTwilioSMSClient:
    """TwilioSMSClient.send_sms falls back to mock mode when PYTEST_CURRENT_TEST is set."""

    def test_send_sms_returns_mock_sid_in_test_env(self, dummy_appointment_id):
        from serviceBot.services.twilio_sms import TwilioSMSClient
        sms = TwilioSMSClient()
        result = sms.send_sms(
            to="+15550001111",
            body="Test booking confirmation",
            template_type="booking",
            appointment_id=dummy_appointment_id
        )
        assert result["success"] is True
        assert result["status"] == "SENT"
        assert result["sid"].startswith("SMmock_")

    def test_send_sms_logs_dispatch_to_db(self, dummy_appointment_id):
        from serviceBot.services.twilio_sms import TwilioSMSClient
        from serviceBot.db.queries import get_sms_logs_by_appointment
        sms = TwilioSMSClient()
        sms.send_sms(
            to="+15550001112",
            body="Dispatch logging test",
            template_type="agent_booking",
            appointment_id=dummy_appointment_id
        )
        logs = get_sms_logs_by_appointment(dummy_appointment_id)
        assert any(
            log["recipient_phone"] == "+15550001112" and log["status"] == "SENT"
            for log in logs
        )

    def test_send_sms_returns_failure_on_bad_credentials(self):
        """When credentials are wrong and we're NOT in test mode, real Twilio raises."""
        import os
        from serviceBot.services.twilio_sms import TwilioSMSClient

        # Force real Twilio path by unsetting the test flag
        orig = os.environ.pop("PYTEST_CURRENT_TEST", None)
        try:
            sms = TwilioSMSClient()
            sms.account_sid = "ACbad"
            sms.auth_token = "badtoken"
            sms.from_number = "+15559999999"
            sms.messaging_service_sid = ""

            with patch("twilio.rest.Client") as mock_twilio:
                mock_twilio.return_value.messages.create.side_effect = Exception("Auth error, code: 20003")
                result = sms.send_sms(to="+15550001113", body="fail test", template_type="booking")

            assert result["success"] is False
            assert result["status"] == "FAILED"
        finally:
            if orig:
                os.environ["PYTEST_CURRENT_TEST"] = orig


# ===========================================================================
# 2. SMSNotificationRouter — routing matrix per event type
# ===========================================================================

class TestSMSNotificationRouter:

    def test_booking_dispatches_to_customer(self, dummy_appointment_id):
        from serviceBot.services.sms_router import SMSNotificationRouter
        router = SMSNotificationRouter()
        result = router.process_event(
            event_type="BOOKING",
            appointment_id=dummy_appointment_id,
            customer_phone="+15550002001",
            agent_phone="+15550002002",
            booking_time="2026-10-25 14:00:00"
        )
        recipients = [d["recipient"] for d in result["dispatches"]]
        assert "customer" in recipients

    def test_booking_dispatches_to_agent(self, dummy_appointment_id):
        from serviceBot.services.sms_router import SMSNotificationRouter
        router = SMSNotificationRouter()
        result = router.process_event(
            event_type="BOOKING",
            appointment_id=dummy_appointment_id,
            customer_phone="+15550002001",
            agent_phone="+15550002002",
            booking_time="2026-10-25 14:00:00"
        )
        recipients = [d["recipient"] for d in result["dispatches"]]
        assert "agent" in recipients

    def test_rescheduled_dispatches_to_customer(self, dummy_appointment_id):
        from serviceBot.services.sms_router import SMSNotificationRouter
        router = SMSNotificationRouter()
        result = router.process_event(
            event_type="RESCHEDULED",
            appointment_id=dummy_appointment_id,
            customer_phone="+15550002003",
            booking_time="2026-11-01 10:00:00"
        )
        recipients = [d["recipient"] for d in result["dispatches"]]
        assert "customer" in recipients

    def test_reassigned_routes_to_agent_and_previous_agent(self, dummy_appointment_id):
        from serviceBot.services.sms_router import SMSNotificationRouter
        router = SMSNotificationRouter()
        result = router.process_event(
            event_type="REASSIGNED",
            appointment_id=dummy_appointment_id,
            customer_phone="+15550002004",
            agent_phone="+15550002005",
            previous_agent_phone="+15550002006",
            booking_time="2026-10-25 14:00:00"
        )
        recipients = [d["recipient"] for d in result["dispatches"]]
        assert "agent" in recipients
        assert "previous_agent" in recipients
        # Customer is suppressed by default for REASSIGNED
        assert "customer" not in recipients

    def test_opted_out_customer_skipped(self, dummy_appointment_id):
        from serviceBot.services.sms_router import SMSNotificationRouter
        from serviceBot.db.queries import update_customer_opt_in
        phone = "+15550003000"
        update_customer_opt_in(phone, False)
        router = SMSNotificationRouter()
        result = router.process_event(
            event_type="BOOKING",
            appointment_id=dummy_appointment_id,
            customer_phone=phone,
            booking_time="2026-10-25 14:00:00"
        )
        cust = next(d for d in result["dispatches"] if d["recipient"] == "customer")
        assert cust["status"] == "SKIPPED_OPT_OUT"
        # cleanup
        update_customer_opt_in(phone, True)


# ===========================================================================
# 3. Outbox Worker — agent_reassignment SMS leg
# ===========================================================================

class TestOutboxWorkerSMSTriggers:
    """
    Verify that _dispatch_outbox_event calls SMSNotificationRouter.process_event
    with the correct arguments for agent_reassignment and booking_notification.
    """

    @patch("serviceBot.services.outbox_worker.send_admin_notification")
    @patch("serviceBot.services.outbox_worker.create_admin_calendar_event")
    @patch("serviceBot.services.outbox_worker.create_agent_calendar_event")
    @patch("serviceBot.services.outbox_worker.delete_agent_calendar_event")
    @patch("serviceBot.services.outbox_worker.send_booking_notification")
    def test_agent_reassignment_calls_sms_router(
        self,
        mock_email,
        mock_delete_cal,
        mock_create_cal,
        mock_admin_cal,
        mock_admin_email,
    ):
        from serviceBot.services.outbox_worker import _dispatch_outbox_event

        payload = {
            "old_agent_id": 1,
            "old_agent_name": "Alice",
            "new_agent_id": 2,
            "new_agent_name": "Bob",
            "new_agent_email": "bob@example.com",
            "agent_phone": "+15550010001",
            "previous_agent_phone": "+15550010002",
            "booking_time_str": "2026-10-25 14:00:00",
            "details": {
                "customer_name": "Jane Doe",
                "phone": "+15550010003",
                "vehicle": "2020 Toyota Camry",
                "service_type": "Oil Change",
                "issue": "Routine service",
                "previous_agent_name": "Alice"
            }
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as mock_sms:
            mock_sms.return_value = {"dispatches": []}
            _dispatch_outbox_event("agent_reassignment", request_id=99, payload=payload)

        mock_sms.assert_called_once()
        call_kwargs = mock_sms.call_args.kwargs
        assert call_kwargs["event_type"] == "REASSIGNED"
        assert call_kwargs["appointment_id"] == 99
        assert call_kwargs["customer_phone"] == "+15550010003"
        assert call_kwargs["agent_phone"] == "+15550010001"
        assert call_kwargs["previous_agent_phone"] == "+15550010002"

    @patch("serviceBot.services.outbox_worker.send_admin_notification")
    @patch("serviceBot.services.outbox_worker.create_admin_calendar_event")
    @patch("serviceBot.services.outbox_worker.send_booking_notification")
    def test_booking_notification_calls_sms_router(
        self,
        mock_email,
        mock_admin_cal,
        mock_admin_email,
    ):
        from serviceBot.services.outbox_worker import _dispatch_outbox_event

        payload = {
            "booking_type": "appointment",
            "agent_email": "agent@example.com",
            "agent_name": "Bob",
            "agent_phone": "+15550010011",
            "booking_time_str": "2026-10-25 14:00:00",
            "details": {
                "customer_name": "John Smith",
                "phone": "+15550010012",
                "vehicle": "2019 Honda Civic",
                "service_type": "Brake inspection",
                "issue": "Squeaking brakes"
            }
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as mock_sms:
            mock_sms.return_value = {"dispatches": []}
            _dispatch_outbox_event("booking_notification", request_id=88, payload=payload)

        mock_sms.assert_called_once()
        call_kwargs = mock_sms.call_args.kwargs
        assert call_kwargs["event_type"] == "BOOKING"
        assert call_kwargs["appointment_id"] == 88
        assert call_kwargs["customer_phone"] == "+15550010012"
        assert call_kwargs["agent_phone"] == "+15550010011"

    @patch("serviceBot.services.outbox_worker.send_admin_notification")
    @patch("serviceBot.services.outbox_worker.create_admin_calendar_event")
    @patch("serviceBot.services.outbox_worker.send_booking_notification")
    def test_booking_notification_reschedule_maps_to_rescheduled_event(
        self,
        mock_email,
        mock_admin_cal,
        mock_admin_email,
    ):
        from serviceBot.services.outbox_worker import _dispatch_outbox_event

        payload = {
            "booking_type": "reschedule",
            "agent_email": None,
            "agent_name": None,
            "agent_phone": None,
            "booking_time_str": "2026-11-01 10:00:00",
            "details": {
                "customer_name": "Jane Smith",
                "phone": "+15550010015",
                "vehicle": "2021 Ford Explorer",
                "service_type": "Tire rotation",
                "issue": ""
            }
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as mock_sms:
            mock_sms.return_value = {"dispatches": []}
            _dispatch_outbox_event("booking_notification", request_id=77, payload=payload)

        call_kwargs = mock_sms.call_args.kwargs
        assert call_kwargs["event_type"] == "RESCHEDULED"


# ===========================================================================
# 4. Voice Tools API — SMS fires on booking/callback/reschedule tool calls
# ===========================================================================

class TestVoiceToolsSMSTriggers:
    """
    Integration tests for /api/v1/voice/tools.
    We mock DB calls and SMSNotificationRouter so tests don't need a live DB or Twilio.
    """

    @patch("serviceBot.api.telephony.get_booking_details")
    @patch("serviceBot.api.telephony.create_service_request")
    @patch("serviceBot.api.telephony.lookup_customer_by_phone")
    def test_create_service_request_appointment_triggers_sms(
        self, mock_lookup, mock_create, mock_details
    ):
        mock_lookup.return_value = {"customer_id": 42}
        mock_create.return_value = 201
        mock_details.return_value = {
            "customer_name": "Jane Doe",
            "phone": "+15550020001",
            "vehicle": "2020 Toyota Camry",
            "service_type": "Oil Change",
            "issue": "Routine service",
            "time": "2026-10-25 14:00:00"
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter") as MockRouter:
            instance = MagicMock()
            instance.process_event.return_value = {"dispatches": []}
            MockRouter.return_value = instance

            payload = {
                "tool_call_id": "sms_apt_1",
                "name": "create_service_request",
                "arguments": {
                    "customer_name": "Jane Doe",
                    "phone": "555-002-0001",
                    "make": "Toyota",
                    "model": "Camry",
                    "year": 2020,
                    "issue_description": "Oil change",
                    "booking_type": "appointment",
                    "booking_time": "2026-10-25 14:00:00"
                }
            }
            with patch("serviceBot.services.gmail.send_booking_notification"), \
                 patch("serviceBot.services.gmail.send_admin_notification"):
                response = client.post("/api/v1/voice/tools", json=payload)

        assert response.status_code == 200
        assert response.json()["result"]["success"] is True
        instance.process_event.assert_called_once()
        evt_call = instance.process_event.call_args.kwargs
        assert evt_call["event_type"] == "BOOKING"
        assert evt_call["appointment_id"] == 201

    @patch("serviceBot.api.telephony.get_booking_details")
    @patch("serviceBot.api.telephony.create_service_request")
    @patch("serviceBot.api.telephony.lookup_customer_by_phone")
    def test_create_service_request_callback_triggers_sms(
        self, mock_lookup, mock_create, mock_details
    ):
        mock_lookup.return_value = {"customer_id": 42}
        mock_create.return_value = 202
        mock_details.return_value = {
            "customer_name": "Bob Smith",
            "phone": "+15550020002",
            "vehicle": "2019 Honda Civic",
            "service_type": "Brake inspection",
            "issue": "Squeaking",
            "time": "ASAP"
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter") as MockRouter:
            instance = MagicMock()
            instance.process_event.return_value = {"dispatches": []}
            MockRouter.return_value = instance

            payload = {
                "tool_call_id": "sms_cb_1",
                "name": "create_service_request",
                "arguments": {
                    "customer_name": "Bob Smith",
                    "phone": "555-002-0002",
                    "make": "Honda",
                    "model": "Civic",
                    "year": 2019,
                    "issue_description": "Squeaking brakes",
                    "booking_type": "callback",
                    "booking_time": "ASAP"
                }
            }
            with patch("serviceBot.services.gmail.send_booking_notification"), \
                 patch("serviceBot.services.gmail.send_admin_notification"):
                response = client.post("/api/v1/voice/tools", json=payload)

        assert response.status_code == 200
        assert response.json()["result"]["success"] is True
        instance.process_event.assert_called_once()
        evt_call = instance.process_event.call_args.kwargs
        assert evt_call["event_type"] == "BOOKING"

    @patch("serviceBot.api.telephony.get_booking_details")
    @patch("serviceBot.api.telephony.book_appointment")
    @patch("serviceBot.api.telephony.lookup_customer_by_phone")
    def test_book_appointment_triggers_sms(self, mock_lookup, mock_book, mock_details):
        mock_lookup.return_value = {
            "customer_id": 42,
            "name": "Carol White",
            "phone": "+15550020003",
            "make": "Ford",
            "model": "Focus",
            "year": 2021,
            "open_sr_id": 300
        }
        mock_book.return_value = 300
        mock_details.return_value = {
            "customer_name": "Carol White",
            "phone": "+15550020003",
            "vehicle": "2021 Ford Focus",
            "service_type": "Tire rotation",
            "issue": "",
            "time": "2026-10-30 09:00:00"
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter") as MockRouter:
            instance = MagicMock()
            instance.process_event.return_value = {"dispatches": []}
            MockRouter.return_value = instance

            payload = {
                "tool_call_id": "sms_book_1",
                "name": "book_appointment",
                "arguments": {
                    "phone": "555-002-0003",
                    "appointment_datetime": "2026-10-30 09:00:00",
                    "service_type": "Tire rotation"
                }
            }
            with patch("serviceBot.services.gmail.send_booking_notification"), \
                 patch("serviceBot.services.gmail.send_admin_notification"):
                response = client.post("/api/v1/voice/tools", json=payload)

        assert response.status_code == 200
        assert response.json()["result"]["success"] is True
        instance.process_event.assert_called_once()
        evt_call = instance.process_event.call_args.kwargs
        assert evt_call["event_type"] == "BOOKING"
        assert evt_call["appointment_id"] == 300

    @patch("serviceBot.api.telephony.get_booking_details")
    @patch("serviceBot.api.telephony.create_callback_request")
    @patch("serviceBot.api.telephony.create_service_request")
    @patch("serviceBot.api.telephony.lookup_customer_by_phone")
    def test_request_callback_triggers_sms(
        self, mock_lookup, mock_create_sr, mock_create_cb, mock_details
    ):
        mock_lookup.return_value = None
        mock_create_sr.return_value = 400
        mock_create_cb.return_value = 400
        mock_details.return_value = {
            "customer_name": "Dave Brown",
            "phone": "+15550020004",
            "vehicle": "2018 Chevy Malibu",
            "service_type": "Repair",
            "issue": "Check engine light",
            "time": "Tomorrow morning"
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter") as MockRouter:
            instance = MagicMock()
            instance.process_event.return_value = {"dispatches": []}
            MockRouter.return_value = instance

            payload = {
                "tool_call_id": "sms_reqcb_1",
                "name": "request_callback",
                "arguments": {
                    "phone": "555-002-0004",
                    "customer_name": "Dave Brown",
                    "make": "Chevy",
                    "model": "Malibu",
                    "year": 2018,
                    "issue_description": "Check engine light",
                    "preferred_time": "Tomorrow morning"
                }
            }
            with patch("serviceBot.services.gmail.send_booking_notification"), \
                 patch("serviceBot.services.gmail.send_admin_notification"):
                response = client.post("/api/v1/voice/tools", json=payload)

        assert response.status_code == 200
        assert response.json()["result"]["success"] is True
        instance.process_event.assert_called_once()
        evt_call = instance.process_event.call_args.kwargs
        assert evt_call["event_type"] == "BOOKING"

    @patch("serviceBot.api.telephony.get_booking_details")
    @patch("serviceBot.api.telephony.reschedule_appointment")
    @patch("serviceBot.api.telephony.get_customer_appointments")
    @patch("serviceBot.api.telephony.lookup_customer_by_phone")
    def test_reschedule_appointment_triggers_sms(
        self, mock_lookup, mock_get_appts, mock_reschedule, mock_details
    ):
        mock_lookup.return_value = {"customer_id": 42}
        mock_get_appts.return_value = [{"id": 500, "booking_time": "2026-10-25 14:00:00"}]
        mock_reschedule.return_value = True
        mock_details.return_value = {
            "customer_name": "Eve Green",
            "phone": "+15550020005",
            "vehicle": "2022 Tesla Model 3",
            "service_type": "Inspection",
            "issue": "",
            "time": "2026-11-05 11:00:00"
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter") as MockRouter:
            instance = MagicMock()
            instance.process_event.return_value = {"dispatches": []}
            MockRouter.return_value = instance

            payload = {
                "tool_call_id": "sms_resched_1",
                "name": "reschedule_appointment",
                "arguments": {
                    "phone": "555-002-0005",
                    "new_appointment_datetime": "2026-11-05 11:00:00"
                }
            }
            with patch("serviceBot.services.gmail.send_booking_notification"), \
                 patch("serviceBot.services.gmail.send_admin_notification"):
                response = client.post("/api/v1/voice/tools", json=payload)

        assert response.status_code == 200
        assert response.json()["result"]["success"] is True
        instance.process_event.assert_called_once()
        evt_call = instance.process_event.call_args.kwargs
        assert evt_call["event_type"] == "RESCHEDULED"
        assert evt_call["appointment_id"] == 500


# ===========================================================================
# 5. SMS failure isolation — SMS error doesn't break booking response
# ===========================================================================

class TestSMSFailureIsolation:
    """
    Even if SMS dispatch throws, the booking API must still return 200 success.
    """

    @patch("serviceBot.api.telephony.get_booking_details")
    @patch("serviceBot.api.telephony.create_service_request")
    @patch("serviceBot.api.telephony.lookup_customer_by_phone")
    def test_sms_failure_does_not_break_booking(
        self, mock_lookup, mock_create, mock_details
    ):
        mock_lookup.return_value = {"customer_id": 42}
        mock_create.return_value = 600
        mock_details.return_value = {
            "customer_name": "Frank Black",
            "phone": "+15550030001",
            "vehicle": "2020 BMW 3 Series",
            "service_type": "Oil Change",
            "issue": "",
            "time": "2026-10-25 14:00:00"
        }

        with patch("serviceBot.services.sms_router.SMSNotificationRouter") as MockRouter:
            instance = MagicMock()
            instance.process_event.side_effect = Exception("Twilio connection refused")
            MockRouter.return_value = instance

            payload = {
                "tool_call_id": "sms_fail_1",
                "name": "create_service_request",
                "arguments": {
                    "customer_name": "Frank Black",
                    "phone": "555-003-0001",
                    "make": "BMW",
                    "model": "3 Series",
                    "year": 2020,
                    "issue_description": "Oil change",
                    "booking_type": "appointment",
                    "booking_time": "2026-10-25 14:00:00"
                }
            }
            with patch("serviceBot.services.gmail.send_booking_notification"), \
                 patch("serviceBot.services.gmail.send_admin_notification"):
                response = client.post("/api/v1/voice/tools", json=payload)

        # Booking must still succeed even if SMS blows up
        assert response.status_code == 200
        assert response.json()["result"]["success"] is True
