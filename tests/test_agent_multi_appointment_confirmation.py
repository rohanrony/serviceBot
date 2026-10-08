"""
Test Suite: Staff Agent Multi-Appointment Confirmation Disambiguation & Batch Processing
Feature: 004-agent-multi-appointment-confirmation
"""

import datetime as dt_mod
from unittest.mock import MagicMock, patch
import pytest

from serviceBot.services.sms_classifier import (
    parse_agent_confirmation_intent,
    handle_agent_confirmation_action,
)


# ==============================================================================
# Phase 2: Intent Parsing Engine Tests (T002)
# ==============================================================================

def test_parse_agent_confirmation_intent_bare_actions():
    """Verify bare confirmation and decline tokens are classified correctly."""
    assert parse_agent_confirmation_intent("CONFIRM") == {
        "action": "CONFIRM", "selector_type": "bare", "value": None
    }
    assert parse_agent_confirmation_intent("c") == {
        "action": "CONFIRM", "selector_type": "bare", "value": None
    }
    assert parse_agent_confirmation_intent("YES") == {
        "action": "CONFIRM", "selector_type": "bare", "value": None
    }
    assert parse_agent_confirmation_intent("accept") == {
        "action": "CONFIRM", "selector_type": "bare", "value": None
    }
    assert parse_agent_confirmation_intent("DECLINE") == {
        "action": "DECLINE", "selector_type": "bare", "value": None
    }
    assert parse_agent_confirmation_intent("unavailable") == {
        "action": "DECLINE", "selector_type": "bare", "value": None
    }
    assert parse_agent_confirmation_intent("no") == {
        "action": "DECLINE", "selector_type": "bare", "value": None
    }


def test_parse_agent_confirmation_intent_batch_actions():
    """Verify batch confirmation and decline phrases are parsed accurately."""
    assert parse_agent_confirmation_intent("CONFIRM ALL") == {
        "action": "CONFIRM_ALL", "selector_type": "batch", "value": None
    }
    assert parse_agent_confirmation_intent("confirm all") == {
        "action": "CONFIRM_ALL", "selector_type": "batch", "value": None
    }
    assert parse_agent_confirmation_intent("C ALL") == {
        "action": "CONFIRM_ALL", "selector_type": "batch", "value": None
    }
    assert parse_agent_confirmation_intent("accept all") == {
        "action": "CONFIRM_ALL", "selector_type": "batch", "value": None
    }
    assert parse_agent_confirmation_intent("DECLINE ALL") == {
        "action": "DECLINE_ALL", "selector_type": "batch", "value": None
    }
    assert parse_agent_confirmation_intent("reject all") == {
        "action": "DECLINE_ALL", "selector_type": "batch", "value": None
    }


def test_parse_agent_confirmation_intent_numeric_selectors():
    """Verify action + index / ID and pure numeric replies."""
    assert parse_agent_confirmation_intent("CONFIRM 1") == {
        "action": "CONFIRM", "selector_type": "numeric", "value": 1
    }
    assert parse_agent_confirmation_intent("C 2") == {
        "action": "CONFIRM", "selector_type": "numeric", "value": 2
    }
    assert parse_agent_confirmation_intent("confirm #101") == {
        "action": "CONFIRM", "selector_type": "numeric", "value": 101
    }
    assert parse_agent_confirmation_intent("DECLINE 2") == {
        "action": "DECLINE", "selector_type": "numeric", "value": 2
    }
    assert parse_agent_confirmation_intent("decline #102") == {
        "action": "DECLINE", "selector_type": "numeric", "value": 102
    }
    # Pure number reply answering disambiguation menu
    assert parse_agent_confirmation_intent("1") == {
        "action": "CONFIRM", "selector_type": "index", "value": 1
    }
    assert parse_agent_confirmation_intent("2") == {
        "action": "CONFIRM", "selector_type": "index", "value": 2
    }


# ==============================================================================
# Helper Mock Harness
# ==============================================================================

def _setup_mock_db(pending_appointments=None, superseded_appointment=None):
    mock_cursor = MagicMock()
    pending = list(pending_appointments or [])

    def mock_fetchall():
        return list(pending)

    def mock_fetchone():
        return superseded_appointment

    mock_cursor.fetchall.side_effect = mock_fetchall
    mock_cursor.fetchone.side_effect = mock_fetchone

    mock_cursor_ctx = MagicMock()
    mock_cursor_ctx.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__.return_value = mock_conn

    return mock_conn_ctx, mock_cursor_ctx, mock_cursor


# ==============================================================================
# Phase 3: User Story 1 - Single Job Fast Path Tests (T004, T005)
# ==============================================================================

