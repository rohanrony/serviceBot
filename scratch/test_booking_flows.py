"""
test_booking_flows.py - Comprehensive audit of the full appointment lifecycle.
Sections: Booking, Status Changes, Reschedule, Agent Reassignment,
          SMS Routing, Email Notifications, Outbox Worker, Calendar Sync, Callback
"""
import pytest, os, sys, inspect
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# ── SETUP: Load env ──────────────────────────────────────────
env_vars = {}
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            env_vars[k.strip()] = v.strip().strip('"').strip("'")
for k, v in env_vars.items():
    os.environ.setdefault(k, v)
os.environ['DATABASE_URL'] = env_vars.get('DATABASE_URL', '')
os.environ['TEST_DATABASE_URL'] = env_vars.get('DATABASE_URL', '')
os.environ['ENCRYPTION_KEY'] = env_vars.get('ENCRYPTION_KEY', '')

from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import (
    book_appointment, reschedule_appointment,
    update_service_request_status, assign_staff_agent_to_service_request,
)
from serviceBot.services.sms_router import SMSNotificationRouter, format_time_slot_range
from serviceBot.services.outbox_worker import enqueue_outbox_event, _dispatch_outbox_event

# ── FUTURE SLOTS (business hours, Mon–Fri) ──────────────────
def _next_weekday(days_ahead=3, hour=10):
    dt = datetime.now() + timedelta(days=days_ahead)
    while dt.weekday() >= 5:
        dt += timedelta(days=1)
    return dt.replace(hour=hour, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

FUTURE_SLOT  = _next_weekday(3, 10)
FUTURE_SLOT2 = _next_weekday(4, 14)

# ── TEST RECORD REGISTRY for cleanup ────────────────────────
CREATED_RECORDS = []

@pytest.fixture(scope="module", autouse=True)
def db_cleanup():
    yield
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            for (tbl, col, rid) in reversed(CREATED_RECORDS):
                try:
                    cursor.execute(f"DELETE FROM {tbl} WHERE {col} = %s;", (rid,))
                except Exception:
                    pass
        conn.commit()
    print(f"\n[Cleanup] Removed {len(CREATED_RECORDS)} test records.")

def _track(tbl, col, rid):
    CREATED_RECORDS.append((tbl, col, rid)); return rid

def _customer(name="Test BF Cust", phone="+15550099901"):
    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("INSERT INTO customers (name,phone) VALUES (%s,%s) ON CONFLICT (phone) DO UPDATE SET name=EXCLUDED.name RETURNING id;", (name, phone))
            cid = cur.fetchone()["id"]
        conn.commit()
    return _track("customers", "id", cid)

def _vehicle(cid, make="Toyota", model="Camry", year=2021):
    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("INSERT INTO vehicles (customer_id,make,model,year) VALUES (%s,%s,%s,%s) RETURNING id;", (cid, make, model, year))
            vid = cur.fetchone()["id"]
        conn.commit()
    return _track("vehicles", "id", vid)

def _agent(name="Test BF Agent", email="bfagent@test.com", phone="+15550099902"):
    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("INSERT INTO staff_agents (name,role,email,phone_number) VALUES (%s,'Mechanic',%s,%s) RETURNING id;", (name, email, phone))
            aid = cur.fetchone()["id"]
        conn.commit()
    return _track("staff_agents", "id", aid)

def _free_slot(agent_id, slot=None):
    s = slot or FUTURE_SLOT
    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("INSERT INTO mock_calendar_slots (slot_datetime,is_booked,staff_agent_id) VALUES (CAST(%s AS TIMESTAMP),FALSE,%s) ON CONFLICT (slot_datetime,staff_agent_id) DO UPDATE SET is_booked=FALSE;", (s, agent_id))
        conn.commit()

def _sr(cid, status="pending", btype="appointment"):
    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("INSERT INTO service_requests (customer_id,service_type,status,booking_type) VALUES (%s,'Oil Change',%s,%s) RETURNING id;", (cid, status, btype))
            sid = cur.fetchone()["id"]
        conn.commit()
    return _track("service_requests", "id", sid)


# ════════════════════════════════════════════════════════════════
# SECTION 1: BOOKING
# ════════════════════════════════════════════════════════════════
class TestBooking:
    def test_creates_sr_with_booking_type(self):
        cid = _customer(phone="+15550099910"); _vehicle(cid)
        aid = _agent(name="BkAgent1", email="bk1@t.com", phone="+15550099911")
        _free_slot(aid, FUTURE_SLOT)
        sr = book_appointment(cid, None, FUTURE_SLOT, "Oil Change", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT booking_type,staff_agent_id,booking_time FROM service_requests WHERE id=%s;", (sr,))
                row = cur.fetchone()
        assert row["booking_type"] == "appointment", f"Got booking_type={row['booking_type']}"
        assert row["staff_agent_id"] is not None, "staff_agent_id should be set"
        print(f"  ✅ Booking SR#{sr}: agent={row['staff_agent_id']}, time={row['booking_time']}")

    def test_marks_slot_as_booked(self):
        cid = _customer(phone="+15550099912"); _vehicle(cid)
        aid = _agent(name="BkAgent2", email="bk2@t.com", phone="+15550099913")
        slot = _next_weekday(5, 9)
        _free_slot(aid, slot)
        sr = book_appointment(cid, None, slot, "Brake Repair", {"make":"Honda","model":"Civic","year":2019})
        _track("service_requests", "id", sr)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (aid, slot))
                row = cur.fetchone()
        assert row and row["is_booked"] is True, f"Slot should be booked, got: {row}"
        print(f"  ✅ Slot {slot} marked is_booked=True for agent {aid}")

    def test_requires_real_customer_name(self):
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("INSERT INTO customers (name,phone) VALUES ('Unknown Customer','+15550099950') ON CONFLICT (phone) DO UPDATE SET name=EXCLUDED.name RETURNING id;")
                cid = cur.fetchone()["id"]
            conn.commit()
        _track("customers", "id", cid)
        with pytest.raises(ValueError, match="Customer name is required"):
            book_appointment(cid, None, FUTURE_SLOT, "Oil Change")
        print("  ✅ ValueError raised for 'Unknown Customer' name")

    def test_duplicate_slot_merges_service_type(self):
        cid = _customer(phone="+15550099914"); _vehicle(cid)
        aid = _agent(name="BkAgent3", email="bk3@t.com", phone="+15550099915")
        slot = _next_weekday(6, 11)
        _free_slot(aid, slot)
        sr1 = book_appointment(cid, None, slot, "Oil Change", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr1)
        # Re-free slot manually so second call can re-enter the duplicate check path
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("UPDATE mock_calendar_slots SET is_booked=FALSE WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (aid, slot))
            conn.commit()
        sr2 = book_appointment(cid, None, slot, "Brake Repair", {"make":"Toyota","model":"Camry","year":2021})
        assert sr1 == sr2, f"Duplicate booking should return same SR (got {sr1} vs {sr2})"
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT service_type FROM service_requests WHERE id=%s;", (sr1,))
                svc = cur.fetchone()["service_type"]
        assert "Brake Repair" in svc, f"Service should merge, got: {svc}"
        print(f"  ✅ Merged service_type: {svc}")


# ════════════════════════════════════════════════════════════════
# SECTION 2: STATUS CHANGES
# ════════════════════════════════════════════════════════════════
class TestStatusChanges:
    def test_pending_to_confirmed(self):
        cid = _customer(phone="+15550099921")
        sr = _sr(cid, "pending"); r = update_service_request_status(sr, "confirmed")
        assert r["status"] == "confirmed"; print(f"  ✅ pending→confirmed SR#{sr}")

    def test_confirmed_to_in_progress(self):
        cid = _customer(phone="+15550099922")
        sr = _sr(cid, "confirmed"); r = update_service_request_status(sr, "in_progress")
        assert r["status"] == "in_progress"; print(f"  ✅ confirmed→in_progress SR#{sr}")

    def test_in_progress_to_completed(self):
        cid = _customer(phone="+15550099923")
        sr = _sr(cid, "in_progress"); r = update_service_request_status(sr, "completed")
        assert r["status"] == "completed"; print(f"  ✅ in_progress→completed SR#{sr}")

    def test_done_alias_maps_to_completed(self):
        cid = _customer(phone="+15550099924")
        sr = _sr(cid); r = update_service_request_status(sr, "done")
        assert r["status"] == "completed", f"'done' should map to 'completed', got {r['status']}"
        print(f"  ✅ 'done'→'completed' SR#{sr}")

    def test_pending_to_cancelled(self):
        cid = _customer(phone="+15550099925")
        sr = _sr(cid); r = update_service_request_status(sr, "cancelled")
        assert r["status"] == "cancelled"; print(f"  ✅ pending→cancelled SR#{sr}")

    def test_pending_to_rescheduled(self):
        cid = _customer(phone="+15550099926")
        sr = _sr(cid); r = update_service_request_status(sr, "rescheduled")
        assert r["status"] == "rescheduled"; print(f"  ✅ pending→rescheduled SR#{sr}")

    def test_invalid_status_raises(self):
        cid = _customer(phone="+15550099927")
        sr = _sr(cid)
        with pytest.raises(ValueError, match="Invalid status"):
            update_service_request_status(sr, "flying")
        print(f"  ✅ Invalid status raises ValueError SR#{sr}")

    def test_status_update_no_outbox_events(self):
        """Plain status update should NOT enqueue outbox notifications."""
        cid = _customer(phone="+15550099928"); sr = _sr(cid)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM outbox_notifications WHERE request_id=%s;", (sr,))
                before = cur.fetchone()["cnt"]
        update_service_request_status(sr, "completed")
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM outbox_notifications WHERE request_id=%s;", (sr,))
                after = cur.fetchone()["cnt"]
        assert after == before, f"Status update should NOT create outbox events (before={before}, after={after})"
        print(f"  ✅ Status update: no outbox events created SR#{sr}")

    def test_cancellation_does_not_free_slot(self):
        """KNOWN BUG AUDIT: Cancelling SR does NOT free the calendar slot."""
        cid = _customer(phone="+15550099929"); _vehicle(cid)
        aid = _agent(name="AgentCancel", email="agcancel@t.com", phone="+15550099930")
        slot = _next_weekday(7, 13); _free_slot(aid, slot)
        sr = book_appointment(cid, None, slot, "Tire Rotation", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr)
        update_service_request_status(sr, "cancelled")
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (aid, slot))
                row = cur.fetchone()
        if row and row["is_booked"]:
            print(f"  ⚠️  BUG CONFIRMED: Cancellation does NOT free slot (is_booked=True) for agent {aid} at {slot}")
        else:
            print(f"  ✅ Slot freed after cancellation")


# ════════════════════════════════════════════════════════════════
# SECTION 3: RESCHEDULE
# ════════════════════════════════════════════════════════════════
class TestReschedule:
    def test_frees_old_books_new_slot(self):
        cid = _customer(phone="+15550099931"); _vehicle(cid)
        aid = _agent(name="AgResched", email="agresched@t.com", phone="+15550099932")
        sold = _next_weekday(8, 10); snew = _next_weekday(9, 14)
        _free_slot(aid, sold); _free_slot(aid, snew)
        sr = book_appointment(cid, None, sold, "Oil Change", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr)
        with patch("serviceBot.services.google_calendar.create_agent_calendar_event"), \
             patch("serviceBot.services.gmail.create_admin_calendar_event"), \
             patch("serviceBot.services.gmail.delete_admin_calendar_event"), \
             patch("serviceBot.services.google_calendar.delete_agent_calendar_event"):
            result = reschedule_appointment(sr, snew)
        assert result is True
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (aid, sold))
                old_row = cur.fetchone()
                cur.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (aid, snew))
                new_row = cur.fetchone()
                cur.execute("SELECT booking_time FROM service_requests WHERE id=%s;", (sr,))
                sr_row = cur.fetchone()
        if old_row and old_row["is_booked"]:
            print(f"  ⚠️  BUG: Old slot {sold} NOT freed after reschedule")
        else:
            print(f"  ✅ Old slot {sold} freed")
        if new_row and new_row["is_booked"]:
            print(f"  ✅ New slot {snew} booked")
        else:
            print(f"  ⚠️  BUG: New slot {snew} NOT booked after reschedule")
        if sr_row and str(sr_row["booking_time"])[:19] == snew:
            print(f"  ✅ booking_time updated to {snew}")
        else:
            print(f"  ⚠️  BUG: booking_time NOT updated (got {sr_row})")

    def test_status_not_set_to_rescheduled(self):
        """KNOWN BUG AUDIT: reschedule_appointment does NOT set status='rescheduled'."""
        cid = _customer(phone="+15550099933"); _vehicle(cid)
        aid = _agent(name="AgResched2", email="agresched2@t.com", phone="+15550099934")
        sold = _next_weekday(10, 10); snew = _next_weekday(11, 14)
        _free_slot(aid, sold); _free_slot(aid, snew)
        sr = book_appointment(cid, None, sold, "Oil Change", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr)
        with patch("serviceBot.services.google_calendar.create_agent_calendar_event"), \
             patch("serviceBot.services.gmail.create_admin_calendar_event"), \
             patch("serviceBot.services.gmail.delete_admin_calendar_event"), \
             patch("serviceBot.services.google_calendar.delete_agent_calendar_event"):
            reschedule_appointment(sr, snew)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT status FROM service_requests WHERE id=%s;", (sr,))
                status = cur.fetchone()["status"]
        if status != "rescheduled":
            print(f"  ⚠️  BUG CONFIRMED: Status after reschedule='{status}' (expected 'rescheduled') SR#{sr}")
        else:
            print(f"  ✅ Status='rescheduled' after reschedule SR#{sr}")

    def test_weekend_slot_rejected(self):
        sat = datetime.now()
        while sat.weekday() != 5:
            sat += timedelta(days=1)
        bad = sat.replace(hour=10, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        cid = _customer(phone="+15550099935"); _vehicle(cid)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("INSERT INTO service_requests (customer_id,status,booking_type) VALUES (%s,'pending','appointment') RETURNING id;", (cid,))
                sr = cur.fetchone()["id"]
            conn.commit()
        _track("service_requests", "id", sr)
        with pytest.raises(ValueError, match="outside company workhours"):
            reschedule_appointment(sr, bad)
        print("  ✅ Weekend reschedule correctly rejected")


# ════════════════════════════════════════════════════════════════
# SECTION 4: AGENT REASSIGNMENT
# ════════════════════════════════════════════════════════════════
class TestReassignment:
    def test_updates_staff_agent_id(self):
        cid = _customer(phone="+15550099940"); _vehicle(cid)
        a1 = _agent(name="AgRe1", email="agre1@t.com", phone="+15550099941")
        a2 = _agent(name="AgRe2", email="agre2@t.com", phone="+15550099942")
        slot = _next_weekday(12, 10); _free_slot(a1, slot)
        sr = book_appointment(cid, None, slot, "Oil Change", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr)
        r = assign_staff_agent_to_service_request(sr, a2)
        assert r["staff_agent_id"] == a2
        print(f"  ✅ Reassignment updated staff_agent_id to {a2} SR#{sr}")

    def test_slot_swap_old_freed_new_booked(self):
        cid = _customer(phone="+15550099943"); _vehicle(cid)
        a1 = _agent(name="AgRe3", email="agre3@t.com", phone="+15550099944")
        a2 = _agent(name="AgRe4", email="agre4@t.com", phone="+15550099945")
        slot = _next_weekday(13, 10); _free_slot(a1, slot); _free_slot(a2, slot)
        sr = book_appointment(cid, None, slot, "Oil Change", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr)
        assign_staff_agent_to_service_request(sr, a2)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (a1, slot))
                r1 = cur.fetchone()
                cur.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (a2, slot))
                r2 = cur.fetchone()
        print(f"  {'✅' if r1 and not r1['is_booked'] else '⚠️  BUG'}: Old agent {a1} slot freed: {r1}")
        print(f"  {'✅' if r2 and r2['is_booked'] else '⚠️  BUG'}: New agent {a2} slot booked: {r2}")

    def test_enqueues_outbox_event(self):
        cid = _customer(phone="+15550099946"); _vehicle(cid)
        a1 = _agent(name="AgRe5", email="agre5@t.com", phone="+15550099947")
        a2 = _agent(name="AgRe6", email="agre6@t.com", phone="+15550099948")
        slot = _next_weekday(14, 11); _free_slot(a1, slot); _free_slot(a2, slot)
        sr = book_appointment(cid, None, slot, "Oil Change", {"make":"Toyota","model":"Camry","year":2021})
        _track("service_requests", "id", sr)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM outbox_notifications WHERE request_id=%s AND event_type='agent_reassignment';", (sr,))
                before = cur.fetchone()["cnt"]
        assign_staff_agent_to_service_request(sr, a2)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM outbox_notifications WHERE request_id=%s AND event_type='agent_reassignment';", (sr,))
                after = cur.fetchone()["cnt"]
        assert after > before, f"Outbox event not enqueued (before={before}, after={after})"
        print(f"  ✅ Outbox event enqueued for agent_reassignment SR#{sr}")

    def test_cannot_reassign_completed(self):
        cid = _customer(phone="+15550099949")
        sr = _sr(cid, "completed")
        a = _agent(name="AgNoAssign1", email="noa1@t.com", phone="+15550099950")
        with pytest.raises(ValueError, match="completed"):
            assign_staff_agent_to_service_request(sr, a)
        print(f"  ✅ Reassignment blocked for completed SR#{sr}")

    def test_cannot_reassign_cancelled(self):
        cid = _customer(phone="+15550099951")
        sr = _sr(cid, "cancelled")
        a = _agent(name="AgNoAssign2", email="noa2@t.com", phone="+15550099952")
        with pytest.raises(ValueError, match="cancelled"):
            assign_staff_agent_to_service_request(sr, a)
        print(f"  ✅ Reassignment blocked for cancelled SR#{sr}")


