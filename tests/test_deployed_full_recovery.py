"""Offline coordinator tests; captured observations are not native acceptance."""

import json

import pytest

from live_simulations.core import SimulationError, private_json
from live_simulations.deployed_full_recovery import prepare_source, submit_source


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    """Pure offline coordinator has no database dependency."""
    yield


def inputs(tmp_path):
    private_json(tmp_path / "usage-ledger.json", {"entries": []})
    folder = tmp_path / ("a" * 32)
    private_json(
        folder / "manifest.json",
        {
            "run_id": "a" * 32,
            "campaign_agent_id": "agent",
            "invocations": [],
            "provider_tests": ["test"],
        },
    )
    return {
        "root": tmp_path,
        "identity": {
            "run_id": "a" * 32,
            "case_id": "C48",
            "attempt": 1,
            "test_id": "test",
            "agent_id": "agent",
        },
        "expected_booking": {
            "customer_id": 9,
            "staff_agent_id": 4,
            "starts_at": "2026-11-11T10:00:00-05:00",
            "ends_at": "2026-11-11T11:00:00-05:00",
            "service_type": "Oil Change",
            "duration_minutes": 60,
        },
        "tool_url": "https://owned.invalid/tool",
        "test_definition": {
            "id": "test",
            "type": "simulation",
            "tool_mock_config": {
                "mocking_strategy": "none",
                "fallback_strategy": "call_real_tool",
                "mocked_tool_ids": [],
            },
        },
        "budget": {
            "source_estimate": 10,
            "recovery_estimate": 20,
            "credit_ceiling": 100,
            "remaining": 100,
        },
        "observe_baseline": lambda: {
            "source": "native_postgresql",
            "customer_id": 9,
            "observed_at_unix": 100,
            "baseline_note_ids": [],
            "baseline_event_ids": [],
            "request_ids": [],
            "reservation_ids": [],
            "active_request_ids": [],
        },
    }


def test_baseline_precedes_submission_and_common_ledger_binding(tmp_path):
    args = inputs(tmp_path)
    prepared = prepare_source(**args)

    def submit(request):
        assert (tmp_path / ("a" * 32) / "C48-1-pre-invocation.json").exists()
        return {"id": "invocation"}

    binding = submit_source(
        tmp_path, identity=args["identity"], submit=submit, now=lambda: 101
    )
    ledger = json.loads((tmp_path / "usage-ledger.json").read_text())
    assert ledger["entries"][0]["invocation_id"] == binding.invocation_id
    assert prepared["baseline"]["customer_id"] == 9


def test_ambiguous_submit_is_never_repeated(tmp_path):
    args = inputs(tmp_path)
    prepare_source(**args)
    calls = []

    def submit(request):
        calls.append(request)
        raise RuntimeError("private-token")

    for _ in range(2):
        with pytest.raises(SimulationError) as error:
            submit_source(
                tmp_path, identity=args["identity"], submit=submit, now=lambda: 101
            )
        assert "private-token" not in str(error.value)
    assert len(calls) == 1
    ledger = json.loads((tmp_path / "usage-ledger.json").read_text())
    assert ledger["entries"][0]["submission_unknown"] is True
    assert ledger["entries"][0]["unsettled"] is True


@pytest.mark.parametrize(
    "change", ["reserve", "unknown", "missing_recovery", "foreign_baseline", "boolean"]
)
def test_preparation_failures_precede_submit(tmp_path, change):
    args = inputs(tmp_path)
    if change == "reserve":
        args["budget"]["credit_ceiling"] = 30
    if change == "unknown":
        private_json(tmp_path / "usage-ledger.json", {"entries": [{"unsettled": True}]})
    if change == "missing_recovery":
        args["budget"].pop("recovery_estimate")
    if change == "foreign_baseline":
        args["observe_baseline"] = lambda: {
            "source": "native_postgresql",
            "customer_id": 8,
        }
    if change == "boolean":
        args["budget"]["source_estimate"] = True
    with pytest.raises(SimulationError):
        prepare_source(**args)
    assert not (tmp_path / ("a" * 32) / "C48-1-pre-invocation.json").exists()