def test_single_job_confirm_fast_path():
    """When technician has 1 pending job, replying CONFIRM immediately accepts it."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    single_pending = [{
        "id": 101,
        "staff_agent_id": 1,
        "confirmation_status": "pending_agent_confirmation",
        "escalation_status": None,
        "created_at": dt_mod.datetime(2026, 10, 8, 9, 0),
        "booking_time": "2026-10-12 10:00:00",
        "vehicle": "2021 Toyota Camry",
        "service_type": "Brake Inspection",
    }]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=single_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-1"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "CONFIRM")

    assert res["status"] == "processed"
    assert res["category"] in ("agent_confirmed", "agent_confirm")
    assert res["appointment_id"] == 101
    mock_update.assert_called_once()
    mock_cancel.assert_called_once_with(101, recipient_type="agent")
    mock_client.send_sms.assert_called_once()
    assert "Appointment #101 confirmed" in mock_client.send_sms.call_args[1]["body"]


def test_single_job_decline_fast_path():
    """When technician has 1 pending job, replying DECLINE immediately declines and escalates it."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    single_pending = [{
        "id": 101,
        "staff_agent_id": 1,
        "confirmation_status": "pending_agent_confirmation",
        "escalation_status": None,
        "created_at": dt_mod.datetime(2026, 10, 8, 9, 0),
        "booking_time": "2026-10-12 10:00:00",
        "vehicle": "2021 Toyota Camry",
        "service_type": "Brake Inspection",
    }]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=single_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-1"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.escalate_service_request") as mock_escalate, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "DECLINE")

    assert res["status"] == "processed"
    assert res["category"] in ("agent_declined", "agent_decline")
    assert res["appointment_id"] == 101
    mock_update.assert_called_once()
    mock_escalate.assert_called_once()
    mock_cancel.assert_called_once_with(101, recipient_type="agent")


# ==============================================================================
# Phase 4: User Story 2 - Disambiguation Menu for Multiple Jobs (T007)
# ==============================================================================

def test_multiple_jobs_bare_confirm_triggers_disambiguation_menu():
    """When technician has 2 pending jobs, bare CONFIRM returns numbered menu without altering state."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    two_pending = [
        {
            "id": 101,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 0),
            "booking_time": "2026-10-12 10:00:00",
            "vehicle": "2021 Toyota Camry",
            "service_type": "Brake Inspection",
        },
        {
            "id": 102,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 10),
            "booking_time": "2026-10-12 13:00:00",
            "vehicle": "2018 Ford F-150",
            "service_type": "Oil Change",
        },
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=two_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-menu"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update:

        res = handle_agent_confirmation_action(staff_agent, "CONFIRM")

    assert res["status"] == "disambiguation_requested"
    assert res["category"] == "agent_disambiguation_menu"
    assert res["pending_count"] == 2
    # Neither appointment was confirmed yet
    mock_update.assert_not_called()
    mock_client.send_sms.assert_called_once()
    body = mock_client.send_sms.call_args[1]["body"]
    assert "You have 2 assignments awaiting confirmation" in body
    assert "1️⃣ #101" in body
    assert "2️⃣ #102" in body
    assert "Reply CONFIRM 1 (or C 1), CONFIRM 2, or CONFIRM ALL" in body


# ==============================================================================
# Phase 5: User Story 3 - Index & Explicit ID Confirmation Tests (T009-T012)
# ==============================================================================

def test_multiple_jobs_confirm_by_index():
    """Replying CONFIRM 1 confirms the 1st appointment in the sorted schedule."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    two_pending = [
        {
            "id": 101,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 0),
            "booking_time": "2026-10-12 10:00:00",
            "vehicle": "2021 Toyota Camry",
            "service_type": "Brake Inspection",
        },
        {
            "id": 102,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 10),
            "booking_time": "2026-10-12 13:00:00",
            "vehicle": "2018 Ford F-150",
            "service_type": "Oil Change",
        },
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=two_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-idx1"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "CONFIRM 1")

    assert res["status"] == "processed"
    assert res["category"] in ("agent_confirmed", "agent_confirm")
    assert res["appointment_id"] == 101
    mock_update.assert_called_once()
    mock_cancel.assert_called_once_with(101, recipient_type="agent")
    body = mock_client.send_sms.call_args[1]["body"]
    assert "Appointment #101 confirmed" in body
    assert "1 assignment remaining: #102" in body


def test_multiple_jobs_decline_by_index():
    """Replying DECLINE 2 declines the 2nd appointment in the sorted schedule."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    two_pending = [
        {
            "id": 101,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 0),
            "booking_time": "2026-10-12 10:00:00",
            "vehicle": "2021 Toyota Camry",
            "service_type": "Brake Inspection",
        },
        {
            "id": 102,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 10),
            "booking_time": "2026-10-12 13:00:00",
            "vehicle": "2018 Ford F-150",
            "service_type": "Oil Change",
        },
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=two_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-dec2"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.escalate_service_request") as mock_escalate, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "DECLINE 2")

    assert res["status"] == "processed"
    assert res["category"] in ("agent_declined", "agent_decline")
    assert res["appointment_id"] == 102
    mock_update.assert_called_once()
    mock_escalate.assert_called_once()
    mock_cancel.assert_called_once_with(102, recipient_type="agent")
    body = mock_client.send_sms.call_args[1]["body"]
    assert "Appointment #102 marked declined" in body
    assert "1 assignment remaining: #101" in body


def test_multiple_jobs_confirm_by_explicit_id():
    """Replying CONFIRM 101 matches explicit appointment ID #101."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    two_pending = [
        {
            "id": 101,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 0),
            "booking_time": "2026-10-12 10:00:00",
            "vehicle": "2021 Toyota Camry",
            "service_type": "Brake Inspection",
        },
        {
            "id": 102,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 10),
            "booking_time": "2026-10-12 13:00:00",
            "vehicle": "2018 Ford F-150",
            "service_type": "Oil Change",
        },
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=two_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-id101"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "CONFIRM 101")

    assert res["status"] == "processed"
    assert res["appointment_id"] == 101
    mock_update.assert_called_once()
    mock_cancel.assert_called_once_with(101, recipient_type="agent")


