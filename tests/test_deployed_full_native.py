"""Offline captured SQL/REST integration for compiled native bridge only."""

import copy
from types import SimpleNamespace

import httpx
import pytest

from live_simulations.core import SimulationError, private_json
from live_simulations.deployed_full_native import (
    C48Observers,
    GoogleEvents,
    NativeBridge,
    NativeReader,
)


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    yield


class Reader:
    def __init__(self):
        self.calls = []
        self.data = {
            "clock": [{"now_unix": 100}],
            "customer": [{"id": 9, "phone": "+14242704893"}],
            "baseline_requests": [
                {
                    "id": 10,
                    "customer_id": 9,
                    "service_type": "Original Repair",
                    "status": "pending",
                }
            ],
            "baseline_reservations": [{"id": 20, "service_request_id": 10}],
            "history_notes": [],
            "history_events": [],
            "reservations": [
                {
                    "id": 41,
                    "service_request_id": 31,
                    "staff_agent_id": 4,
                    "status": "ACTIVE",
                    "starts_at": "2026-11-11T10:00:00-05:00",
                    "ends_at": "2026-11-11T11:00:00-05:00",
                    "calendar_event_id": "event",
                    "calendar_integration_status": "CREATED",
                }
            ],
            "segments": [
                {
                    "reservation_id": 41,
                    "staff_agent_id": 4,
                    "segment_start": f"2026-11-11T10:{m:02}:00-05:00",
                }
                for m in (0, 15, 30, 45)
            ],
            "google_account": [
                {
                    "agent_id": 4,
                    "provider": "google",
                    "google_account_id": "google-user",
                    "email": "owner@example.invalid",
                    "access_token": "ciphertext",
                    "expires_at": 1000,
                    "granted_scopes": "https://www.googleapis.com/auth/calendar.events",
                }
            ],
            "projection": [
                {
                    "id": 51,
                    "request_id": 31,
                    "event_type": "calendar_projection",
                    "status": "DELIVERED",
                    "payload": {
                        "reservation_id": 41,
                        "agent_id": 4,
                        "calendar_event_id": "event",
                    },
                }
            ],
            "notifications": [
                {
                    "id": 61,
                    "appointment_id": 31,
                    "recipient_type": "customer",
                    "recipient_phone": "+14242704893",
                    "status": "DELIVERED",
                    "retry_count": 0,
                    "twilio_message_sid": "SM" + "1" * 32,
                }
            ],
            "preflight_staff": [
                {"id": 4, "phone_number": "+14242704893", "is_active": True},
                {"id": 5, "phone_number": "+14242704893", "is_active": True},
            ],
            "preflight_customer": [
                {"id": 9, "phone": "+14242704893", "sms_opt_in": True}
            ],
            "preflight_policy": [{"quiet_hours_enabled": True}],
            "preflight_enrollment": [
                {"phone_number": "+14242704893", "whatsapp_onboarded": True}
            ],
            "condition_poll": [],
        }
        self.raw = [
            {
                "id": 31,
                "customer_id": 9,
                "customer_phone": "+14242704893",
                "service_type": "Oil Change",
                "status": "pending",
                "booking_type": "appointment",
                "duration_minutes": 60,
                "staff_agent_id": 4,
                "starts_at": "2026-11-11T10:00:00-05:00",
                "ends_at": "2026-11-11T11:00:00-05:00",
                "reservation_id": 41,
            }
        ]

    def rows(self, query, params=()):
        assert query.lstrip().upper().startswith("SELECT")
        key = query.split("/* native:")[1].split(" */")[0]
        self.calls.append((key, params))
        return copy.deepcopy(self.data[key])

    def request_rows(self, ids):
        return copy.deepcopy([r for r in self.raw if r["id"] in ids])


def adapter(tmp_path):
    manifest = {
        "run_id": "a" * 32,
        "campaign_agent_id": "agent",
        "stage_authorization": {"authorization_id": "auth"},
        "invocations": [],
        "provider_tests": ["test"],
        "baseline": [{"id": 10}],
    }
    folder = tmp_path / ("a" * 32)
    private_json(folder / "manifest.json", manifest)
    private_json(tmp_path / "usage-ledger.json", {"entries": []})
    value = SimpleNamespace(
        config={
            "deployed_medium": {"technician_ids": [4, 5]},
            "existing_customer_identity": {"id": 9, "name": "Owned Customer"},
            "app_config": {"business_timezone": "America/New_York"},
            "deployed_url": "https://owned.invalid",
        },
        campaign=SimpleNamespace(root=tmp_path, folder=folder, manifest=manifest),
        state={"services": {"oil": {"name": "Oil Change"}}, "owned_request_ids": []},
        owned_ids=set(),
        current_ids=set(),
        original_ids={10},
    )
    value._guard = lambda: None
    value._save = lambda: None
    return value