def lifecycle(tmp_path):
    import copy
    import runpy
    from pathlib import Path

    from live_simulations.deployed_full_recovery import (
        advance_recovery,
        advance_source,
        prepare_recovery,
        submit_recovery,
    )

    old = runpy.run_path(
        str(Path(__file__).with_name("test_deployed_full_interruption.py"))
    )
    root, binding, journal, booking, provider = old["setup"].__wrapped__(tmp_path)
    journal["baseline"].update(baseline_note_ids=[], baseline_event_ids=[])
    folder = root / binding.run_id
    for name in ("C48-1-pre-invocation.json", "C48-1-interruption-journal.json"):
        (folder / name).unlink()
    private_json(root / "usage-ledger.json", {"entries": []})
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["invocations"] = []
    manifest["provider_tests"].append("recovery-test")
    private_json(folder / "manifest.json", manifest)
    identity = {k: v for k, v in binding.as_dict().items() if k != "invocation_id"}
    test = {
        "id": binding.test_id,
        "type": "simulation",
        "tool_mock_config": {
            "mocking_strategy": "none",
            "fallback_strategy": "call_real_tool",
            "mocked_tool_ids": [],
        },
    }
    prepare_source(
        root,
        identity=identity,
        expected_booking=journal["expected_booking"],
        test_definition=test,
        tool_url=journal["tool_url"],
        budget={
            "source_estimate": 20,
            "recovery_estimate": 20,
            "credit_ceiling": 200,
            "remaining": 200,
        },
        observe_baseline=lambda: copy.deepcopy(journal["baseline"]),
    )
    bound = submit_source(
        root,
        identity=identity,
        submit=lambda _: {"id": binding.invocation_id},
        now=lambda: 101,
    )
    interrupted = advance_source(
        root,
        binding=bound,
        provider=provider,
        observe_booking=lambda: copy.deepcopy(booking),
    )
    assert interrupted["interruption_verified"] is True
    recovery_identity = identity | {"test_id": "recovery-test"}
    prepare_recovery(
        root,
        source_binding=bound,
        identity=recovery_identity,
        test_definition=test | {"id": "recovery-test"},
        observe_booking=lambda: copy.deepcopy(booking),
    )
    recovery = submit_recovery(
        root, identity=recovery_identity, submit=lambda _: {"id": "recovery-invocation"}
    )
    recovered = {
        "id": recovery.invocation_id,
        "agent_id": recovery.agent_id,
        "cancelled": False,
        "test_runs": [
            {
                "test_id": recovery.test_id,
                "test_invocation_id": recovery.invocation_id,
                "status": "passed",
                "credits_used": 11,
                "agent_responses": [
                    {
                        "role": "agent",
                        "message": "Your existing appointment is confirmed.",
                    }
                ],
            }
        ],
    }
    provider.responses = [recovered]
    delivery = {
        "source": "native_postgresql",
        "customer_id": 9,
        "service_request_id": 31,
        "reservation_id": 41,
        "calendar_events": [
            {
                "service_request_id": 31,
                "staff_agent_id": 4,
                "status": "confirmed",
                "provider_event_id": "event",
            }
        ],
        "call_history": [
            {
                "provider_invocation_id": recovery.invocation_id,
                "customer_id": 9,
            }
        ],
        "notifications": [
            {
                "service_request_id": 31,
                "status": "delivered",
                "provider_message_id": "message",
            }
        ],
    }
    complete_external_evidence(provider, binding, journal, delivery)
    return (
        {
            "root": root,
            "binding": recovery,
            "provider": provider,
            "observe_booking": lambda: copy.deepcopy(booking),
            "observe_delivery": lambda: copy.deepcopy(delivery),
        },
        advance_recovery,
        booking,
        delivery,
    )