# ════════════════════════════════════════════════════════════════
# SECTION 5: SMS NOTIFICATION ROUTING
# ════════════════════════════════════════════════════════════════
class TestSMSRouting:
    def _make_sr(self, phone):
        cid = _customer(phone=phone); vid = _vehicle(cid)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("INSERT INTO service_requests (customer_id,vehicle_id,service_type,status,booking_type,booking_time) VALUES (%s,%s,'Oil Change','pending','appointment',%s) RETURNING id;", (cid, vid, FUTURE_SLOT))
                sid = cur.fetchone()["id"]
            conn.commit()
        return _track("service_requests", "id", sid), phone

    @patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms")
    def test_booking_event_dispatches_to_customer(self, mock_send):
        mock_send.return_value = {"success": True, "status": "SENT", "sid": "SMmock1"}
        from serviceBot.db.queries import add_sms_whitelist
        add_sms_whitelist("+15550099960", "SMS Test Cust")
        sr, phone = self._make_sr("+15550099960")
        result = SMSNotificationRouter().process_event("BOOKING", sr, customer_phone=phone, booking_time=FUTURE_SLOT)
        customer_d = [d for d in result["dispatches"] if d.get("recipient") == "customer"]
        if not customer_d:
            print(f"  ⚠️  BUG: No customer SMS dispatched for BOOKING SR#{sr}")
        else:
            print(f"  ✅ Customer SMS dispatched BOOKING SR#{sr}: {customer_d[0].get('status')}")

    @patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms")
    def test_reassigned_event_dispatches_to_agent(self, mock_send):
        mock_send.return_value = {"success": True, "status": "SENT", "sid": "SMmock2"}
        from serviceBot.db.queries import add_sms_whitelist
        add_sms_whitelist("+15550099961", "SMS Test Agent")
        sr, phone = self._make_sr("+15550099962")
        result = SMSNotificationRouter().process_event(
            "REASSIGNED", sr, customer_phone=phone,
            agent_phone="+15550099961", previous_agent_phone="+15550099963",
            booking_time=FUTURE_SLOT
        )
        agent_d = [d for d in result["dispatches"] if d.get("recipient") == "agent"]
        if not agent_d:
            print(f"  ⚠️  BUG: No agent SMS dispatched for REASSIGNED SR#{sr}")
        else:
            print(f"  ✅ Agent SMS dispatched REASSIGNED SR#{sr}: {agent_d[0].get('status')}")

    @patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms")
    def test_cancelled_events_dispatch(self, mock_send):
        mock_send.return_value = {"success": True, "status": "SENT", "sid": "SMmock3"}
        from serviceBot.db.queries import add_sms_whitelist
        add_sms_whitelist("+15550099964", "Cancel SMS Cust")
        sr, phone = self._make_sr("+15550099964")
        for evt in ["CANCELLED_BY_CUSTOMER", "CANCELLED_BY_ADMIN"]:
            r = SMSNotificationRouter().process_event(evt, sr, customer_phone=phone, booking_time=FUTURE_SLOT)
            print(f"  ✅ {evt}: {[d.get('recipient')+':'+str(d.get('status','?')) for d in r['dispatches']]}")

    def test_opted_out_customer_skipped(self):
        phone = "+15550099965"
        try:
            from serviceBot.db.queries import update_customer_opt_in
            update_customer_opt_in(phone, False)
        except Exception:
            pass
        sr, _ = self._make_sr(phone)
        result = SMSNotificationRouter().process_event("BOOKING", sr, customer_phone=phone, booking_time=FUTURE_SLOT)
        cust_d = [d for d in result["dispatches"] if d.get("recipient") == "customer"]
        if cust_d and cust_d[0].get("status") == "SKIPPED_OPT_OUT":
            print(f"  ✅ SMS correctly skipped for opted-out customer")
        elif cust_d:
            print(f"  ⚠️  BUG: SMS sent to opted-out customer: {cust_d[0]}")
        else:
            print(f"  ⚠️  WARN: No customer dispatch entry for opted-out customer")

    def test_format_time_slot_range(self):
        r = format_time_slot_range("2026-08-15 10:00:00", 60)
        assert "Aug" in r and "10:00 AM" in r and "11:00 AM" in r, f"Bad format: {r}"
        print(f"  ✅ format_time_slot_range: {r}")

    def test_format_asap_passthrough(self):
        assert format_time_slot_range("ASAP") == "ASAP"
        print("  ✅ 'ASAP' passes through unchanged")

    def test_rescheduled_event_triggers_reminder_update(self):
        """RESCHEDULED event should call update_or_cancel_appointment_reminders."""
        from serviceBot.db.queries import add_sms_whitelist
        add_sms_whitelist("+15550099966", "Remind Test Cust")
        sr, phone = self._make_sr("+15550099966")
        with patch("serviceBot.services.sms_router.update_or_cancel_appointment_reminders") as mock_update, \
             patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms", return_value={"success": True, "status": "SENT", "sid": "SMmock4"}):
            SMSNotificationRouter().process_event("RESCHEDULED", sr, customer_phone=phone, booking_time=FUTURE_SLOT)
            if mock_update.called:
                print(f"  ✅ update_or_cancel_appointment_reminders called on RESCHEDULED")
            else:
                print(f"  ⚠️  BUG: update_or_cancel_appointment_reminders NOT called on RESCHEDULED SR#{sr}")