def expected():
    return {
        "customer_id": 9,
        "staff_agent_id": 4,
        "service_type": "Oil Change",
        "starts_at": "2026-11-11T10:00:00-05:00",
        "ends_at": "2026-11-11T11:00:00-05:00",
        "duration_minutes": 60,
    }


def test_native_reader_is_readonly_and_uses_existing_sql_owner(tmp_path, monkeypatch):
    import live_simulations.deployed_medium as medium

    calls = []
    monkeypatch.setattr(
        medium,
        "_read",
        lambda config, query, params=(): calls.append((query, params)) or [],
    )
    reader = NativeReader(adapter(tmp_path))
    reader.rows("SELECT id FROM customers WHERE id=%s", (9,))
    with pytest.raises(SimulationError):
        reader.rows("DELETE FROM customers")
    with pytest.raises(SimulationError):
        reader.rows("SELECT 1; DELETE FROM customers")
    assert len(calls) == 1


def test_google_readonly_expiry_and_actual_rest_shape(tmp_path):
    reader = Reader()
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer offline-access"
        return httpx.Response(
            200,
            json={
                "id": "event",
                "status": "confirmed",
                "start": {"dateTime": expected()["starts_at"]},
                "end": {"dateTime": expected()["ends_at"]},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events = GoogleEvents(
            reader,
            client=client,
            staff_agent_id=4,
            decrypt=lambda encrypted: "offline-access",
        )
        assert events.get_calendar_event("primary", "event")["id"] == "event"
        reader.data["google_account"][0]["expires_at"] = 120
        with pytest.raises(SimulationError):
            events.get_calendar_event("primary", "event")
    assert calls == [("GET", "/calendar/v3/calendars/primary/events/event")]


def test_native_baseline_captures_original_ids_but_owned_service_active_scope(tmp_path):
    obj = C48Observers(
        adapter(tmp_path),
        identity={
            "run_id": "a" * 32,
            "case_id": "C48",
            "attempt": 1,
            "test_id": "test",
            "agent_id": "agent",
        },
        expected_booking=expected(),
        reader=Reader(),
    )
    baseline = obj.baseline()
    assert baseline["request_ids"] == [10] and baseline["reservation_ids"] == [20]
    assert baseline["active_request_ids"] == []
    assert baseline["original_active_request_ids"] == [10]
    assert baseline["source"] == "native_postgresql"


def test_preflight_flags_shared_phone_policy_and_unverified_units(tmp_path):
    bridge = NativeBridge(
        adapter(tmp_path), elevenlabs=SimpleNamespace(), reader=Reader()
    )
    report = bridge.preflight(["C33", "C40", "C41", "C45", "C48"])
    assert all(
        row["source_supported"] is True and row["native_ready"] is False
        for row in report.values()
    )
    assert "phone" in " ".join(report["C45"]["blockers"]).lower()
    assert "policy" in " ".join(report["C41"]["blockers"]).lower()
    assert "unit" in " ".join(report["C48"]["blockers"]).lower()


def source_observers(tmp_path):
    from live_simulations.deployed_full_recovery import prepare_source, submit_source

    value = adapter(tmp_path)
    reader = Reader()
    identity = {
        "run_id": "a" * 32,
        "case_id": "C48",
        "attempt": 1,
        "test_id": "test",
        "agent_id": "agent",
    }
    obj = C48Observers(
        value, identity=identity, expected_booking=expected(), reader=reader
    )
    prepare_source(
        tmp_path,
        identity=identity,
        expected_booking=expected(),
        tool_url="https://owned.invalid/api/v1/voice/tools?name=book_appointment",
        test_definition={
            "id": "test",
            "type": "simulation",
            "tool_mock_config": {
                "mocking_strategy": "none",
                "fallback_strategy": "call_real_tool",
                "mocked_tool_ids": [],
            },
        },
        budget={
            "source_estimate": 10,
            "recovery_estimate": 20,
            "credit_ceiling": 100,
            "remaining": 100,
        },
        observe_baseline=obj.baseline,
    )
    submit_source(
        tmp_path,
        identity=identity,
        submit=lambda request: {"id": "invocation"},
        now=lambda: 101,
    )
    reader.data["baseline_requests"].append(
        {"id": 31, "customer_id": 9, "service_type": "Oil Change", "status": "pending"}
    )
    return value, reader, obj


def test_compiled_native_booking_and_delivery_bind_existing_schema_and_journal(
    tmp_path,
):
    value, reader, obj = source_observers(tmp_path)
    booking = obj.booking()
    assert booking["requests"][0]["id"] == 31 and booking["reservations"][0]["id"] == 41
    assert value.owned_ids == {31} and 10 not in value.owned_ids
    delivery = obj.delivery()
    assert delivery["staff_calendar"]["calendar_id"] == "primary"
    assert delivery["calendar_events"][0]["provider_event_id"] == "event"
    assert delivery["notifications"][0]["booking_invocation_id"] == "invocation"
    assert delivery["notifications"][0]["attempt"] == 1
    assert delivery["notifications"][0]["status"] == "delivered"
    assert all("invocation" not in queryparams[0] for queryparams in reader.calls)


@pytest.mark.parametrize(
    "change",
    [
        "original_change",
        "foreign_customer",
        "reservation_staff",
        "missing_segment",
        "old_request",
    ],
)
def test_native_booking_never_adopts_seeded_or_wrong_native_effect(tmp_path, change):
    value, reader, obj = source_observers(tmp_path)
    if change == "original_change":
        reader.data["baseline_requests"][0]["status"] = "cancelled"
    if change == "foreign_customer":
        reader.raw[0]["customer_id"] = 99
    if change == "reservation_staff":
        reader.data["reservations"][0]["staff_agent_id"] = 5
    if change == "missing_segment":
        reader.data["segments"].pop()
    if change == "old_request":
        reader.data["baseline_requests"].pop()
    with pytest.raises(SimulationError):
        obj.booking()
    assert value.owned_ids == set()


@pytest.mark.parametrize(
    "change",
    [
        "projection_agent",
        "projection_event",
        "sms_recipient",
        "sms_retry_type",
        "google_identity",
        "not_projected",
    ],
)
def test_native_delivery_requires_exact_independent_projection_and_sms_rows(
    tmp_path, change
):
    _value, reader, obj = source_observers(tmp_path)
    if change == "projection_agent":
        reader.data["projection"][0]["payload"]["agent_id"] = 5
    if change == "projection_event":
        reader.data["projection"][0]["payload"]["calendar_event_id"] = "foreign"
    if change == "sms_recipient":
        reader.data["notifications"][0]["recipient_phone"] = "+15550000000"
    if change == "sms_retry_type":
        reader.data["notifications"][0]["retry_count"] = True
    if change == "google_identity":
        reader.data["google_account"][0]["agent_id"] = 5
    if change == "not_projected":
        reader.data["reservations"][0]["calendar_integration_status"] = (
            "PENDING_CALENDAR"
        )
    with pytest.raises(SimulationError):
        obj.delivery()


@pytest.mark.parametrize(
    "change",
    [
        "wrong_staff",
        "expired",
        "missing_scope",
        "dummy",
        "private_error",
        "wrong_event",
        "wrong_calendar",
    ],
)
def test_google_readonly_observer_fails_closed_without_refresh(tmp_path, change):
    reader = Reader()
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(
            200, json={"id": "foreign" if change == "wrong_event" else "event"}
        )

    decrypt = lambda encrypted: "dummy_test" if change == "dummy" else "offline-access"
    if change == "private_error":

        def decrypt(encrypted):
            raise SimulationError("PRIVATE TOKEN")

    if change == "wrong_staff":
        reader.data["google_account"][0]["agent_id"] = 5
    if change == "expired":
        reader.data["google_account"][0]["expires_at"] = 99
    if change == "missing_scope":
        reader.data["google_account"][0]["granted_scopes"] = "openid email"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events = GoogleEvents(reader, client=client, staff_agent_id=4, decrypt=decrypt)
        with pytest.raises(SimulationError) as error:
            events.get_calendar_event(
                "foreign" if change == "wrong_calendar" else "primary", "event"
            )
    assert "PRIVATE" not in str(error.value)
    assert set(calls) <= {"GET"}


def condition_bridge(tmp_path):
    import runpy
    from pathlib import Path

    from live_simulations.deployed_full_native import CompositeProvider

    captured = runpy.run_path(
        str(Path(__file__).with_name("test_deployed_full_conditions.py"))
    )
    native = Reader()
    conditions = captured["Reader"]()
    provider = captured["Provider"]()
    clock = [1]

    class CombinedReader:
        def rows(self, query, params=()):
            if "/* native:" in query:
                return native.rows(query, params)
            key = query.split("/* conditions:")[1].split(" */")[0]
            if (
                key
                in ("requests", "logs", "messages", "audit", "outbox", "qualifications")
                and params
                and params[0] == 0
            ):
                return []
            return conditions.rows(query, params)

        def request_rows(self, ids):
            return native.request_rows(ids)

    value = adapter(tmp_path)

    def register(ids, values):
        assert ids == [31] and values["customer_phone"] == "+14242704893"
        value.owned_ids.update(ids)
        value.current_ids.update(ids)

    value._register = register
    bridge = NativeBridge(
        value, SimpleNamespace(), reader=CombinedReader(), monotonic=lambda: clock[0]
    )
    bridge.twilio = provider
    bridge.conditions.provider = CompositeProvider(SimpleNamespace(), twilio=provider)
    return bridge, value, native, conditions, provider, clock, captured["message"]


def new_condition_request(native):
    native.data["condition_poll"] = [
        {
            "id": 31,
            "customer_id": 9,
            "staff_agent_id": 4,
            "service_type": "Oil Change",
            "customer_phone": "+14242704893",
            "confirmation_status": "pending_agent_confirmation",
            "confirmation_cutoff_at": 1100,
            "created_at": 1001,
        }
    ]


def test_condition_bridge_pre_request_baseline_precedes_new_suppression(tmp_path):
    bridge, value, native, conditions, _provider, clock, _ = condition_bridge(tmp_path)
    native.data["condition_poll"] = []
    conditions.data["staff"][0]["phone_number"] = "+15550000000"
    values = {"customer_phone": "+14242704893", "customer_name": "Owned Customer"}
    assert (
        bridge.arrange_conditions("C40", values)["status"]
        == "awaiting_owned_request_and_offer"
    )
    new_condition_request(native)
    conditions.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    conditions.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_phone": "+14242704893",
            "recipient_type": "customer",
            "status": "SKIPPED_OPT_OUT",
            "twilio_message_sid": None,
        }
    ]
    result = bridge.poll_conditions("C40", values)
    assert result["evidence_complete"] is True and result["native_ready"] is False
    assert value.owned_ids == {31}
    import json

    baseline = json.loads(
        (value.campaign.folder / "C40-1-conditions-baseline.json").read_text()
    )
    assert baseline["snapshot"]["observed_at_unix"] == 1000
    assert baseline["snapshot"]["requests"] == []
    assert (
        baseline["pre_request_sha256"]
        == value.state["full_condition_prepared"]["C40"]["sha256"]
    )