def test_captured_source_cancellation_and_separate_recovery_same_native_effect(
    tmp_path,
):
    args, advance, _booking, _delivery = lifecycle(tmp_path)
    result = advance(**args)
    assert result["recovery_verified"] is True
    assert result["global_stop"] is False and result["full_case_supported"] is False
    assert (
        result["implemented_offline"] is True
        and result["native_acceptance"] == "unverified"
    )
    assert advance(**args)["recovery_verified"] is True
    ledger = json.loads((tmp_path / "usage-ledger.json").read_text())
    assert [e["credits"] for e in ledger["entries"]] == ["17", "11"]
    assert len(ledger["entries"]) == 2
    assert args["provider"].cancels == ["invocation-48"]


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "wrong_delivery",
        "unknown_credits",
        "secret_error",
        "booking_call",
        "same_invocation",
    ],
)
def test_recovery_uncertainty_keeps_gate_closed(tmp_path, change):
    args, advance, booking, delivery = lifecycle(tmp_path)
    if change == "duplicate":
        booking["requests"].append(dict(booking["requests"][0]))
    if change == "wrong_delivery":
        delivery["calendar_events"][0]["service_request_id"] = 100
    if change == "unknown_credits":
        args["provider"].responses[0]["test_runs"][0]["credits_used"] = None
    if change == "secret_error":

        def fail():
            raise SimulationError("PRIVATE SECRET")

        args["observe_delivery"] = fail
    if change == "booking_call":
        args["provider"].responses[0]["test_runs"][0]["agent_responses"][0][
            "tool_calls"
        ] = [{"tool_name": "book_appointment"}]
    if change == "same_invocation":
        args["provider"].responses[0]["id"] = "invocation-48"
    outcome = advance(**args)
    assert outcome["recovery_verified"] is False and outcome["global_stop"] is True
    assert "PRIVATE" not in json.dumps(outcome)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_booking", []),
        ("test_definition", []),
        ("identity", []),
        ("budget", []),
    ],
)
def test_invalid_types_have_fixed_safe_errors(tmp_path, field, value):
    args = inputs(tmp_path)
    args[field] = value
    with pytest.raises(SimulationError):
        prepare_source(**args)


def test_recovery_conflicting_settlement_is_integrity_error(tmp_path):
    args, advance, _, _ = lifecycle(tmp_path)
    assert advance(**args)["recovery_verified"] is True
    args["provider"].responses[0]["test_runs"][0]["credits_used"] = 12
    with pytest.raises(SimulationError, match="credits conflict"):
        advance(**args)


@pytest.mark.parametrize(
    "change", ["missing_lookup", "foreign_result", "boolean_booking_fk"]
)
def test_recovery_requires_actual_testing_lookup_provenance(tmp_path, change):
    args, advance, _, delivery = lifecycle(tmp_path)
    responses = args["provider"].responses[0]["test_runs"][0]["agent_responses"]
    if change == "missing_lookup":
        responses[0]["tool_calls"] = []
    if change == "foreign_result":
        responses[-1]["tool_results"][0]["request_id"] = "foreign"
    if change == "boolean_booking_fk":
        delivery["service_request_id"] = True
    assert advance(**args)["recovery_verified"] is False


