"""Captured read-only condition contracts; no native recipient or elapsed proof."""

import copy

import pytest

from live_simulations.core import SimulationError
from live_simulations.deployed_full_conditions import Conditions, Identity


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    yield


class Reader:
    def __init__(self):
        self.calls = []
        self.data = {
            "clock": [{"observed_at_unix": 1000}],
            "customers": [{"id": 9, "phone": "+14242704893", "sms_opt_in": False}],
            "requests": [
                {
                    "id": 31,
                    "customer_id": 9,
                    "staff_agent_id": 4,
                    "status": "pending",
                    "service_type": "Oil Change",
                    "confirmation_status": "pending_agent_confirmation",
                    "escalation_status": "none",
                    "confirmation_cutoff_at": 1100,
                }
            ],
            "staff": [{"id": 4, "phone_number": "+14242704893", "is_active": True}],
            "whitelist": [{"phone_number": "+14242704893", "whatsapp_onboarded": True}],
            "logs": [],
            "messages": [],
            "audit": [],
            "outbox": [],
            "policy": [
                {
                    "quiet_hours_enabled": True,
                    "quiet_start_time": "21:00",
                    "quiet_end_time": "08:00",
                }
            ],
            "qualifications": [],
        }

    def rows(self, query, params):
        assert query.lstrip().upper().startswith("SELECT")
        key = query.split("/* conditions:")[1].split(" */")[0]
        self.calls.append((key, params))
        return copy.deepcopy(self.data[key])


class Provider:
    def __init__(self):
        self.messages = {}
        self.calls = []

    def get_message(self, sid):
        self.calls.append(sid)
        return copy.deepcopy(self.messages[sid])


def identity(cid="C40"):
    return Identity(
        run_id="a" * 32,
        case_id=cid,
        attempt=1,
        customer_id=9,
        request_id=31,
        staff_agent_id=4,
    )


def observer(tmp_path, cid="C40"):
    reader = Reader()
    provider = Provider()
    clock = [1]
    obj = Conditions(
        tmp_path, reader=reader, provider=provider, monotonic=lambda: clock[0]
    )
    return obj, reader, provider, clock, identity(cid)


def test_new_native_opt_out_suppression_after_journalled_baseline(tmp_path):
    obj, reader, provider, clock, binding = observer(tmp_path)
    reader.data["staff"][0]["phone_number"] = "+15550000000"
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_phone": "+14242704893",
            "recipient_type": "customer",
            "status": "SKIPPED_OPT_OUT",
            "twilio_message_sid": None,
        }
    ]
    result = obj.observe(binding)
    assert result["source_supported"] is True and result["evidence_complete"] is True
    assert result["native_ready"] is False
    assert provider.calls == []


@pytest.mark.parametrize("change", ["seeded", "opted_in", "sent", "foreign"])
def test_optout_receipt_or_seed_cannot_establish_suppression(tmp_path, change):
    obj, reader, _provider, clock, binding = observer(tmp_path)
    log = {
        "id": 50,
        "appointment_id": 31,
        "recipient_phone": "+14242704893",
        "recipient_type": "customer",
        "status": "SKIPPED_OPT_OUT",
        "twilio_message_sid": None,
    }
    if change == "seeded":
        reader.data["logs"] = [log]
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    reader.data["logs"] = [log]
    if change == "opted_in":
        reader.data["customers"][0]["sms_opt_in"] = True
    if change == "sent":
        log["status"] = "SENT"
        log["twilio_message_sid"] = "SM" + "1" * 32
    if change == "foreign":
        log["appointment_id"] = 999
    assert obj.observe(binding)["evidence_complete"] is False


def test_same_handset_does_not_establish_distinct_customer(tmp_path):
    obj, _reader, _provider, _clock, binding = observer(tmp_path, "C33")
    obj.arrange(binding)
    result = obj.observe(binding)
    assert result["evidence_complete"] is False
    assert result["source_supported"] is True


def test_backwards_native_or_monotonic_clock_blocks(tmp_path):
    obj, _reader, _provider, clock, binding = observer(tmp_path)
    obj.arrange(binding)
    clock[0] = 0
    with pytest.raises(SimulationError, match="clock"):
        obj.observe(binding)