def test_condition_bridge_captures_actual_offer_before_operator_reply(tmp_path):
    bridge, _value, native, conditions, provider, clock, message = condition_bridge(
        tmp_path
    )
    values = {"customer_phone": "+14242704893", "customer_name": "Owned Customer"}
    bridge.arrange_conditions("C42", values)
    new_condition_request(native)
    native.data["condition_offer"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_type": "agent",
            "recipient_phone": "+14242704893",
            "status": "DELIVERED",
            "twilio_message_sid": "SM" + "1" * 32,
            "confirmation_status": "pending_agent_confirmation",
        }
    ]
    conditions.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    conditions.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_type": "agent",
            "recipient_phone": "+14242704893",
            "status": "DELIVERED",
            "twilio_message_sid": "SM" + "1" * 32,
        }
    ]
    provider.messages["SM" + "1" * 32] = message("SM" + "1" * 32, created=1001)
    assert bridge.poll_conditions("C42", values)["status"] == "awaiting_operator_reply"
    conditions.data["clock"][0]["observed_at_unix"] = 1002
    clock[0] = 3
    provider.messages["SM" + "2" * 32] = message(
        "SM" + "2" * 32, inbound=True, created=1002
    )
    conditions.data["messages"] = [
        {
            "id": 60,
            "appointment_id": 31,
            "customer_phone": "+14242704893",
            "direction": "inbound",
            "body": "CONFIRM #31",
            "twilio_message_sid": "SM" + "2" * 32,
            "created_at": 1002,
        }
    ]
    conditions.data["audit"] = [
        {
            "id": 70,
            "request_id": 31,
            "event_type": "AGENT_CONFIRMED",
            "agent_id": 4,
            "phone": "+14242704893",
            "reply": "CONFIRM #31",
            "created_at": 1002,
        }
    ]
    conditions.data["requests"][0]["confirmation_status"] = "confirmed"
    assert bridge.observe_conditions("C42", values)["evidence_complete"] is True


