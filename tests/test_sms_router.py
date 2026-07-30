import pytest
import datetime as dt_mod
from serviceBot.services.sms_router import SMSNotificationRouter
from serviceBot.services.quiet_hours import is_in_quiet_hours, should_bypass_quiet_hours, calculate_quiet_hours_release_time
from serviceBot.services.sms_reminders import schedule_appointment_reminders, get_due_sms_reminders, cancel_pending_sms_reminders
from serviceBot.db.queries import update_customer_opt_in, get_customer_opt_in


def test_reassigned_agent_only_routing_matrix(dummy_appointment_id):
    router = SMSNotificationRouter()
    # Trigger REASSIGNED event (Agent A -> Agent B)
    res = router.process_event(
        event_type="REASSIGNED",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550192831",
        agent_phone="+15550192832",  # Agent B
        previous_agent_phone="+15550192833",  # Agent A
        admin_phone="+15550192834"
    )

    dispatches = res["dispatches"]
    recipients = [d["recipient"] for d in dispatches]

    # Customer and Admin should be isolated/suppressed by default
    assert "customer" not in recipients
    assert "admin" not in recipients
    # Agent B (assignment) and Agent A (unassignment) should be present
    assert "agent" in recipients
    assert "previous_agent" in recipients


def test_compound_rescheduled_reassigned_routing(dummy_appointment_id):
    router = SMSNotificationRouter()
    res = router.process_event(
        event_type="RESCHEDULED_REASSIGNED",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550192831",
        agent_phone="+15550192832",
        previous_agent_phone="+15550192833",
        booking_time="2026-10-25 14:00:00"
    )

    recipients = [d["recipient"] for d in res["dispatches"]]
    assert "customer" in recipients
    assert "agent" in recipients
    assert "previous_agent" in recipients


def test_opt_in_guard(dummy_appointment_id):
    phone = "+15550198888"
    update_customer_opt_in(phone, False)

    router = SMSNotificationRouter()
    res = router.process_event(
        event_type="BOOKING",
        appointment_id=dummy_appointment_id,
        customer_phone=phone,
        agent_phone="+15550192832"
    )

    cust_disp = next(d for d in res["dispatches"] if d["recipient"] == "customer")
    assert cust_disp["status"] == "SKIPPED_OPT_OUT"

    # Restore opt-in
    update_customer_opt_in(phone, True)


def test_quiet_hours_and_urgent_override():
    # Urgent appointment starting in 2 hours
    apt_urgent = dt_mod.datetime.now(dt_mod.timezone.utc) + dt_mod.timedelta(hours=2)
    assert should_bypass_quiet_hours(apt_urgent) is True

    # Non-urgent appointment starting in 7 days
    apt_far = dt_mod.datetime.now(dt_mod.timezone.utc) + dt_mod.timedelta(days=7)
    assert should_bypass_quiet_hours(apt_far) is False


def test_reminder_scheduling_and_cancellation(dummy_appointment_id):
    apt_id = dummy_appointment_id
    future_time = (dt_mod.datetime.now() + dt_mod.timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")

    # Schedule 24h & 2h reminders
    schedule_appointment_reminders(apt_id, future_time, customer_phone="+15550192831", agent_phone="+15550192832")

    # Cancel reminders
    cancel_pending_sms_reminders(apt_id)
    due = get_due_sms_reminders()
    assert not any(r["appointment_id"] == apt_id and r["status"] == "PENDING" for r in due)