def test_config_ready_receipts_are_not_accepted(tmp_path):
    with pytest.raises(TypeError):
        Conditions(
            tmp_path,
            reader={"ready": True},
            provider=Provider(),
            receipt={"ready": True},
        )


def message(
    sid,
    *,
    inbound=False,
    phone="+14242704893",
    created=1001,
    status="delivered",
    code=None,
    body="CONFIRM #31",
):
    return {
        "sid": sid,
        "status": status,
        "direction": "inbound" if inbound else "outbound-api",
        "from": phone if inbound else "+15551234567",
        "to": "+15551234567" if inbound else phone,
        "date_created": created,
        "date_sent": created,
        "error_code": code,
        "body": body,
    }


@pytest.mark.parametrize("cid,code", [("C38", 63015), ("C39", 63016)])
def test_provider_bound_unenrolled_and_closed_window_rejection(tmp_path, cid, code):
    obj, reader, provider, clock, binding = observer(tmp_path, cid)
    if cid == "C38":
        reader.data["whitelist"][0]["whatsapp_onboarded"] = False
    if cid == "C39":
        reader.data["clock"][0]["observed_at_unix"] = 200000
        sid = "SM" + "2" * 32
        reader.data["messages"] = [
            {
                "id": 60,
                "appointment_id": 31,
                "customer_phone": "+14242704893",
                "direction": "inbound",
                "body": "Hello",
                "twilio_message_sid": sid,
                "created_at": 100000,
            }
        ]
        provider.messages[sid] = message(
            sid, inbound=True, created=100000, body="Hello"
        )
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] += 1
    clock[0] = 2
    sid = "SM" + "1" * 32
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_phone": "+14242704893",
            "recipient_type": "customer",
            "status": "FAILED",
            "twilio_message_sid": sid,
        }
    ]
    provider.messages[sid] = message(
        sid,
        status="failed",
        code=code,
        created=reader.data["clock"][0]["observed_at_unix"],
    )
    assert obj.observe(binding)["evidence_complete"] is True
    assert all(s.startswith("SM") for s in provider.calls)


@pytest.mark.parametrize(
    "change",
    ["wrong_sid", "wrong_recipient", "enrolled", "wrong_code", "private_error"],
)
def test_provider_receipt_identity_and_native_enrollment_must_match(tmp_path, change):
    obj, reader, provider, clock, binding = observer(tmp_path, "C38")
    reader.data["whitelist"][0]["whatsapp_onboarded"] = False
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    sid = "SM" + "1" * 32
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_phone": "+14242704893",
            "recipient_type": "customer",
            "status": "FAILED",
            "twilio_message_sid": sid,
        }
    ]
    provider.messages[sid] = message(sid, status="failed", code=63015)
    if change == "wrong_sid":
        provider.messages[sid]["sid"] = "SM" + "3" * 32
    if change == "wrong_recipient":
        provider.messages[sid]["to"] = "+15550000000"
    if change == "enrolled":
        reader.data["whitelist"][0]["whatsapp_onboarded"] = True
    if change == "wrong_code":
        provider.messages[sid]["error_code"] = 63016
    if change == "private_error":

        def error(sid):
            raise SimulationError("PRIVATE TOKEN")

        provider.get_message = error
    result = obj.observe(binding)
    assert result["evidence_complete"] is False
    assert "PRIVATE" not in str(result)