@pytest.mark.parametrize("delayed", [False, True])
@pytest.mark.parametrize("recovery_pending", [0, 2, 4])
def test_runner_facade_dispatches_full_lifecycle(tmp_path, delayed, recovery_pending):
    import runpy
    from pathlib import Path

    from live_simulations.deployed_full_recovery import execute

    old = runpy.run_path(
        str(Path(__file__).with_name("test_deployed_full_interruption.py"))
    )
    root, binding, journal, booking, provider = old["setup"].__wrapped__(tmp_path)
    journal["baseline"].update(baseline_note_ids=[], baseline_event_ids=[])
    folder = root / binding.run_id
    for name in ("C48-1-pre-invocation.json", "C48-1-interruption-journal.json"):
        (folder / name).unlink()
    private_json(root / "usage-ledger.json", {"entries": []})
    private_json(
        folder / "manifest.json",
        {
            "run_id": binding.run_id,
            "campaign_agent_id": binding.agent_id,
            "invocations": [],
            "provider_tests": [binding.test_id, "recovery-test"],
        },
    )
    identity = {k: v for k, v in binding.as_dict().items() if k != "invocation_id"}
    test = {
        "id": binding.test_id,
        "type": "simulation",
        "tool_mock_config": {
            "mocking_strategy": "none",
            "fallback_strategy": "call_real_tool",
            "mocked_tool_ids": [],
        },
    }
    recovery_receipt = {
        "id": "recovery-invocation",
        "agent_id": binding.agent_id,
        "cancelled": False,
        "test_runs": [
            {
                "test_id": "recovery-test",
                "test_invocation_id": "recovery-invocation",
                "status": "passed",
                "credits_used": 11,
                "agent_responses": [
                    {"role": "agent", "message": "Your appointment remains booked."}
                ],
            }
        ],
    }

    recovery_submissions = []

    def recovery_submit(request):
        recovery_submissions.append(request)
        assert request == {"tests": [{"test_id": "recovery-test"}], "repeat_count": 1}
        assert (
            json.loads((folder / "C48-1-interruption.json").read_text())[
                "interruption_verified"
            ]
            is True
        )
        import copy

        pending = copy.deepcopy(recovery_receipt)
        pending["test_runs"][0]["status"] = "pending"
        pending["test_runs"][0]["credits_used"] = None
        provider.responses = [pending] * recovery_pending + [recovery_receipt]
        return {"id": "recovery-invocation"}

    source = {
        "identity": identity,
        "expected_booking": journal["expected_booking"],
        "test_definition": test,
        "tool_url": journal["tool_url"],
        "budget": {
            "source_estimate": 20,
            "recovery_estimate": 20,
            "credit_ceiling": 200,
            "remaining": 200,
        },
        "observe_baseline": lambda: journal["baseline"],
        "submit": lambda request: {"id": binding.invocation_id},
        "now": lambda: 101,
    }
    delivery = {
        "source": "native_postgresql",
        "customer_id": 9,
        "service_request_id": 31,
        "reservation_id": 41,
        "call_history": [
            {
                "provider_invocation_id": "recovery-invocation",
                "customer_id": 9,
            }
        ],
        "calendar_events": [
            {
                "service_request_id": 31,
                "staff_agent_id": 4,
                "status": "confirmed",
                "provider_event_id": "event",
            }
        ],
        "notifications": [
            {
                "service_request_id": 31,
                "status": "delivered",
                "provider_message_id": "message",
            }
        ],
    }
    complete_external_evidence(provider, binding, journal, delivery, recovery_receipt)
    observed = [False]
    if delayed:
        import copy

        provider.responses.insert(0, copy.deepcopy(provider.responses[0]))

    def observe_booking():
        if delayed and not observed[0]:
            observed[0] = True
            raise SimulationError("Booking has not committed yet")
        return booking

    sleeps = []
    result = execute(
        root,
        source=source,
        recovery={
            "identity": identity | {"test_id": "recovery-test"},
            "test_definition": test | {"id": "recovery-test"},
            "submit": recovery_submit,
        },
        provider=provider,
        observe_booking=observe_booking,
        observe_delivery=lambda: delivery,
        max_recovery_polls=3,
        poll_interval=0,
        sleep=sleeps.append,
    )
    assert len(recovery_submissions) == 1
    assert sleeps == [0] * (min(recovery_pending, 2) + int(delayed))
    if recovery_pending == 4:
        assert result["status"] == "awaiting_terminal"
        assert result["global_stop"] is True
        from live_simulations.deployed_full_recovery import advance_recovery
        from live_simulations.deployed_full_interruption import Binding

        resumed = advance_recovery(
            root,
            binding=Binding(**result["recovery_binding"]),
            provider=provider,
            observe_booking=observe_booking,
            observe_delivery=lambda: delivery,
        )
        assert resumed["status"] == "awaiting_terminal"
        resumed = advance_recovery(
            root,
            binding=Binding(**result["recovery_binding"]),
            provider=provider,
            observe_booking=observe_booking,
            observe_delivery=lambda: delivery,
        )
        assert resumed["recovery_verified"] is True
        assert len(json.loads((root / "usage-ledger.json").read_text())["entries"]) == 2
        return
    assert (
        result["recovery_verified"] is True
        and result["native_acceptance"] == "unverified"
    )
    assert (
        result["source_binding"]["invocation_id"]
        != result["recovery_binding"]["invocation_id"]
    )