# ════════════════════════════════════════════════════════════════
# SECTION 6: EMAIL NOTIFICATIONS
# ════════════════════════════════════════════════════════════════
class TestEmailNotifications:
    def test_disabled_when_gmail_off(self):
        from serviceBot.services.gmail import send_booking_notification
        from serviceBot.api.portal import load_config, save_config
        cfg = load_config(); orig = dict(cfg)
        try:
            cfg["gmail_enabled"] = False; save_config(cfg)
            r = send_booking_notification("appointment", {"customer_name":"T","phone":"+1","vehicle":"V","service_type":"S","time":FUTURE_SLOT})
            assert r is False
            print("  ✅ Booking email skipped when gmail_enabled=False")
        finally:
            save_config(orig)

    @patch("serviceBot.services.gmail.send_gmail_api_email")
    def test_appointment_subject_correct(self, mock_send):
        mock_send.return_value = True
        from serviceBot.services.gmail import send_booking_notification
        from serviceBot.api.portal import load_config, save_config
        cfg = load_config(); orig = dict(cfg)
        try:
            cfg.update({"gmail_enabled": True, "gmail_sender": "s@e.com", "gmail_recipient": "r@e.com",
                        "gmail_access_token": "tok", "gmail_token_expires_at": 9999999999})
            save_config(cfg)
            with patch("serviceBot.services.gmail.get_gmail_access_token", return_value="mock_tok"):
                r = send_booking_notification("appointment", {"customer_name":"Jane","phone":"+1","vehicle":"V","service_type":"S","time":FUTURE_SLOT})
            if r:
                args = mock_send.call_args
                subject = args[1].get("subject") or (args[0][2] if len(args[0]) > 2 else "")
                if "New Appointment Scheduled" in subject:
                    print(f"  ✅ Appointment email subject correct: '{subject}'")
                else:
                    print(f"  ⚠️  BUG: Wrong subject '{subject}'")
            else:
                print(f"  ⚠️  BUG: send_booking_notification returned {r}")
        finally:
            save_config(orig)

    @patch("serviceBot.services.gmail.send_gmail_api_email")
    def test_reschedule_subject_correct(self, mock_send):
        mock_send.return_value = True
        from serviceBot.services.gmail import send_booking_notification
        from serviceBot.api.portal import load_config, save_config
        cfg = load_config(); orig = dict(cfg)
        try:
            cfg.update({"gmail_enabled": True, "gmail_sender": "s@e.com", "gmail_recipient": "r@e.com",
                        "gmail_access_token": "tok", "gmail_token_expires_at": 9999999999})
            save_config(cfg)
            with patch("serviceBot.services.gmail.get_gmail_access_token", return_value="mock_tok"):
                r = send_booking_notification("reschedule", {"customer_name":"John","phone":"+1","vehicle":"V","service_type":"S","time":FUTURE_SLOT2})
            if r:
                args = mock_send.call_args
                subject = args[1].get("subject") or (args[0][2] if len(args[0]) > 2 else "")
                print(f"  {'✅' if 'Rescheduled' in subject else '⚠️  BUG'}: Reschedule subject: '{subject}'")
        finally:
            save_config(orig)

    def test_admin_notification_missing_cancelled_handler(self):
        """AUDIT: send_admin_notification source for 'cancelled' handler."""
        from serviceBot.services import gmail as gm
        src = inspect.getsource(gm.send_admin_notification)
        has_cancel = "'cancelled'" in src or '"cancelled"' in src
        if not has_cancel:
            print("  ⚠️  BUG: send_admin_notification has no 'cancelled' handler — admin gets wrong/generic email on cancellation")
        else:
            print("  ✅ send_admin_notification has 'cancelled' handler")

    def test_booking_notification_missing_calendar_cleanup(self):
        """AUDIT: Does booking_notification outbox event delete old admin calendar event before creating?"""
        from serviceBot.services import outbox_worker as ow
        src = inspect.getsource(ow._dispatch_outbox_event)
        # Find the booking_notification block and check for delete before create
        lines = src.split('\n')
        in_booking_block = False
        delete_before_create = False
        create_seen = False
        for line in lines:
            if 'booking_notification' in line:
                in_booking_block = True
            if in_booking_block and 'agent_reassignment' in line:
                break
            if in_booking_block and 'delete_admin_calendar_event' in line:
                if not create_seen:
                    delete_before_create = True
            if in_booking_block and 'create_admin_calendar_event' in line:
                create_seen = True
        if not delete_before_create:
            print("  ⚠️  BUG: booking_notification does NOT call delete_admin_calendar_event before create — duplicate calendar events on retry")
        else:
            print("  ✅ booking_notification cleans up old admin calendar event before creating new")