def staff_observer(tmp_path, cid="C42", *, seeded_audit=False):
    obj, reader, provider, clock, binding = observer(tmp_path, cid)
    reader.data["customers"][0]["sms_opt_in"] = True
    sid = "SM" + "1" * 32
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_type": "agent",
            "recipient_phone": "+14242704893",
            "status": "DELIVERED",
            "twilio_message_sid": sid,
        }
    ]
    provider.messages[sid] = message(sid, created=999)
    if seeded_audit:
        reader.data["audit"] = [
            {
                "id": 70,
                "request_id": 31,
                "event_type": "AGENT_CONFIRMED",
                "triggered_by": "agent_sms",
                "agent_id": 4,
                "phone": "+14242704893",
                "reply": "CONFIRM #31",
                "created_at": 999,
            }
        ]
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    reply_sid = "SM" + "2" * 32
    body = "DECLINE #31" if cid == "C43" else "CONFIRM #31"
    reader.data["messages"] = [
        {
            "id": 60,
            "appointment_id": 31,
            "direction": "inbound",
            "customer_phone": "+14242704893",
            "body": body,
            "twilio_message_sid": reply_sid,
            "created_at": 1001,
        }
    ]
    provider.messages[reply_sid] = message(reply_sid, inbound=True, body=body)
    reader.data["audit"] = [
        {
            "id": 70,
            "request_id": 31,
            "event_type": "AGENT_DECLINED" if cid == "C43" else "AGENT_CONFIRMED",
            "triggered_by": "agent_sms",
            "agent_id": 4,
            "phone": "+14242704893",
            "reply": body,
            "created_at": 1001,
        }
    ]
    reader.data["requests"][0]["confirmation_status"] = "confirmed"
    return obj, reader, provider, clock, binding


def test_staff_confirmation_joins_offer_real_inbound_and_native_audit(tmp_path):
    obj, _reader, provider, _clock, binding = staff_observer(tmp_path)
    assert obj.observe(binding)["evidence_complete"] is True
    assert len(set(provider.calls)) == 2


@pytest.mark.parametrize(
    "change",
    [
        "foreign_sender",
        "wrong_target",
        "audit_reply",
        "provider_body",
        "old_reply",
        "new_assignment",
        "missing_offer",
    ],
)
def test_staff_response_cannot_be_seeded_or_relabelled(tmp_path, change):
    obj, reader, provider, _clock, binding = staff_observer(tmp_path)
    if change == "foreign_sender":
        provider.messages["SM" + "2" * 32]["from"] = "+15550000000"
    if change == "wrong_target":
        reader.data["messages"][0]["body"] = "CONFIRM #99"
    if change == "audit_reply":
        reader.data["audit"][0]["reply"] = "CONFIRM #99"
    if change == "provider_body":
        provider.messages["SM" + "2" * 32]["body"] = "DECLINE #31"
    if change == "old_reply":
        provider.messages["SM" + "2" * 32]["date_created"] = 999
    if change == "new_assignment":
        reader.data["requests"][0]["staff_agent_id"] = 5
    if change == "missing_offer":
        reader.data["logs"] = []
    result = obj.observe(binding)
    assert result["evidence_complete"] is False


def test_actual_timeout_requires_native_and_monotonic_elapsed_boundary(tmp_path):
    obj, reader, _provider, clock, binding = observer(tmp_path, "C44")
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1101
    clock[0] = 102
    reader.data["requests"][0].update(
        escalation_status="escalated", escalation_reason="TIMEOUT_NO_RESPONSE"
    )
    reader.data["audit"] = [
        {
            "id": 70,
            "request_id": 31,
            "event_type": "ESCALATION_TRIGGERED",
            "created_at": 1101,
        }
    ]
    result = obj.observe(binding)
    assert result["evidence_complete"] is False  # no actual provider-backed staff offer


def test_quiet_hours_voice_bypass_remains_operational_blocker(tmp_path):
    obj, reader, _provider, _clock, binding = observer(tmp_path, "C41")
    reader.data["outbox"] = [
        {
            "id": 1,
            "request_id": 31,
            "payload": {"triggered_by": "voice_agent", "bypass_quiet_hours": True},
        }
    ]
    obj.arrange(binding)
    assert "policy" in " ".join(obj.observe(binding)["blockers"])


def test_shared_staff_phone_does_not_prove_isolated_customer_optout(tmp_path):
    obj, reader, _provider, clock, binding = observer(tmp_path)
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_phone": "+14242704893",
            "recipient_type": "customer",
            "status": "SKIPPED_OPT_OUT",
            "twilio_message_sid": None,
        }
    ]
    assert obj.observe(binding)["evidence_complete"] is False


