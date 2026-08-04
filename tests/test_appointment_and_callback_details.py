import os
import json
import pytest
from unittest.mock import patch, MagicMock

from serviceBot.db.queries import book_appointment, create_callback_request, create_service_request
from serviceBot.db.connection import get_db_connection, dict_cursor


def test_system_prompts_mandate_detailed_descriptions():
    """Verify that system prompt files require rich, detailed descriptions for both appointments and callbacks."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # 1. system_prompt.txt
    txt_path = os.path.join(base_dir, "serviceBot", "system_prompt.txt")
    assert os.path.exists(txt_path)
    with open(txt_path, "r", encoding="utf-8") as f:
        txt_content = f.read()
    assert "MANDATORY" in txt_content
    assert "issue_description" in txt_content
    assert "Never leave the description generic or empty" in txt_content or "rich, complete details" in txt_content

    # 2. config.json
    cfg_path = os.path.join(base_dir, "serviceBot", "config.json")
    assert os.path.exists(cfg_path)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    sys_prompt = cfg.get("system_prompt", "")
    assert "MANDATORY" in sys_prompt
    assert "issue_description" in sys_prompt

    # 3. portal.py default system prompt
    portal_py = os.path.join(base_dir, "serviceBot", "api", "portal.py")
    with open(portal_py, "r", encoding="utf-8") as f:
        portal_code = f.read()
    assert "issue_description" in portal_code
    assert "combining all reported vehicle issues/services" in portal_code


@patch("serviceBot.services.google_calendar.create_agent_calendar_event")
@patch("serviceBot.services.google_calendar.is_agent_free", return_value=True)
def test_book_appointment_fallback_generates_detailed_description(mock_free, mock_agent_event):
    """Verify that book_appointment generates detailed issue_description if not provided or generic."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Create test customer and vehicle
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Detail Test Cust', '+15559990011') RETURNING id;")
            cust_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Kia', 'Forte', 2018) RETURNING id;", (cust_id,))
            veh_id = cursor.fetchone()["id"]

            cursor.execute("SELECT id FROM staff_agents LIMIT 1;")
            sa_row = cursor.fetchone()
            sa_id = sa_row["id"] if sa_row else 1

            appt_datetime = "2026-08-10 09:00:00"
            cursor.execute(
                "INSERT INTO mock_calendar_slots (staff_agent_id, slot_datetime, is_booked) VALUES (%s, %s, FALSE) ON CONFLICT (staff_agent_id, slot_datetime) DO UPDATE SET is_booked = FALSE;",
                (sa_id, appt_datetime)
            )
            conn.commit()
            appt_id = book_appointment(
                customer_id=cust_id,
                service_request_id=None,
                appointment_datetime=appt_datetime,
                service_type="Oil Change (Full Synthetic)",
                vehicle_details={"make": "Kia", "model": "Forte", "year": 2018}
            )

            # Retrieve created service request and verify description details
            cursor.execute("SELECT issue_description FROM service_requests WHERE id = %s;", (appt_id,))
            sr_row = cursor.fetchone()
            desc = sr_row["issue_description"]

            assert desc != "Appointment booking."
            assert "Oil Change" in desc
            assert "Kia" in desc or "2018" in desc
            assert appt_datetime in desc


@patch("serviceBot.services.gmail.send_booking_notification")
@patch("serviceBot.services.gmail.send_admin_notification")
def test_create_callback_request_fallback_generates_detailed_description(mock_admin_notif, mock_booking_notif):
    """Verify that create_callback_request generates detailed description when issue_description is generic."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Create test customer and vehicle
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Callback Test Cust', '+15559990022') RETURNING id;")
            cust_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Honda', 'Civic', 2021) RETURNING id;", (cust_id,))
            veh_id = cursor.fetchone()["id"]
            conn.commit()

            cb_id = create_callback_request(
                customer_id=cust_id,
                service_request_id=None,
                preferred_time="Tomorrow at 10 AM",
                vehicle_details={"make": "Honda", "model": "Civic", "year": 2021}
            )

            cursor.execute("SELECT issue_description, booking_type FROM service_requests WHERE id = %s;", (cb_id,))
            sr_row = cursor.fetchone()
            desc = sr_row["issue_description"]
            b_type = sr_row["booking_type"]

            assert b_type == "callback"
            assert desc != "Callback requested."
            assert "Callback requested" in desc or "Phone consultation" in desc
            assert "Honda" in desc or "Civic" in desc or "2021" in desc
            assert "Tomorrow at 10 AM" in desc