def test_condition_bridge_never_retrofits_baseline_after_reply(tmp_path):
    bridge, value, native, _conditions, _provider, _clock, _message = condition_bridge(
        tmp_path
    )
    values = {"customer_phone": "+14242704893", "customer_name": "Owned Customer"}
    bridge.arrange_conditions("C42", values)
    new_condition_request(native)
    native.data["condition_offer"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "status": "DELIVERED",
            "twilio_message_sid": "SM" + "1" * 32,
            "confirmation_status": "confirmed",
        }
    ]
    with pytest.raises(SimulationError, match="preceded"):
        bridge.poll_conditions("C42", values)
    assert not (value.campaign.folder / "C42-1-conditions-baseline.json").exists()


def test_condition_poll_without_pre_request_journal_is_blocked(tmp_path):
    bridge, _value, native, _conditions, _provider, _clock, _message = condition_bridge(
        tmp_path
    )
    new_condition_request(native)
    with pytest.raises(SimulationError, match="precede"):
        bridge.poll_conditions("C40", {"customer_phone": "+14242704893"})


def test_native_registration_cannot_overwrite_coordinator_manifest_binding(tmp_path):
    value, _reader, obj = source_observers(tmp_path)
    value._save = lambda: private_json(
        value.campaign.folder / "manifest.json", value.campaign.manifest
    )
    obj.booking()
    assert obj.delivery()["notifications"][0]["booking_invocation_id"] == "invocation"