def test_real_timeout_captured_contract_has_exact_offer_and_escalation(tmp_path):
    obj, reader, provider, clock, binding = observer(tmp_path, "C44")
    sid = "SM" + "1" * 32
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_type": "agent",
            "recipient_phone": "+14242704893",
            "status": "DELIVERED",
            "twilio_message_sid": sid,
        }
    ]
    provider.messages[sid] = message(sid, created=999)
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1101
    clock[0] = 102
    reader.data["requests"][0].update(
        escalation_status="escalated", escalation_reason="TIMEOUT_NO_RESPONSE"
    )
    reader.data["audit"] = [
        {
            "id": 70,
            "request_id": 31,
            "event_type": "ESCALATION_TRIGGERED",
            "created_at": 1101,
        }
    ]
    assert obj.observe(binding)["evidence_complete"] is True


@pytest.mark.parametrize("cid", ["C43", "C45"])
def test_distinct_replacement_and_original_sender_captured_contract(tmp_path, cid):
    from dataclasses import replace

    obj, reader, provider, clock, binding = observer(tmp_path, cid)
    binding = replace(binding, original_staff_agent_id=4, replacement_staff_agent_id=5)
    reader.data["staff"].append(
        {"id": 5, "phone_number": "+15550000000", "is_active": True}
    )
    reader.data["qualifications"] = [
        {"staff_agent_id": 5, "service_name": "Oil Change", "is_active": True}
    ]
    if cid == "C45":
        reader.data["requests"][0].update(
            staff_agent_id=5, confirmation_status="confirmed"
        )
    sid = "SM" + "1" * 32
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_type": "agent",
            "recipient_phone": "+14242704893",
            "status": "DELIVERED",
            "twilio_message_sid": sid,
        }
    ]
    provider.messages[sid] = message(sid, created=999)
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    reply_sid = "SM" + "2" * 32
    body = "DECLINE #31" if cid == "C43" else "CONFIRM #31"
    provider.messages[reply_sid] = message(reply_sid, inbound=True, body=body)
    reader.data["messages"] = [
        {
            "id": 60,
            "appointment_id": 31,
            "direction": "inbound",
            "customer_phone": "+14242704893",
            "body": body,
            "twilio_message_sid": reply_sid,
            "created_at": 1001,
        }
    ]
    reader.data["audit"] = [
        {
            "id": 70,
            "request_id": 31,
            "event_type": "AGENT_DECLINED"
            if cid == "C43"
            else "AGENT_CONFIRM_REJECTED",
            "agent_id": 4,
            "phone": "+14242704893",
            "reply": body,
            "created_at": 1001,
        }
    ]
    if cid == "C43":
        reader.data["requests"][0].update(staff_agent_id=5)
    assert obj.observe(binding)["evidence_complete"] is True


def test_quiet_queue_release_source_check_preserves_policy_blocker(tmp_path):
    obj, reader, provider, clock, binding = observer(tmp_path, "C41")
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_type": "customer",
            "recipient_phone": "+14242704893",
            "status": "QUEUED",
            "twilio_message_sid": None,
            "scheduled_send_at": 1010,
        }
    ]
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1011
    clock[0] = 12
    sid = "SM" + "1" * 32
    reader.data["logs"][0].update(status="DELIVERED", twilio_message_sid=sid)
    provider.messages[sid] = message(sid, created=1010)
    result = obj.observe(binding)
    assert result["blockers"] == [
        "Voice/customer quiet-hours bypass policy requires owner decision"
    ]
    assert result["native_ready"] is False


def test_native_journal_hashes_private_message_and_phone(tmp_path):
    obj, _reader, _provider, _clock, binding = staff_observer(tmp_path)
    obj.observe(binding)
    text = "".join(
        path.read_text() for path in (tmp_path / binding.run_id).glob("*.json")
    )
    assert "+14242704893" not in text
    assert "CONFIRM #31" not in text
    assert "body_sha256" in text


def test_twilio_transport_has_exact_account_sid_and_only_get(tmp_path):
    import httpx

    from live_simulations.deployed_full_conditions import TwilioMessages

    account = "AC" + "a" * 32
    sid = "SM" + "b" * 32
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=message(sid) | {"account_sid": account})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = TwilioMessages(account, client=client, auth=("offline", "offline"))
        assert transport.get_message(sid)["sid"] == sid
    assert calls == [("GET", f"/2010-04-01/Accounts/{account}/Messages/{sid}.json")]


