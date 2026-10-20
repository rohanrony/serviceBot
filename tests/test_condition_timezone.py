"""Native operational timestamps compose with provider epochs in real PostgreSQL."""

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from live_simulations.core import SimulationError
from live_simulations.deployed_full_conditions import Conditions, Identity, _timestamp
from live_simulations.deployed_full_native import NativeReader

pytestmark = pytest.mark.test_layer("database")


@pytest.mark.parametrize("session_timezone", ["UTC", "America/Los_Angeles"])
@pytest.mark.parametrize(
    "business_timezone", ["America/New_York", "America/Los_Angeles"]
)
def test_native_condition_rows_keep_database_timezone_and_provider_epoch(
    tmp_path, monkeypatch, session_timezone, business_timezone
):
    from serviceBot.services import timezone_service, quiet_hours

    monkeypatch.setattr(
        timezone_service, "get_business_zoneinfo", lambda: ZoneInfo(business_timezone)
    )
    monkeypatch.setattr(
        quiet_hours, "_get_quiet_hours_tz", lambda: ZoneInfo(business_timezone)
    )
    instant = datetime(2026, 11, 11, 15, tzinfo=timezone.utc)
    cutoff = timezone_service.to_business_tz(instant).replace(tzinfo=None)
    release = quiet_hours.calculate_quiet_hours_release_time(
        instant, {"quiet_end_time": "08:00"}
    )
    schema = "conditions_test_" + uuid4().hex
    dsn = os.environ["TEST_DATABASE_URL"]
    with psycopg2.connect(dsn) as owner:
        with owner.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        owner.commit()
        try:
            scoped = make_dsn(
                dsn, options=f"-c search_path={schema} -c timezone={session_timezone}"
            )
            monkeypatch.setenv("CONDITIONS_TEST_DATABASE_URL", scoped)
            with psycopg2.connect(scoped) as writer:
                with writer.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE customers (id integer,phone text,sms_opt_in boolean);
                        CREATE TABLE staff_agents (id integer,phone_number text,is_active boolean);
                        CREATE TABLE services (id integer,name text);
                        CREATE TABLE service_staff_agents (staff_agent_id integer,service_id integer);
                        CREATE TABLE service_requests (id integer,customer_id integer,staff_agent_id integer,
                            service_type text,status text,confirmation_status text,escalation_status text,
                            escalation_reason text,confirmation_cutoff_at timestamp,confirmed_at timestamp);
                        CREATE TABLE sms_whitelist (phone_number text,whatsapp_onboarded boolean,twilio_verified boolean);
                        CREATE TABLE sms_log (id integer,appointment_id integer,recipient_phone text,
                            recipient_type text,status text,error_code text,twilio_message_sid text,
                            scheduled_send_at timestamp,sent_at timestamp,created_at timestamp);
                        CREATE TABLE sms_conversations (id integer,context_appointment_id integer,customer_phone text);
                        CREATE TABLE sms_messages (id integer,conversation_id integer,direction text,body text,
                            twilio_message_sid text,created_at timestamp);
                        CREATE TABLE service_request_audit_log (id integer,request_id integer,event_type text,
                            triggered_by text,metadata jsonb,created_at timestamp);
                        CREATE TABLE outbox_notifications (id integer,request_id integer,event_type text,
                            status text,payload jsonb,created_at timestamp,updated_at timestamp);
                        CREATE TABLE sms_config (id integer,quiet_hours_enabled boolean,
                            quiet_start_time time,quiet_end_time time);
                        INSERT INTO customers VALUES (9,'+15550000001',true);
                        INSERT INTO staff_agents VALUES (4,'+15550000002',true);
                        INSERT INTO services VALUES (1,'Oil Change');
                        INSERT INTO service_staff_agents VALUES (4,1);
                        INSERT INTO service_requests VALUES (31,9,4,'Oil Change','pending',
                            'pending_agent_confirmation','none',NULL,
                            TIMESTAMPTZ '2026-11-11T15:15:00+00:00',TIMESTAMPTZ '2026-11-11T15:00:00+00:00');
                        INSERT INTO sms_whitelist VALUES ('+15550000001',true,true);
                        INSERT INTO sms_log VALUES (50,31,'+15550000001','customer','DELIVERED',NULL,
                            'SMaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',TIMESTAMPTZ '2026-11-11T15:01:00+00:00',
                            TIMESTAMPTZ '2026-11-11T15:00:30+00:00',TIMESTAMPTZ '2026-11-11T15:00:00+00:00');
                        INSERT INTO sms_conversations VALUES (1,31,'+15550000001');
                        INSERT INTO sms_messages VALUES (60,1,'inbound','CONFIRM #31',NULL,
                            TIMESTAMPTZ '2026-11-11T15:00:30+00:00');
                        INSERT INTO service_request_audit_log VALUES (70,31,'staff_confirmed','staff',
                            '{"agent_id":"4","phone":"+15550000002","reply":"CONFIRM #31"}',
                            TIMESTAMPTZ '2026-11-11T15:00:30+00:00');
                        INSERT INTO outbox_notifications VALUES (80,31,'calendar_projection','DELIVERED','{}',
                            TIMESTAMPTZ '2026-11-11T15:00:00+00:00',TIMESTAMPTZ '2026-11-11T15:01:00+00:00');
                        INSERT INTO sms_config VALUES (1,true,'21:00','08:00');
                    """)
                    cur.execute(
                        "UPDATE service_requests SET confirmation_cutoff_at=%s",
                        (cutoff,),
                    )
                    cur.execute("UPDATE sms_log SET scheduled_send_at=%s", (release,))
                writer.commit()
            adapter = SimpleNamespace(
                config={
                    "deployed_medium": {"database_env": "CONDITIONS_TEST_DATABASE_URL"}
                }
            )
            calls = []

            def message(sid):
                calls.append(sid)
                return dict(
                    sid=sid,
                    status="delivered",
                    direction="outbound-api",
                    error_code=None,
                    **{
                        "from": "+15550009999",
                        "to": "+15550000001",
                        "body": "Booking received",
                        "date_created": "Wed, 11 Nov 2026 15:00:00 +0000",
                        "date_sent": "Wed, 11 Nov 2026 15:00:30 +0000",
                    },
                )

            conditions = Conditions(
                tmp_path,
                reader=NativeReader(adapter),
                provider=SimpleNamespace(get_message=message),
                business_timezone=business_timezone,
            )
            snapshot = conditions._snapshot(Identity("a" * 32, "C42", 1, 9, 31, 4))
            epoch = datetime(2026, 11, 11, 15, tzinfo=timezone.utc).timestamp()
            assert snapshot["requests"][0]["confirmation_cutoff_at"] == epoch
            assert "confirmed_at" not in snapshot["requests"][0]
            assert snapshot["requests"][0]["confirmed_at_wall_clock"]
            assert (
                snapshot["logs"][0]["created_at"]
                == snapshot["provider_messages"][0]["date_created"]
                == epoch
            )
            assert (
                snapshot["logs"][0]["scheduled_send_at"]
                == release.replace(tzinfo=timezone.utc).timestamp()
            )
            assert (
                snapshot["logs"][0]["sent_at"]
                == snapshot["messages"][0]["created_at"]
                == epoch + 30
            )
            assert snapshot["audit"][0]["created_at"] == epoch + 30
            assert snapshot["outbox"][0]["created_at"] == epoch
            assert snapshot["outbox"][0]["updated_at"] == epoch + 60
            assert calls == ["SM" + "a" * 32]
        finally:
            with owner.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


@pytest.mark.parametrize("value", [datetime(2026, 11, 11, 15), "2026-11-11T15:00:00"])
def test_naive_condition_timestamp_is_not_guessed_as_utc(value):
    with pytest.raises(SimulationError, match="timezone"):
        _timestamp(value)