def test_google_permission_probe_uses_metadata_get_without_refresh_or_event_bodies(
    tmp_path,
):
    reader = Reader()
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, str(request.url.query)))
        assert request.url.params["fields"] == "kind,accessRole"
        return httpx.Response(
            200, json={"kind": "calendar#events", "accessRole": "owner"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        observed = GoogleEvents(
            reader, client=client, staff_agent_id=4, decrypt=lambda _: "offline-access"
        ).permissions()
    assert observed["read"] is True and observed["write"] is True
    assert all(method == "GET" for method, _, _ in calls)


def test_readonly_google_token_cannot_claim_booking_write_permission(tmp_path):
    reader = Reader()
    reader.data["google_account"][0]["granted_scopes"] = (
        "https://www.googleapis.com/auth/calendar.events.readonly"
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"kind": "calendar#events", "accessRole": "owner"}
            )
        )
    ) as client:
        result = GoogleEvents(
            reader, client=client, staff_agent_id=4, decrypt=lambda _: "offline-access"
        ).permissions()
    assert result["write"] is False


def test_mechanism_preflight_get_auth_and_allowlists_are_native_not_config_receipts(
    tmp_path,
):
    from live_simulations.core import fingerprint

    value = adapter(tmp_path)
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer offline-cron"
        return httpx.Response(
            200,
            json={
                "success": True,
                "enabled": True,
                "capability": "owned-faults-v1",
                "schema_ready": True,
                "modes": ["calendar_reject"],
                "allowlisted_technician_ids": [4, 5],
                "allowlisted_phone_fingerprints": [fingerprint("+14242704893")],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        value.client = client
        bridge = NativeBridge(
            value,
            SimpleNamespace(),
            reader=Reader(),
            capability_headers={"Authorization": "Bearer offline-cron"},
        )
        assert bridge.fault_capabilities()["enabled"] is True
    assert calls == [("GET", "/api/v1/portal/internal/simulation-faults")]


def test_disabled_native_mechanism_cannot_be_enabled_by_supplied_config(tmp_path):
    value = adapter(tmp_path)
    value.config["capabilities"] = {"ready": True, "enabled": True}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "success": True,
                    "enabled": False,
                    "capability": "owned-staff-v1",
                },
            )
        )
    ) as client:
        value.client = client
        bridge = NativeBridge(
            value,
            SimpleNamespace(),
            reader=Reader(),
            capability_headers={"Authorization": "Bearer offline-cron"},
        )
        with pytest.raises(SimulationError):
            bridge.staff_capabilities()


def test_c50_callback_preflight_reads_authenticated_native_capability(tmp_path):
    value = adapter(tmp_path)
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "success": True,
                "enabled": True,
                "capability": "owned-session-v1",
                "audit_schema_ready": True,
                "hmac_configured": True,
                "verification_bypass_active": False,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        value.client = client
        bridge = NativeBridge(
            value,
            SimpleNamespace(),
            reader=Reader(),
            capability_headers={"Authorization": "Bearer offline-cron"},
        )
        assert bridge.session_capabilities()["audit_schema_ready"] is True
        report = bridge.preflight(["C50"])["C50"]
    assert report["source_supported"] is True
    assert not any("callback" in blocker for blocker in report["blockers"])
    assert any("unit" in blocker for blocker in report["blockers"])
    assert all(
        method == "GET"
        and path == "/api/v1/portal/internal/simulation-session-capabilities"
        for method, path in calls
    )