def test_distinct_native_customer_condition_preserves_other_owner(tmp_path):
    from dataclasses import replace

    obj, reader, _provider, _clock, binding = observer(tmp_path, "C33")
    binding = replace(binding, other_customer_id=10)
    reader.data["customers"].append(
        {"id": 10, "phone": "+15550000000", "sms_opt_in": True}
    )
    reader.data["requests"][0]["customer_id"] = 10
    obj.arrange(binding)
    assert obj.observe(binding)["evidence_complete"] is True


def test_actual_twilio_rfc_date_shape_is_supported():
    from live_simulations.deployed_full_conditions import _timestamp

    assert _timestamp("Wed, 11 Nov 2026 15:00:00 +0000") == _timestamp(
        "2026-11-11T15:00:00+00:00"
    )


def test_twilio_foreign_account_and_private_failure_are_sanitized():
    import httpx

    from live_simulations.deployed_full_conditions import TwilioMessages

    account = "AC" + "a" * 32
    sid = "SM" + "b" * 32
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=message(sid)
                | {"account_sid": "AC" + "c" * 32, "private": "PRIVATE TOKEN"},
            )
        )
    ) as client:
        transport = TwilioMessages(account, client=client, auth=("offline", "offline"))
        with pytest.raises(SimulationError) as error:
            transport.get_message(sid)
        assert "PRIVATE" not in str(error.value)


def test_seeded_staff_audit_cannot_prove_new_native_transition(tmp_path):
    obj, _reader, _provider, _clock, binding = staff_observer(
        tmp_path, seeded_audit=True
    )
    assert obj.observe(binding)["evidence_complete"] is False


def test_staff_reply_after_offer_deadline_is_not_ordinary_confirmation(tmp_path):
    obj, reader, provider, clock, binding = staff_observer(tmp_path)
    provider.messages["SM" + "2" * 32]["date_created"] = 1101
    reader.data["clock"][0]["observed_at_unix"] = 1102
    clock[0] = 103
    assert obj.observe(binding)["evidence_complete"] is False


@pytest.mark.parametrize(
    "value", ["4242704893", "14242704893", "(424) 270-4893", "whatsapp:+14242704893"]
)
def test_native_nanp_storage_canonicalizes_to_provider_e164(value):
    from live_simulations.deployed_full_conditions import _phone

    assert _phone(value) == _phone("+14242704893")


def test_c37_actual_owned_provider_rejection_is_not_a_configured_fault(tmp_path):
    obj, reader, provider, clock, binding = observer(tmp_path, "C37")
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    sid = "SM" + "1" * 32
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_phone": "+14242704893",
            "recipient_type": "customer",
            "status": "FAILED",
            "error_code": "63015",
            "twilio_message_sid": sid,
        }
    ]
    provider.messages[sid] = message(sid, status="failed", code=63015)
    assert obj.observe(binding)["evidence_complete"] is True


@pytest.mark.parametrize(
    "change", ["wrong_error", "sent", "foreign_recipient", "cancelled_booking"]
)
def test_c37_rejection_requires_matching_actual_native_and_provider_effect(
    tmp_path, change
):
    obj, reader, provider, clock, binding = observer(tmp_path, "C37")
    obj.arrange(binding)
    reader.data["clock"][0]["observed_at_unix"] = 1001
    clock[0] = 2
    sid = "SM" + "1" * 32
    reader.data["logs"] = [
        {
            "id": 50,
            "appointment_id": 31,
            "recipient_phone": "+14242704893",
            "recipient_type": "customer",
            "status": "FAILED",
            "error_code": "63015",
            "twilio_message_sid": sid,
        }
    ]
    provider.messages[sid] = message(sid, status="failed", code=63015)
    if change == "wrong_error":
        provider.messages[sid]["error_code"] = 63016
    if change == "sent":
        provider.messages[sid]["status"] = "delivered"
    if change == "foreign_recipient":
        provider.messages[sid]["to"] = "+15550000000"
    if change == "cancelled_booking":
        reader.data["requests"][0]["status"] = "cancelled"
    assert obj.observe(binding)["evidence_complete"] is False