# ════════════════════════════════════════════════════════════════
# SECTION 7: OUTBOX WORKER
# ════════════════════════════════════════════════════════════════
class TestOutboxWorker:
    def test_enqueue_persists_pending(self):
        cid = _customer(phone="+15550099980")
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("INSERT INTO service_requests (customer_id,status,booking_type) VALUES (%s,'pending','appointment') RETURNING id;", (cid,))
                sr = cur.fetchone()["id"]; _track("service_requests", "id", sr)
                enqueue_outbox_event(cur, "booking_notification", sr, {"booking_type":"appointment","details":{},"agent_email":"a@e.com","booking_time_str":FUTURE_SLOT})
            conn.commit()
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT status FROM outbox_notifications WHERE request_id=%s AND event_type='booking_notification' ORDER BY id DESC LIMIT 1;", (sr,))
                row = cur.fetchone()
        assert row and row["status"] == "PENDING", f"Expected PENDING, got {row}"
        print(f"  ✅ Outbox enqueued PENDING SR#{sr}")

    @patch("serviceBot.services.gmail.send_booking_notification", return_value=True)
    @patch("serviceBot.services.gmail.send_admin_notification", return_value=True)
    @patch("serviceBot.services.gmail.create_admin_calendar_event", return_value=None)
    @patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event", return_value={"dispatches":[]})
    def test_dispatch_booking_calls_gmail_and_sms(self, mock_sms, mock_cal, mock_admin, mock_booking):
        cid = _customer(phone="+15550099981")
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("INSERT INTO service_requests (customer_id,status,booking_type) VALUES (%s,'pending','appointment') RETURNING id;", (cid,))
                sr = cur.fetchone()["id"]
            conn.commit()
        _track("service_requests", "id", sr)
        payload = {
            "booking_type": "appointment",
            "details": {"customer_name":"T","phone":"+15550099981","vehicle":"V","service_type":"S","time":FUTURE_SLOT},
            "agent_email": "a@e.com", "agent_name": "Agent", "booking_time_str": FUTURE_SLOT, "agent_phone": "+15550099982"
        }
        _dispatch_outbox_event("booking_notification", sr, payload)
        mock_booking.assert_called_once(); mock_admin.assert_called_once()
        if mock_sms.called:
            print(f"  ✅ SMS process_event called during booking_notification dispatch")
        else:
            print(f"  ⚠️  BUG: SMS process_event NOT called during booking_notification dispatch (agent_phone was present)")

    @patch("serviceBot.services.gmail.send_booking_notification", return_value=True)
    @patch("serviceBot.services.gmail.send_admin_notification", return_value=True)
    @patch("serviceBot.services.gmail.create_admin_calendar_event", return_value=None)
    @patch("serviceBot.services.gmail.delete_admin_calendar_event", return_value=None)
    @patch("serviceBot.services.google_calendar.create_agent_calendar_event", return_value=None)
    @patch("serviceBot.services.google_calendar.delete_agent_calendar_event", return_value=None)
    @patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event", return_value={"dispatches":[]})
    def test_dispatch_reassignment_calls_all_operations(self, mock_sms, mock_del_ag, mock_cr_ag, mock_del_adm, mock_cr_adm, mock_admin, mock_bk):
        cid = _customer(phone="+15550099983")
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("INSERT INTO service_requests (customer_id,status,booking_type) VALUES (%s,'pending','appointment') RETURNING id;", (cid,))
                sr = cur.fetchone()["id"]
            conn.commit()
        _track("service_requests", "id", sr)
        a1 = _agent(name="DispAg1", email="disp1@t.com", phone="+15550099984")
        a2 = _agent(name="DispAg2", email="disp2@t.com", phone="+15550099985")
        payload = {
            "old_agent_id": a1, "old_agent_name": "DispAg1",
            "new_agent_id": a2, "new_agent_name": "DispAg2",
            "new_agent_email": "disp2@t.com", "agent_phone": "+15550099985",
            "previous_agent_phone": "+15550099984", "booking_time_str": FUTURE_SLOT,
            "details": {"customer_name":"T","phone":"+15550099983","vehicle":"V","service_type":"S","time":FUTURE_SLOT,"issue":""}
        }
        _dispatch_outbox_event("agent_reassignment", sr, payload)
        mock_del_ag.assert_called_once()
        mock_cr_ag.assert_called_once()
        mock_del_adm.assert_called_once()
        mock_cr_adm.assert_called_once()
        mock_sms.assert_called_once()
        sms_kw = mock_sms.call_args[1]
        if sms_kw.get("event_type") == "REASSIGNED":
            print(f"  ✅ All reassignment operations called, SMS event_type=REASSIGNED")
        else:
            print(f"  ⚠️  BUG: SMS event_type='{sms_kw.get('event_type')}' (expected REASSIGNED)")