@pytest.mark.parametrize("key", ["audit_schema_ready", "hmac_configured"])
def test_c50_callback_preflight_cannot_accept_missing_native_auth_or_audit(
    tmp_path, key
):
    value = adapter(tmp_path)
    result = {
        "success": True,
        "enabled": True,
        "capability": "owned-session-v1",
        "audit_schema_ready": True,
        "hmac_configured": True,
        "verification_bypass_active": False,
    }
    result[key] = False
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result))
    ) as client:
        value.client = client
        bridge = NativeBridge(
            value,
            SimpleNamespace(),
            reader=Reader(),
            capability_headers={"Authorization": "Bearer offline-cron"},
        )
        with pytest.raises(SimulationError):
            bridge.session_capabilities()


def test_c39_preflight_reads_actual_provider_latest_whatsapp_window(tmp_path):
    value = adapter(tmp_path)
    reader = Reader()
    reader.data["clock"] = [{"now_unix": 200000}]
    account = "AC" + "a" * 32
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/Messages.json"):
            assert request.url.params["From"] == "whatsapp:+14242704893"
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {
                            "sid": "SM" + "1" * 32,
                            "account_sid": account,
                            "direction": "inbound",
                            "from": "whatsapp:+14242704893",
                            "date_created": "1970-01-02T03:46:40+00:00",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"sid": account, "status": "active"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        bridge = NativeBridge(
            value,
            SimpleNamespace(),
            reader=reader,
            twilio_client=client,
            twilio_account_sid=account,
            twilio_auth=("offline", "offline"),
        )
        report = bridge.preflight(["C39"])["C39"]
    assert not any("window" in blocker for blocker in report["blockers"])
    assert all(method == "GET" for method, _ in calls)


def test_c50_testing_verification_bypass_is_never_native_auth_proof(tmp_path):
    value = adapter(tmp_path)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "success": True,
                    "enabled": True,
                    "capability": "owned-session-v1",
                    "audit_schema_ready": True,
                    "hmac_configured": True,
                    "verification_bypass_active": True,
                },
            )
        )
    ) as client:
        value.client = client
        bridge = NativeBridge(
            value,
            SimpleNamespace(),
            reader=Reader(),
            capability_headers={"Authorization": "Bearer offline-cron"},
        )
        with pytest.raises(SimulationError):
            bridge.session_capabilities()


def test_c50_good_history_and_booking_cannot_complete_without_actual_whatsapp(tmp_path):
    value = adapter(tmp_path)
    reader = Reader()
    value.owned_ids = {31}
    value.current_ids = {31}
    bridge = NativeBridge(value, SimpleNamespace(), reader=reader)
    report = bridge.c50_delivery(
        expected_booking=expected(), request_id=31, conversation_id="actual-session"
    )
    assert report["evidence_complete"] is False
    assert report["native_inbox_receiving"] == "unverified"


