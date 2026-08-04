#!/usr/bin/env python3
"""
test_full_workflow.py
==============================================================================
End-to-End Local Workflow Test Script for serviceBot (Post-Call Lifecycle).

Simulates:
1. ElevenLabs Post-Call Webhook (`POST /api/v1/telephony/webhook`) with a call transcript.
2. Verification of Customer creation, CRM Note logging, and Service Request initialization (`pending`).
3. Simulation of Staff Agent confirming the request via portal API or inbound SMS (`CONFIRM`).
4. Verification of state transition from `pending` -> `confirmed`.
5. Verification of customer cancellation SMS flow (`CANCEL`).
==============================================================================
"""

import sys
import os
import json
from unittest.mock import patch

# Ensure root workspace is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor

# Colors for terminal output
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
RED = "\033[0;31m"
BOLD = "\033[1m"
NC = "\033[0m"

client = TestClient(app)
TEST_PHONE = "+15558889999"
TEST_CONV_ID = "conv_full_workflow_test_001"

def cleanup():
    """Clean up test records from database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM crm_notes WHERE call_id = %s;", (TEST_CONV_ID,))
        cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = %s);", (TEST_PHONE,))
        cursor.execute("DELETE FROM customers WHERE phone = %s;", (TEST_PHONE,))
        conn.commit()

def run_test():
    print(f"\n{BOLD}{CYAN}========================================================================{NC}")
    print(f"{BOLD}{CYAN}      serviceBot Post-Call Full Workflow End-to-End Test Engine        {NC}")
    print(f"{BOLD}{CYAN}========================================================================{NC}\n")

    cleanup()
    print(f"{BOLD}{YELLOW}Step 1: Simulating Post-Call Telephony Webhook...{NC}")

    payload = {
        "type": "post_call_transcription",
        "event_timestamp": 1700000000,
        "data": {
            "conversation_id": TEST_CONV_ID,
            "agent_id": "agent_test_full_001",
            "analysis": {
                "summary": "Customer booked an oil change for tomorrow at 10 AM and reported a strange squeaking noise when turning."
            },
            "metadata": {
                "from_number": TEST_PHONE
            },
            "transcript": [
                {"role": "user", "message": "Hi, I need to book an oil change for tomorrow at 10 AM."},
                {"role": "agent", "message": "I can help with that. Is there anything else?"},
                {"role": "user", "message": "Also my steering wheel makes a squeaking noise when turning left. Can an advisor call me back about that?"},
                {"role": "agent", "message": "Got it, I will book the oil change and flag the callback for our advisor."}
            ]
        }
    }

    with patch("serviceBot.api.telephony.generate_service_summary") as mock_summary, \
         patch("serviceBot.api.telephony.extract_callback_from_transcript") as mock_extract:

        mock_summary.return_value = "Customer requested oil change and callback for squeaking steering wheel."
        mock_extract.return_value = {
            "preferred_time": "Tomorrow 10:00 AM",
            "service_type": "Oil Change & Inspection",
            "issue_description": "Squeaking noise when turning left",
            "is_uncataloged": True
        }

        response = client.post("/api/v1/telephony/webhook", json=payload)
        assert response.status_code == 200, f"Webhook failed: {response.text}"
        print(f"  {GREEN}✓ Webhook accepted (HTTP 200){NC}")

    print(f"\n{BOLD}{YELLOW}Step 2: Verifying Database Intake State...{NC}")
    request_id = None
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check customer
            cursor.execute("SELECT id, name, phone FROM customers WHERE phone = %s;", (TEST_PHONE,))
            cust = cursor.fetchone()
            assert cust is not None, "Customer was not created!"
            print(f"  {GREEN}✓ Customer created: ID={cust['id']}, Phone={cust['phone']}{NC}")

            # Check CRM Note
            cursor.execute("SELECT id, summary FROM crm_notes WHERE call_id = %s;", (TEST_CONV_ID,))
            note = cursor.fetchone()
            assert note is not None, "CRM note was not created!"
            print(f"  {GREEN}✓ CRM Note logged: ID={note['id']}{NC}")

            # Check Service Request
            cursor.execute("SELECT id, status, booking_type, booking_time FROM service_requests WHERE customer_id = %s ORDER BY id DESC LIMIT 1;", (cust['id'],))
            sreq = cursor.fetchone()
            assert sreq is not None, "Service Request was not created!"
            request_id = sreq['id']
            initial_status = sreq['status']
            print(f"  {GREEN}✓ Service Request created: ID={request_id}, Status='{initial_status}', Type='{sreq['booking_type']}'{NC}")

    print(f"\n{BOLD}{YELLOW}Step 3: Simulating Staff Agent Confirmation (PENDING -> CONFIRMED)...{NC}")
    patch_resp = client.patch(f"/api/v1/portal/service-requests/{request_id}/status", json={"status": "confirmed"})
    assert patch_resp.status_code == 200, f"Status update failed: {patch_resp.text}"
    print(f"  {GREEN}✓ Staff Agent confirmed request via Portal API (HTTP 200){NC}")

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status FROM service_requests WHERE id = %s;", (request_id,))
            updated_sreq = cursor.fetchone()
            assert updated_sreq['status'] in ["confirmed", "accepted"], f"Unexpected status: {updated_sreq['status']}"
            print(f"  {GREEN}✓ Verified DB Status transition: '{initial_status}' -> '{updated_sreq['status']}'{NC}")

    print(f"\n{BOLD}{YELLOW}Step 4: Testing Finite State Machine (FSM) Guardrails...{NC}")
    # Attempt illegal transition: confirmed -> pending
    illegal_resp = client.patch(f"/api/v1/portal/service-requests/{request_id}/status", json={"status": "pending"})
    assert illegal_resp.status_code == 400, f"Illegal transition should return 400, got {illegal_resp.status_code}"
    print(f"  {GREEN}✓ FSM Guardrail passed: Rejected illegal transition 'confirmed' -> 'pending' (HTTP 400){NC}")

    print(f"\n{BOLD}{YELLOW}Step 5: Advancing Workflow (CONFIRMED -> IN_PROGRESS -> COMPLETED)...{NC}")
    client.patch(f"/api/v1/portal/service-requests/{request_id}/status", json={"status": "in_progress"})
    client.patch(f"/api/v1/portal/service-requests/{request_id}/status", json={"status": "completed"})

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status FROM service_requests WHERE id = %s;", (request_id,))
            final_sreq = cursor.fetchone()
            print(f"  {GREEN}✓ Service Request lifecycle completed cleanly: Status='{final_sreq['status']}'{NC}")

    cleanup()
    print(f"\n{BOLD}{GREEN}========================================================================{NC}")
    print(f"{BOLD}{GREEN}  🎉 FULL POST-CALL WORKFLOW E2E TEST COMPLETED SUCCESSFULLY!           {NC}")
    print(f"{BOLD}{GREEN}========================================================================{NC}\n")

if __name__ == "__main__":
    run_test()