@pytest.mark.parametrize(
    "field", ["customer_id", "service_request_id", "reservation_id"]
)
def test_delivery_native_ids_cannot_be_float(tmp_path, field):
    args, advance, _, delivery = lifecycle(tmp_path)
    delivery[field] = float(delivery[field])
    assert advance(**args)["recovery_verified"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool_url", "https://user:PRIVATE@owned.invalid/tool"),
        (
            "test_definition",
            {
                "id": "test",
                "type": "simulation",
                "tool_mock_config": {
                    "mocking_strategy": "none",
                    "fallback_strategy": "call_real_tool",
                    "mocked_tool_ids": [],
                },
                "api_key": "PRIVATE",
            },
        ),
    ],
)
def test_private_preparation_inputs_rejected_before_persistence(tmp_path, field, value):
    args = inputs(tmp_path)
    args[field] = value
    with pytest.raises(SimulationError):
        prepare_source(**args)
    assert not (tmp_path / ("a" * 32) / "C48-1-pre-invocation.json").exists()


def test_recovery_deducts_actual_source_cost_from_retained_quota(tmp_path):
    from live_simulations.deployed_full_recovery import _budget

    with pytest.raises(SimulationError):
        _budget(
            {
                "source_estimate": 2,
                "recovery_estimate": 2,
                "credit_ceiling": 100,
                "remaining": 10,
                "quota_baseline_spent": 0,
            },
            {"entries": [{"unsettled": False, "credits": 9}]},
            run_id="a" * 32,
            phase="recovery",
        )


def test_recovery_empty_turn_dict_is_not_actual_conversation(tmp_path):
    args, advance, _, _ = lifecycle(tmp_path)
    args["provider"].responses[0]["test_runs"][0]["agent_responses"] = [{}]
    assert advance(**args)["recovery_verified"] is False


def complete_external_evidence(
    provider, source_binding, journal, delivery, recovery_receipt=None
):
    from live_simulations.core import fingerprint

    receipt = (
        recovery_receipt if recovery_receipt is not None else provider.responses[-1]
    )
    run = receipt["test_runs"][0]
    run.pop("conversation_id", None)
    expected = journal["expected_booking"]
    lookup = {
        "type": "webhook",
        "request_id": "recovery-lookup",
        "tool_name": "get_customer_appointments",
        "tool_has_been_called": True,
        "tool_details": {
            "type": "webhook",
            "method": "POST",
            "url": journal["tool_url"].replace(
                "name=book_appointment", "name=get_customer_appointments"
            ),
        },
        "params_as_json": json.dumps(
            {"phone": "+14242704893", "caller_phone": "+14242704893"}
        ),
    }
    result = {
        "tool_name": "get_customer_appointments",
        "request_id": "recovery-lookup",
        "is_error": False,
        "result_value": json.dumps(
            {
                "result": {
                    "success": True,
                    "appointments": [
                        {
                            "id": 31,
                            "appointment_datetime": expected["starts_at"],
                            "booking_type": "appointment",
                            "service_type": "Oil Change",
                            "duration_minutes": 60,
                            "status": "pending",
                        }
                    ],
                }
            }
        ),
    }
    run["agent_responses"][0]["tool_calls"] = [lookup]
    run["agent_responses"].append(
        {
            "role": "agent",
            "message": "Your existing appointment remains confirmed.",
            "tool_results": [result],
        }
    )
    expected = journal["expected_booking"]
    event = delivery["calendar_events"][0]
    event.update(
        reservation_id=41,
        starts_at=expected["starts_at"],
        ends_at=expected["ends_at"],
        calendar_id="owned-calendar",
        booking_invocation_id=source_binding.invocation_id,
    )
    actual = {
        "id": event["provider_event_id"],
        "status": "confirmed",
        "start": {"dateTime": expected["starts_at"]},
        "end": {"dateTime": expected["ends_at"]},
    }
    delivery["staff_calendar"] = {"staff_agent_id": 4, "calendar_id": "owned-calendar"}
    provider.get_calendar_event = lambda calendar, event: (
        actual if calendar == "owned-calendar" else {}
    )
    delivery["customer_recipient_sha256"] = fingerprint("+14242704893")
    for notice in delivery["notifications"]:
        notice.update(
            id=91,
            attempt=1,
            run_id=source_binding.run_id,
            case_id="C48",
            booking_invocation_id=source_binding.invocation_id,
            recipient_sha256=delivery["customer_recipient_sha256"],
        )
    provider.get_message = lambda sid: {
        "sid": sid,
        "status": "delivered",
        "direction": "outbound-api",
        "to": "whatsapp:+14242704893",
    }