def c50_fixture(tmp_path, monkeypatch, *, whatsapp=True):
    import json

    import live_simulations.deployed_medium as medium
    from live_simulations.core import fingerprint

    value = adapter(tmp_path)
    reader = Reader()
    value.owned_ids = {31}
    value.current_ids = {31}
    auth = {
        "authorization_id": "auth",
        "tier": "full",
        "case_ids": [f"C{i:02}" for i in range(17, 51)],
        "credit_ceiling": 1000,
    }
    value.campaign.manifest["stage_authorization"] = auth
    baseline = {
        "run_id": "a" * 32,
        "case_id": "C50",
        "agent_id": "agent",
        "customer_id": 9,
        "customer_phone": "+14242704893",
        "customer_name": "Owned Customer",
        "baseline_note_ids": [],
        "baseline_event_ids": [],
    }
    value.state["full_history"] = baseline
    dynamic = {"run_id": "a" * 32, "case_id": "C50", "session_nonce": "b" * 32}
    intent = {
        "schema_version": 1,
        "run_id": "a" * 32,
        "case_id": "C50",
        "agent_id": "agent",
        "authorization_id": "auth",
        "session_nonce": "b" * 32,
        "dynamic_variables": dynamic,
        "baseline": baseline,
        "script_sha256": "f" * 64,
    }
    private_json(value.campaign.folder / "C50-native-session-intent.json", intent)
    entry = {
        k: intent[k]
        for k in ("run_id", "case_id", "agent_id", "authorization_id", "session_nonce")
    }
    entry.update(
        resource_type="conversation",
        unsettled=False,
        credits="17",
        intent_sha256=fingerprint(intent),
        provider_conversation_id="actual-session",
        billing_id="conversation:actual-session",
        submission_unknown=False,
    )
    private_json(
        tmp_path / "usage-ledger.json",
        {"entries": [entry], "stage_authorizations": [{**auth, "run_id": "a" * 32}]},
    )

    def native_customer(config, query, params=()):
        assert (
            query == "SELECT id,name,phone FROM customers WHERE id=%s"
            and params == (9,)
        )
        return [{"id": 9, "name": "Owned Customer", "phone": "+14242704893"}]

    monkeypatch.setattr(medium, "_read", native_customer)
    call = {
        "type": "webhook",
        "request_id": "native-booking",
        "tool_name": "book_appointment",
        "tool_has_been_called": True,
        "tool_details": {
            "type": "webhook",
            "method": "POST",
            "url": "https://owned.invalid/api/v1/voice/tools?name=book_appointment",
        },
        "params_as_json": json.dumps(
            {"service_type": "Oil Change", "phone": "+14242704893"}
        ),
    }
    result = {
        "tool_name": "book_appointment",
        "request_id": "native-booking",
        "is_error": False,
        "result_value": json.dumps(
            {
                "result": {
                    "success": True,
                    "appointment_id": 31,
                    "appointments": [{"service_request_id": 31, "reservation_id": 41}],
                }
            }
        ),
    }
    turns = [
        {
            "role": "user",
            "message": "Please book the exact confirmed Oil Change appointment.",
        },
        {"role": "agent", "message": None, "tool_calls": [call]},
        {
            "role": "agent",
            "message": "Your appointment is saved.",
            "tool_results": [result],
        },
    ]
    detail = {
        "conversation_id": "actual-session",
        "agent_id": "agent",
        "status": "done",
        "user_id": baseline["customer_phone"],
        "conversation_initiation_client_data": {
            "dynamic_variables": dynamic,
            "user_id": baseline["customer_phone"],
        },
        "transcript": turns,
    }

    class Provider:
        def request(self, method, path):
            assert method == "GET" and path == "/v1/convai/conversations/actual-session"
            return copy.deepcopy(detail)

    reader.data["c50_notes"] = [
        {
            "id": 71,
            "call_id": "actual-session",
            "customer_id": 9,
            "transcript": "\n".join(
                f"{'User' if turn['role'] == 'user' else 'Agent'}: {turn.get('message', '')}"
                for turn in turns
            ),
        }
    ]
    reader.data["c50_events"] = [
        {
            "id": 81,
            "provider": "elevenlabs",
            "event_id": "actual-session",
            "payload_hash": "f" * 64,
            "status": "COMPLETED",
            "completed_at": "2026-11-11T15:05:00+00:00",
        }
    ]
    reader.data["c50_audit"] = [
        {
            "provider": "elevenlabs",
            "event_id": "actual-session",
            "conversation_id": "actual-session",
            "payload_hash": "f" * 64,
            "verified_at": "2026-11-11T15:04:00+00:00",
        }
    ]
    reader.data["c50_notifications"] = (
        [
            {
                "id": 61,
                "appointment_id": 31,
                "recipient_type": "customer",
                "recipient_phone": "+14242704893",
                "channel": "WHATSAPP",
                "status": "DELIVERED",
                "retry_count": 0,
                "twilio_message_sid": "SM" + "1" * 32,
                "created_at": "2026-11-11T15:00:00+00:00",
            }
        ]
        if whatsapp
        else []
    )
    account = "AC" + "a" * 32
    calls = []
    changes = {}

    def handler(request):
        calls.append((request.method, request.url.host, request.url.path))
        if request.url.host == "www.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "id": "event",
                    "status": "confirmed",
                    "start": {
                        "dateTime": changes.get("google_start", expected()["starts_at"])
                    },
                    "end": {"dateTime": expected()["ends_at"]},
                },
            )
        if request.url.path.endswith("/" + account + ".json"):
            return httpx.Response(200, json={"sid": account, "status": "active"})
        return httpx.Response(
            200,
            json={
                "sid": "SM" + "1" * 32,
                "account_sid": account,
                "status": changes.get("message_status", "delivered"),
                "direction": "outbound-api",
                "to": changes.get("message_to", "whatsapp:+14242704893"),
                "date_created": changes.get(
                    "message_created", "2026-11-11T15:00:01+00:00"
                ),
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bridge = NativeBridge(
        value,
        Provider(),
        reader=reader,
        google_client=client,
        twilio_client=client,
        twilio_account_sid=account,
        twilio_auth=("offline", "offline"),
        decrypt=lambda _: "offline-access",
    )
    return bridge, reader, detail, calls, changes, client


def test_c50_actual_history_booking_google_and_whatsapp_are_joined(
    tmp_path, monkeypatch
):
    bridge, _reader, _detail, calls, _changes, client = c50_fixture(tmp_path, monkeypatch)
    try:
        report = bridge.c50_delivery(
            expected_booking=expected(), request_id=31, conversation_id="actual-session"
        )
    finally:
        client.close()
    assert report["evidence_complete"] is True
    assert report["provider_conversation_id"] == "actual-session"
    assert report["native_inbox_receiving"] == "unverified"
    assert all(method == "GET" for method, host, path in calls)
    assert any(host == "www.googleapis.com" for method, host, path in calls)
    assert any(host == "api.twilio.com" for method, host, path in calls)


def test_c50_real_history_good_booking_and_google_without_whatsapp_is_incomplete(
    tmp_path, monkeypatch
):
    bridge, _reader, _detail, _calls, _changes, client = c50_fixture(
        tmp_path, monkeypatch, whatsapp=False
    )
    try:
        report = bridge.c50_delivery(
            expected_booking=expected(), request_id=31, conversation_id="actual-session"
        )
    finally:
        client.close()
    assert report["evidence_complete"] is False
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert failed == ["exact C50 owned customer WhatsApp attempt"]
    assert all(check["passed"] for check in report["checks"][:-1])


@pytest.mark.parametrize(
    "change",
    [
        "google_missing",
        "google_time",
        "twilio_missing",
        "not_delivered",
        "wrong_recipient",
        "stale_message",
        "wrong_cid",
        "wrong_booking_result",
        "wrong_audit",
    ],
)
def test_c50_partial_or_unrelated_external_evidence_cannot_complete(
    tmp_path, monkeypatch, change
):
    bridge, reader, detail, _calls, changes, client = c50_fixture(tmp_path, monkeypatch)
    if change == "google_missing":
        bridge.google_client = None
    if change == "google_time":
        changes["google_start"] = "2026-11-12T10:00:00-05:00"
    if change == "twilio_missing":
        bridge.twilio = None
    if change == "not_delivered":
        changes["message_status"] = "sent"
    if change == "wrong_recipient":
        changes["message_to"] = "whatsapp:+15550000000"
    if change == "stale_message":
        changes["message_created"] = "2026-11-10T15:00:00+00:00"
    if change == "wrong_cid":
        detail["conversation_id"] = "foreign"
    if change == "wrong_booking_result":
        import json

        value = json.loads(detail["transcript"][-1]["tool_results"][0]["result_value"])
        value["result"]["appointment_id"] = 99
        detail["transcript"][-1]["tool_results"][0]["result_value"] = json.dumps(value)
    if change == "wrong_audit":
        reader.data["c50_audit"][0]["payload_hash"] = "a" * 64
    try:
        report = bridge.c50_delivery(
            expected_booking=expected(), request_id=31, conversation_id="actual-session"
        )
    finally:
        client.close()
    assert report["evidence_complete"] is False
    assert report["native_inbox_receiving"] == "unverified"


def test_c50_account_preflight_observes_fresh_quota_and_pinned_tier(tmp_path):
    value = adapter(tmp_path)
    value.config['budget'] = {'verified_credit_units': True,
        'native_session_credit_units_verified': True,
        'native_session_credit_subscription_tier': 'legacy-test',
        'monthly_credits': 1000, 'reset_unix': 4000000000, 'case_estimates': {'C50': 10}}
    subscription = {'tier': 'legacy-test', 'status': 'active',
        'character_count': 10, 'character_limit': 1000,
        'character_refresh_period': 'monthly_period', 'next_character_count_reset_unix': 4000000000}
    reads = []
    def observe_subscription():
        reads.append(True)
        return dict(subscription)
    bridge = NativeBridge(value, SimpleNamespace(subscription=observe_subscription), reader=Reader())
    bridge.session_capabilities = lambda: {'audit_schema_ready': True}
    first = bridge.preflight(['C50'])['C50']
    assert not any('credit' in blocker for blocker in first['blockers'])
    subscription['tier'] = 'different-minute-plan'
    second = bridge.preflight(['C50'])['C50']
    assert any('credit' in blocker for blocker in second['blockers'])
    assert len(reads) == 2