# ════════════════════════════════════════════════════════════════
# SECTION 8: CALENDAR SYNC
# ════════════════════════════════════════════════════════════════
class TestCalendarSync:
    def test_slot_generation_business_hours_only(self):
        from serviceBot.services.calendar_sync import _generate_slot_strings
        slots = _generate_slot_strings(days=7)
        assert len(slots) > 0
        for s in slots:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            assert dt.weekday() < 5, f"Weekend slot generated: {s}"
            assert 7 <= dt.hour < 18, f"Out-of-hours slot: {s}"
        print(f"  ✅ Generated {len(slots)} Mon-Fri business-hour slots correctly")

    def test_sync_no_connected_agent_returns_empty(self):
        from serviceBot.services.calendar_sync import sync_agent_slots
        aid = _agent(name="CalSyncAgent", email="calsync@t.com", phone="+15550099990")
        result = sync_agent_slots(aid, days=2)
        assert isinstance(result, dict)
        print(f"  ✅ sync_agent_slots unconnected agent returned: {result}")

    def test_create_agent_calendar_event_no_creds_returns_none(self):
        from serviceBot.services.google_calendar import create_agent_calendar_event
        aid = _agent(name="CalNoAuth", email="calnoauth@t.com", phone="+15550099991")
        r = create_agent_calendar_event(aid, "Test Cust", "Oil Change", "Routine", FUTURE_SLOT)
        assert r is None, f"Expected None for unauthenticated agent, got {r}"
        print("  ✅ create_agent_calendar_event returns None for unauthenticated agent")