@pytest.mark.parametrize(
    "change",
    [
        "lookup_id",
        "empty_response",
        "mutating_turn",
        "lookup_url",
        "lookup_result",
        "mocked_lookup",
        "event_time",
        "reservation",
        "calendar",
        "recipient",
        "notice_attempt",
        "message_delivery",
    ],
)
def test_independent_external_recovery_proof_is_exact(tmp_path, change):
    args, advance, _, delivery = lifecycle(tmp_path)
    provider = args["provider"]
    responses = provider.responses[0]["test_runs"][0]["agent_responses"]
    if change == "lookup_id":
        responses[0]["tool_calls"][0]["request_id"] = "foreign"
    if change == "empty_response":
        provider.responses[0]["test_runs"][0]["agent_responses"] = [{}]
    if change == "mutating_turn":
        responses[0]["tool_calls"].append({"tool_name": "reschedule_appointment"})
    if change == "lookup_url":
        responses[0]["tool_calls"][0]["tool_details"]["url"] = (
            "https://foreign.invalid/tools"
        )
    if change == "lookup_result":
        value = json.loads(responses[-1]["tool_results"][0]["result_value"])
        value["result"]["appointments"][0]["id"] = 999
        responses[-1]["tool_results"][0]["result_value"] = json.dumps(value)
    if change == "mocked_lookup":
        responses[0]["tool_calls"][0]["tool_has_been_called"] = False
    if change == "event_time":
        original = provider.get_calendar_event
        provider.get_calendar_event = lambda *args: (
            original(*args) | {"start": {"dateTime": "2026-11-12T10:00:00-05:00"}}
        )
    if change == "reservation":
        delivery["calendar_events"][0]["reservation_id"] = 999
    if change == "calendar":
        delivery["calendar_events"][0]["calendar_id"] = "foreign"
    if change == "recipient":
        delivery["notifications"][0]["recipient_sha256"] = "a" * 64
    if change == "notice_attempt":
        delivery["notifications"][0]["attempt"] = 2
    if change == "message_delivery":
        provider.get_message = lambda sid: {
            "sid": sid,
            "status": "sent",
            "direction": "outbound-api",
            "to": "+14242704893",
        }
    assert advance(**args)["recovery_verified"] is False


def test_coordinator_accepts_exact_owned_canonical_oil_service(tmp_path):
    args = inputs(tmp_path)
    args["expected_booking"]["service_type"] = "owner123 Oil Change"
    prepared = prepare_source(**args)
    assert prepared["expected_booking"]["service_type"] == "owner123 Oil Change"


@pytest.mark.parametrize("current_spend,accepted", [(25, True), (55, False)])
def test_budget_ceiling_counts_current_run_all_phases_not_lifetime(
    tmp_path, current_spend, accepted
):
    args = inputs(tmp_path)
    private_json(
        tmp_path / "usage-ledger.json",
        {
            "entries": [
                {"run_id": "b" * 32, "credits": 500, "unsettled": False},
                {
                    "run_id": args["identity"]["run_id"],
                    "case_id": "C17",
                    "credits": current_spend,
                    "unsettled": False,
                },
            ]
        },
    )
    if accepted:
        prepared = prepare_source(**args)
        assert prepared["budget"]["quota_baseline_spent"] == str(500 + current_spend)
    else:
        with pytest.raises(SimulationError):
            prepare_source(**args)


def test_foreign_unsettled_usage_still_blocks_current_run(tmp_path):
    args = inputs(tmp_path)
    private_json(
        tmp_path / "usage-ledger.json",
        {
            "entries": [
                {"run_id": "b" * 32, "unsettled": True},
            ]
        },
    )
    with pytest.raises(SimulationError):
        prepare_source(**args)


@pytest.mark.parametrize("polls", [0, 101, True, 1.5])
def test_recovery_poll_bound_rejected_before_any_submission(tmp_path, polls):
    from live_simulations.deployed_full_recovery import execute

    with pytest.raises(SimulationError, match="Bounded same-handle"):
        execute(
            tmp_path,
            source={},
            recovery={},
            provider=None,
            observe_booking=lambda: None,
            observe_delivery=lambda: None,
            max_recovery_polls=polls,
        )
    assert not (tmp_path / "usage-ledger.json").exists()