def test_pure_number_reply_confirms_index():
    """Replying with just '1' answers disambiguation menu and confirms index 1."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    two_pending = [
        {
            "id": 101,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 0),
            "booking_time": "2026-10-12 10:00:00",
            "vehicle": "2021 Toyota Camry",
            "service_type": "Brake Inspection",
        },
        {
            "id": 102,
            "staff_agent_id": 1,
            "confirmation_status": "pending_agent_confirmation",
            "escalation_status": None,
            "created_at": dt_mod.datetime(2026, 10, 8, 9, 10),
            "booking_time": "2026-10-12 13:00:00",
            "vehicle": "2018 Ford F-150",
            "service_type": "Oil Change",
        },
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=two_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-1"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "1")

    assert res["status"] == "processed"
    assert res["appointment_id"] == 101
    mock_update.assert_called_once()
    mock_cancel.assert_called_once_with(101, recipient_type="agent")


# ==============================================================================
# Phase 6: User Story 4 - Batch Confirmation & Decline Tests (T014, T015)
# ==============================================================================

def test_batch_confirm_all_pending_jobs():
    """Replying CONFIRM ALL atomically confirms all pending appointments."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    three_pending = [
        {"id": 101, "staff_agent_id": 1, "confirmation_status": "pending_agent_confirmation", "booking_time": "2026-10-12 10:00:00"},
        {"id": 102, "staff_agent_id": 1, "confirmation_status": "pending_agent_confirmation", "booking_time": "2026-10-12 13:00:00"},
        {"id": 103, "staff_agent_id": 1, "confirmation_status": "pending_agent_confirmation", "booking_time": "2026-10-12 15:00:00"},
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=three_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-all"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "CONFIRM ALL")

    assert res["status"] == "processed"
    assert res["category"] == "agent_confirmed_all"
    assert res["confirmed_count"] == 3
    assert mock_update.call_count == 3
    assert mock_cancel.call_count == 3
    body = mock_client.send_sms.call_args[1]["body"]
    assert "Confirmed all 3 assignments (#101, #102, #103)" in body


def test_batch_decline_all_pending_jobs():
    """Replying DECLINE ALL atomically declines and escalates all pending appointments."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    two_pending = [
        {"id": 101, "staff_agent_id": 1, "confirmation_status": "pending_agent_confirmation", "booking_time": "2026-10-12 10:00:00"},
        {"id": 102, "staff_agent_id": 1, "confirmation_status": "pending_agent_confirmation", "booking_time": "2026-10-12 13:00:00"},
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=two_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-dec-all"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update, \
         patch("serviceBot.db.queries.escalate_service_request") as mock_escalate, \
         patch("serviceBot.db.queries.cancel_pending_sms_reminders") as mock_cancel:

        res = handle_agent_confirmation_action(staff_agent, "DECLINE ALL")

    assert res["status"] == "processed"
    assert res["category"] == "agent_declined_all"
    assert res["declined_count"] == 2
    assert mock_update.call_count == 2
    assert mock_escalate.call_count == 2
    assert mock_cancel.call_count == 2


# ==============================================================================
# Phase 7: Edge Cases & Hardening Tests (T017, T018)
# ==============================================================================

def test_out_of_bounds_index_returns_guidance():
    """Selecting an out-of-bounds index (e.g. CONFIRM 5 when 2 pending) returns helpful guidance."""
    staff_agent = {"id": 1, "name": "Alex Tech", "phone_number": "+15559990001"}
    two_pending = [
        {"id": 101, "staff_agent_id": 1, "confirmation_status": "pending_agent_confirmation", "booking_time": "2026-10-12 10:00:00"},
        {"id": 102, "staff_agent_id": 1, "confirmation_status": "pending_agent_confirmation", "booking_time": "2026-10-12 13:00:00"},
    ]

    mock_conn_ctx, mock_cursor_ctx, _ = _setup_mock_db(pending_appointments=two_pending)
    mock_client = MagicMock()
    mock_client.send_sms.return_value = {"success": True, "sid": "SM-test-err"}

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.services.sms_classifier.TwilioSMSClient", return_value=mock_client), \
         patch("serviceBot.db.queries.update_appointment_confirmation_status") as mock_update:

        res = handle_agent_confirmation_action(staff_agent, "CONFIRM 5")

    assert res["status"] == "error_out_of_bounds"
    mock_update.assert_not_called()
    body = mock_client.send_sms.call_args[1]["body"]
    assert "Invalid choice" in body
    assert "You have 2 pending assignments" in body