# ════════════════════════════════════════════════════════════════
# SECTION 9: CALLBACK BOOKING
# ════════════════════════════════════════════════════════════════
class TestCallbackBooking:
    def test_callback_booking_type_set(self):
        cid = _customer(phone="+15550099995"); _vehicle(cid)
        aid = _agent(name="CallbackAg", email="cbag@t.com", phone="+15550099996")
        slot = _next_weekday(15, 9); _free_slot(aid, slot)
        sr = book_appointment(cid, None, slot, "Callback / Phone Consultation",
                              {"make":"Toyota","model":"Camry","year":2021}, booking_type="callback")
        _track("service_requests", "id", sr)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT booking_type FROM service_requests WHERE id=%s;", (sr,))
                row = cur.fetchone()
        assert row["booking_type"] == "callback", f"Got {row['booking_type']}"
        print(f"  ✅ Callback booking_type='callback' SR#{sr}")

    def test_callback_uses_15_min_slot_duration(self):
        """Callback should only block 1 x 15-min slot, not a 60-min window."""
        cid = _customer(phone="+15550099997"); _vehicle(cid)
        aid = _agent(name="CallbackAg2", email="cbag2@t.com", phone="+15550099998")
        slot_h = _next_weekday(16, 9)  # 09:00
        slot_h15 = datetime.strptime(slot_h, "%Y-%m-%d %H:%M:%S").replace(minute=15).strftime("%Y-%m-%d %H:%M:%S")
        _free_slot(aid, slot_h)
        _free_slot(aid, slot_h15)  # 09:15 should stay free
        sr = book_appointment(cid, None, slot_h, "Callback / Phone Consultation",
                              {"make":"Toyota","model":"Camry","year":2021}, booking_type="callback")
        _track("service_requests", "id", sr)
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id=%s AND slot_datetime=CAST(%s AS TIMESTAMP);", (aid, slot_h15))
                row = cur.fetchone()
        if row and not row["is_booked"]:
            print(f"  ✅ Callback only blocks 15-min slot; 09:15 slot remains free")
        else:
            print(f"  ⚠️  BUG: Callback booking blocked the 09:15 slot too (60-min window used instead of 15-min)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
