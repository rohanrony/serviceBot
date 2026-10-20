"""Offline-testable C48 lifecycle coordinator. No default provider or native writer.

The caller owns independently authenticated native observers and explicit paid
admission. These interfaces do not open the full-stage live gate.
"""

import json
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import SimulationError, fingerprint, number, private_json
from .deployed_full_interruption import (
    Binding,
    _booking,
    _context,
    _external,
    _intent,
    _positive_id,
    _provider_run,
    _read,
    _same_binding,
    _settle,
    _sync_directory,
    advance,
)
from .runner import campaign_lock


def _identity(identity):
    try:
        binding = Binding(**identity, invocation_id="preparation")
        binding.validate()
        return binding
    except Exception:  # noqa: BLE001 - retain only fixed safe diagnostics
        raise SimulationError("Exact C48 preparation identity required") from None


def _budget(budget, ledger, *, run_id, phase="source"):
    try:
        values = [
            budget[k]
            for k in (
                "source_estimate",
                "recovery_estimate",
                "credit_ceiling",
                "remaining",
            )
        ]
        if any(type(v) not in (int, float, str, Decimal) for v in values):
            raise ValueError
        source, recovery, ceiling, remaining = [
            number(v, positive=True) for v in values
        ]
        entries = ledger["entries"]
        if not isinstance(entries, list) or any(
            not isinstance(e, dict) or e.get("unsettled") is not False for e in entries
        ):
            raise ValueError
        spent = sum((number(e["credits"]) for e in entries), Decimal(0))
        # A stage claim belongs to one run. Count every phase/case in that
        # run, including spend preceding C48; historical runs only affect the
        # fresh provider quota delta and the global unsettled-use barrier.
        if not isinstance(run_id, str) or not re.fullmatch("[0-9a-f]{32}", run_id):
            raise ValueError
        stage_spent = sum(
            (number(e["credits"]) for e in entries if e.get("run_id") == run_id),
            Decimal(0),
        )
        baseline = number(budget.get("quota_baseline_spent", spent))
        required = source + recovery if phase == "source" else recovery
        if (
            baseline > spent
            or stage_spent + required > ceiling * Decimal(".8")
            or required > remaining - (spent - baseline)
        ):
            raise ValueError
        return {
            "quota_baseline_spent": str(baseline),
            **{
                k: str(v)
                for k, v in zip(
                    (
                        "source_estimate",
                        "recovery_estimate",
                        "credit_ceiling",
                        "remaining",
                    ),
                    (source, recovery, ceiling, remaining),
                )
            },
        }
    except Exception:  # noqa: BLE001 - retain only fixed safe diagnostics
        raise SimulationError(
            "Both C48 phases, prior spend and reserve require verified budget"
        ) from None


def _definition(definition):
    if not isinstance(definition, dict) or set(definition) != {
        "id",
        "type",
        "tool_mock_config",
    }:
        raise SimulationError(
            "Only nonsecret immutable provider test fields are accepted"
        )


def _tool_url(value):
    try:
        parts = urlsplit(value)
        query = parse_qs(parts.query, strict_parsing=True)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
            or query not in ({}, {"name": ["book_appointment"]})
            or parts.port not in (None, 443)
        ):
            raise ValueError
    except Exception:  # noqa: BLE001 - fixed safe URL diagnostic
        raise SimulationError(
            "Nonsecret exact HTTPS application tool URL required"
        ) from None


def prepare_source(
    root,
    *,
    identity,
    expected_booking,
    test_definition,
    tool_url,
    budget,
    observe_baseline,
):
    """Persist exclusively before submission; observer reads native baseline itself."""
    binding = _identity(identity)
    if not isinstance(expected_booking, dict) or not isinstance(test_definition, dict):
        raise SimulationError("Invalid owned source preparation types")
    _definition(test_definition)
    _tool_url(tool_url)
    root = Path(root)
    with campaign_lock(root):
        ledger = _read(root / "usage-ledger.json")
        retained_budget = _budget(budget, ledger, run_id=binding.run_id)
        folder = root / binding.run_id
        if folder.is_symlink() or not folder.is_dir():
            raise SimulationError("Owned source folder required")
        manifest = _read(folder / "manifest.json")
        if (
            manifest.get("run_id") != binding.run_id
            or manifest.get("campaign_agent_id") != binding.agent_id
            or binding.test_id not in manifest.get("provider_tests", [])
            or test_definition.get("id") != binding.test_id
            or test_definition.get("type") != "simulation"
            or test_definition.get("tool_mock_config")
            != {
                "mocking_strategy": "none",
                "fallback_strategy": "call_real_tool",
                "mocked_tool_ids": [],
            }
            or not isinstance(tool_url, str)
            or not tool_url.startswith("https://")
            or not all(
                _positive_id(expected_booking.get(k))
                for k in ("customer_id", "staff_agent_id")
            )
        ):
            raise SimulationError("Owned unmocked source preparation required")
        # Reject malformed expected slots before any paid callback can be reached.
        if set(expected_booking) >= {
            "starts_at",
            "ends_at",
            "service_type",
            "duration_minutes",
        }:
            try:
                start = datetime.fromisoformat(expected_booking["starts_at"])
                end = datetime.fromisoformat(expected_booking["ends_at"])
                if (
                    start.tzinfo is None
                    or end.tzinfo is None
                    or start.second
                    or start.microsecond
                    or start.minute % 15
                    or end - start != timedelta(minutes=60)
                    or not isinstance(expected_booking["service_type"], str)
                    or not re.fullmatch(
                        r"[^\r\n\t]{1,255}", expected_booking["service_type"]
                    )
                    or not expected_booking["service_type"].strip()
                    or type(expected_booking["duration_minutes"]) is not int
                    or expected_booking["duration_minutes"] != 60
                ):
                    raise ValueError
            except Exception:  # noqa: BLE001 - retain only fixed safe diagnostics
                raise SimulationError(
                    "Exact owned one-hour canonical service slot required"
                ) from None
        else:
            raise SimulationError(
                "Exact owned one-hour canonical service slot required"
            )
        baseline = _external(observe_baseline)
        try:
            if (
                baseline["source"] != "native_postgresql"
                or baseline["customer_id"] != expected_booking["customer_id"]
                or baseline["active_request_ids"] != []
                or type(baseline["observed_at_unix"]) not in (int, float)
                or not number(baseline["observed_at_unix"], positive=True)
                or any(
                    not isinstance(baseline[k], list)
                    or any(not _positive_id(v) for v in baseline[k])
                    for k in (
                        "request_ids",
                        "reservation_ids",
                    )
                )
            ):
                raise ValueError
        except Exception:  # noqa: BLE001 - retain only fixed safe diagnostics
            raise SimulationError(
                "Independent clean native baseline required"
            ) from None
        pre = {
            "schema_version": 1,
            "binding": identity,
            "baseline": baseline,
            "expected_booking": expected_booking,
            "tool_url": tool_url,
            "test_definition": test_definition,
            "budget": retained_budget,
            "invocation_request": {
                "tests": [{"test_id": binding.test_id}],
                "repeat_count": 1,
            },
        }
        _intent(folder / f"C48-{binding.attempt}-pre-invocation.json", pre)
        ledger.setdefault("c48_preparations", []).append(
            {
                "binding": identity,
                "pre_invocation_sha256": fingerprint(pre),
                "budget": retained_budget,
            }
        )
        private_json(root / "usage-ledger.json", ledger)
        return pre


def submit_source(root, *, identity, submit, now):
    """Durable intent precedes injected submit; ambiguity cannot resubmit."""
    seed = _identity(identity)
    root = Path(root)
    with campaign_lock(root):
        folder = root / seed.run_id
        pre = _read(folder / f"C48-{seed.attempt}-pre-invocation.json")
        if not _same_binding(pre.get("binding"), identity):
            raise SimulationError("Source preparation identity differs")
        ledger = _read(root / "usage-ledger.json")
        _budget(pre["budget"], ledger, run_id=seed.run_id)
        owned = [
            p
            for p in ledger.get("c48_preparations", [])
            if _same_binding(p.get("binding"), identity)
        ]
        if len(owned) != 1 or owned[0].get("pre_invocation_sha256") != fingerprint(pre):
            raise SimulationError("Common ledger does not bind immutable preparation")
        stamp = _external(now)
        if type(stamp) not in (int, float) or number(stamp, positive=True) <= number(
            pre["baseline"]["observed_at_unix"]
        ):
            raise SimulationError("Source submission must follow native baseline")
        intent_path = folder / f"C48-{seed.attempt}-submit-intent.json"
        if intent_path.exists():
            raise SimulationError(
                "Source submission already attempted; reconcile same handle without resubmission"
            )
        _intent(
            intent_path,
            {
                "binding": identity,
                "pre_invocation_sha256": fingerprint(pre),
                "submitted_at_unix": stamp,
            },
        )
        pending = {
            **identity,
            "phase": "interruption",
            "unsettled": True,
            "submission_unknown": True,
            "pre_invocation_sha256": fingerprint(pre),
        }
        ledger["entries"].append(pending)
        private_json(root / "usage-ledger.json", ledger)
        response = _external(submit, pre["invocation_request"])
        try:
            binding = Binding(**identity, invocation_id=response["id"])
            binding.validate()
        except Exception:  # noqa: BLE001 - retain only fixed safe diagnostics
            raise SimulationError(
                "Source submission handle unavailable; do not resubmit"
            ) from None
        if any(
            e.get("invocation_id") == binding.invocation_id for e in ledger["entries"]
        ):
            raise SimulationError(
                "Provider invocation already belongs to common ledger"
            )
        journal = {
            "schema_version": 1,
            "binding": binding.as_dict(),
            "submitted_at_unix": stamp,
            "pre_invocation_sha256": fingerprint(pre),
            **{k: pre[k] for k in ("baseline", "expected_booking", "tool_url")},
        }
        _intent(folder / f"C48-{seed.attempt}-interruption-journal.json", journal)
        pending.update(
            **binding.as_dict(),
            submission_unknown=False,
            interruption_journal_sha256=fingerprint(journal),
        )
        private_json(root / "usage-ledger.json", ledger)
        manifest = _read(folder / "manifest.json")
        manifest.setdefault("invocations", []).append(binding.invocation_id)
        private_json(folder / "manifest.json", manifest)
        _sync_directory(folder)
        return binding


def advance_source(root, **kwargs):
    """Runner-facing cancellation dispatch uses the existing proven controller."""
    return advance(root, **kwargs)


def prepare_recovery(
    root, *, source_binding, identity, test_definition, observe_booking
):
    """Bind separate recovery identity to verified cancellation and durable effect."""
    candidate = _identity(identity)
    _definition(test_definition)
    if (
        candidate.run_id != source_binding.run_id
        or candidate.attempt != source_binding.attempt
        or candidate.agent_id != source_binding.agent_id
        or candidate.test_id == source_binding.test_id
    ):
        raise SimulationError("Recovery requires a separate owned test identity")
    root = Path(root)
    with campaign_lock(root):
        folder, journal, ledger, _ = _context(root, source_binding)
        source = _read(folder / f"C48-{source_binding.attempt}-interruption.json")
        intent = _read(folder / f"C48-{source_binding.attempt}-cancel-intent.json")
        proof = source.get("proof", {})
        if (
            source.get("status") != "verified_interruption"
            or source.get("interruption_verified") is not True
            or not _same_binding(source.get("binding"), source_binding.as_dict())
            or not _same_binding(proof.get("binding"), source_binding.as_dict())
            or proof.get("journal_sha256") != fingerprint(journal)
            or not _same_binding(intent.get("binding"), source_binding.as_dict())
            or proof.get("pending_provider_sha256")
            != intent.get("pending_provider_sha256")
        ):
            raise SimulationError("Recovery requires genuine owned cancellation proof")
        pre = _read(folder / f"C48-{candidate.attempt}-pre-invocation.json")
        _budget(pre["budget"], ledger, run_id=candidate.run_id, phase="recovery")
        manifest = _read(folder / "manifest.json")
        if (
            candidate.test_id not in manifest.get("provider_tests", [])
            or test_definition.get("id") != candidate.test_id
            or test_definition.get("type") != "simulation"
            or test_definition.get("tool_mock_config")
            != pre["test_definition"]["tool_mock_config"]
        ):
            raise SimulationError("Owned unmocked recovery test required")
        booking = _booking(_external(observe_booking), journal)
        if fingerprint(booking) != proof.get(
            "native_booking_sha256"
        ) or booking != intent.get("native_booking"):
            raise SimulationError(
                "Recovery durable booking differs from verified interruption"
            )
        value = {
            "schema_version": 1,
            "binding": identity,
            "source_binding": source_binding.as_dict(),
            "tool_url": journal["tool_url"],
            "source_proof_sha256": fingerprint(source),
            "native_booking": booking,
            "expected_booking": journal["expected_booking"],
            "budget": pre["budget"],
            "baseline": journal["baseline"],
            "test_definition": test_definition,
            "invocation_request": {
                "tests": [{"test_id": candidate.test_id}],
                "repeat_count": 1,
            },
        }
        _intent(folder / f"C48-{candidate.attempt}-recovery-pre-invocation.json", value)
        return value


def submit_recovery(root, *, identity, submit):
    """Independent paid invocation, never a retry of the interrupted source."""
    seed = _identity(identity)
    root = Path(root)
    with campaign_lock(root):
        folder = root / seed.run_id
        pre = _read(folder / f"C48-{seed.attempt}-recovery-pre-invocation.json")
        if not _same_binding(pre.get("binding"), identity):
            raise SimulationError("Recovery preparation identity differs")
        ledger = _read(root / "usage-ledger.json")
        _budget(pre["budget"], ledger, run_id=seed.run_id, phase="recovery")
        intent_path = folder / f"C48-{seed.attempt}-recovery-submit-intent.json"
        if intent_path.exists():
            raise SimulationError(
                "Recovery already attempted; reconcile same handle without resubmission"
            )
        _intent(
            intent_path,
            {"binding": identity, "pre_invocation_sha256": fingerprint(pre)},
        )
        pending = {
            **identity,
            "phase": "recovery",
            "unsettled": True,
            "submission_unknown": True,
            "pre_invocation_sha256": fingerprint(pre),
        }
        ledger["entries"].append(pending)
        private_json(root / "usage-ledger.json", ledger)
        receipt = _external(submit, pre["invocation_request"])
        try:
            binding = Binding(**identity, invocation_id=receipt["id"])
            binding.validate()
        except Exception:  # noqa: BLE001 - retain only fixed safe diagnostics
            raise SimulationError(
                "Recovery handle unavailable; do not resubmit"
            ) from None
        if any(
            e.get("invocation_id") == binding.invocation_id for e in ledger["entries"]
        ):
            raise SimulationError(
                "Recovery invocation must be separate from all existing invocations"
            )
        journal = {
            "binding": binding.as_dict(),
            "pre_invocation_sha256": fingerprint(pre),
            "source_binding": pre["source_binding"],
        }
        _intent(folder / f"C48-{seed.attempt}-recovery-journal.json", journal)
        pending.update(
            **binding.as_dict(),
            submission_unknown=False,
            recovery_journal_sha256=fingerprint(journal),
        )
        private_json(root / "usage-ledger.json", ledger)
        manifest = _read(folder / "manifest.json")
        manifest.setdefault("invocations", []).append(binding.invocation_id)
        private_json(folder / "manifest.json", manifest)
        return binding


def advance_recovery(root, *, binding, provider, observe_booking, observe_delivery):
    """GET-only settlement and independent no-duplicate/delivery readback.

    Observers are native read owners, never config/seeded acceptance receipts.
    A successful local contract remains gated from paid/full native admission.
    """
    binding.validate()
    root = Path(root)
    with campaign_lock(root):
        folder = root / binding.run_id
        journal = _read(folder / f"C48-{binding.attempt}-recovery-journal.json")
        pre = _read(folder / f"C48-{binding.attempt}-recovery-pre-invocation.json")
        ledger = _read(root / "usage-ledger.json")
        manifest = _read(folder / "manifest.json")
        entries = [
            e
            for e in ledger.get("entries", [])
            if e.get("invocation_id") == binding.invocation_id
        ]
        if (
            not _same_binding(journal.get("binding"), binding.as_dict())
            or journal.get("pre_invocation_sha256") != fingerprint(pre)
            or len(entries) != 1
            or entries[0].get("recovery_journal_sha256") != fingerprint(journal)
            or not _same_binding(
                {k: entries[0].get(k) for k in binding.as_dict()}, binding.as_dict()
            )
            or binding.invocation_id not in manifest.get("invocations", [])
            or manifest.get("campaign_agent_id") != binding.agent_id
        ):
            raise SimulationError("Exact recovery invocation ownership required")
        result = {
            "status": "blocked",
            "global_stop": True,
            "recovery_verified": False,
            "full_case_supported": False,
        }
        try:
            receipt = _external(provider.get, binding.invocation_id)
            run = _provider_run(receipt, binding)
            if run["status"] == "pending":
                result["status"] = "awaiting_terminal"
            else:
                credits = _settle(root, ledger, entries[0], receipt)
                if (
                    credits is None
                    or run["status"] != "passed"
                    or receipt["cancelled"] is not False
                ):
                    raise SimulationError(
                        "Recovery terminal status or charge unverified"
                    )
                booking = _booking(_external(observe_booking), pre)
                if booking != pre["native_booking"]:
                    raise SimulationError(
                        "Recovery changed or duplicated durable booking"
                    )
                responses = run.get("agent_responses")
                if (
                    not isinstance(responses, list)
                    or not responses
                    or not any(
                        isinstance(r, dict)
                        and r.get("role") == "agent"
                        and isinstance(r.get("message"), str)
                        and len(r["message"].strip()) >= 10
                        for r in responses
                    )
                ):
                    raise SimulationError(
                        "Actual recovery conversation evidence unavailable"
                    )
                # Recovery must preserve the one existing booking, not recreate it.
                if any(
                    c.get("tool_name") == "book_appointment"
                    for r in responses
                    for c in r.get("tool_calls", [])
                ):
                    raise SimulationError("Recovery attempted a duplicate booking")
                delivery = _external(observe_delivery)
                request_id = booking["requests"][0]["id"]
                reservation_id = booking["reservations"][0]["id"]
                if (
                    not isinstance(delivery, dict)
                    or delivery.get("source") != "native_postgresql"
                    or any(
                        not _positive_id(delivery.get(k))
                        for k in ("customer_id", "service_request_id", "reservation_id")
                    )
                    or delivery.get("customer_id")
                    != pre["expected_booking"]["customer_id"]
                    or delivery.get("service_request_id") != request_id
                    or delivery.get("reservation_id") != reservation_id
                    or not isinstance(delivery.get("calendar_events"), list)
                    or len(delivery["calendar_events"]) != 1
                    or not isinstance(delivery.get("notifications"), list)
                    or not delivery["notifications"]
                ):
                    raise SimulationError(
                        "Independent native calendar and delivery evidence required"
                    )
                event = delivery["calendar_events"][0]
                if (
                    not _positive_id(event.get("service_request_id"))
                    or not _positive_id(event.get("staff_agent_id"))
                    or event.get("service_request_id") != request_id
                    or event.get("staff_agent_id")
                    != pre["expected_booking"]["staff_agent_id"]
                    or event.get("status") != "confirmed"
                    or not isinstance(event.get("provider_event_id"), str)
                    or not event["provider_event_id"]
                    or any(
                        not _positive_id(n.get("service_request_id"))
                        or n.get("service_request_id") != request_id
                        or n.get("status") != "delivered"
                        or not isinstance(n.get("provider_message_id"), str)
                        or not n["provider_message_id"]
                        for n in delivery["notifications"]
                    )
                ):
                    raise SimulationError(
                        "Native projection or delivery remains unverified"
                    )
                external_proof = _actual_recovery_evidence(
                    provider, run, delivery, pre, binding
                )
                result.update(
                    external_proof=external_proof,
                    status="verified_recovery",
                    recovery_verified=True,
                    credits=credits,
                    implemented_offline=True,
                    source_workflow_supported=True,
                    native_acceptance="unverified",
                    native_call_history_acceptance="unverified_separate_C50",
                    global_stop=any(
                        e.get("unsettled") is not False for e in ledger["entries"]
                    ),
                    native_booking_sha256=fingerprint(booking),
                    native_delivery_sha256=fingerprint(delivery),
                    provider_sha256=fingerprint(receipt),
                )
        except SimulationError as error:
            if (
                str(error)
                == "Settled invocation credits conflict with provider readback"
            ):
                raise
            result.update(
                status="blocked",
                reason="Recovery observation unavailable or inconsistent",
            )
        except Exception:  # noqa: BLE001 - retain only fixed safe diagnostics
            # Never persist callback exceptions or class names supplied by providers.
            result.update(
                status="blocked",
                reason="Recovery observation unavailable or inconsistent",
            )
        private_json(
            folder / f"C48-{binding.attempt}-recovery.json",
            {"binding": binding.as_dict(), **result},
        )
        return result


def execute(
    root,
    *,
    source,
    recovery,
    provider,
    observe_booking,
    observe_delivery,
    max_source_polls=30,
    max_recovery_polls=30,
    poll_interval=1,
    sleep=time.sleep,
):
    """Runner facade for one injected offline/native lifecycle, with no defaults.

    ``source`` contains prepare_source keyword arguments plus ``submit`` and
    ``now`` callbacks. ``recovery`` contains ``identity``, ``test_definition`` and
    its own ``submit`` callback. On an intermediate result, resume only through
    advance_source/advance_recovery on the returned binding; never call execute
    again to retry paid submission. The runner separately owns live admission.
    """
    if (
        type(max_source_polls) is not int
        or not 1 <= max_source_polls <= 100
        or type(max_recovery_polls) is not int
        or not 1 <= max_recovery_polls <= 100
        or type(poll_interval) not in (int, float)
        or not 0 <= number(poll_interval) <= 5
        or not callable(sleep)
    ):
        raise SimulationError("Bounded same-handle C48 observation options required")
    if not isinstance(source, dict) or not isinstance(recovery, dict):
        raise SimulationError("Explicit source and recovery coordinator hooks required")
    source = dict(source)
    submit = source.pop("submit", None)
    now = source.pop("now", None)
    if (
        not callable(submit)
        or not callable(now)
        or not callable(recovery.get("submit"))
        or not callable(source.get("observe_baseline"))
        or not callable(observe_booking)
        or not callable(observe_delivery)
    ):
        raise SimulationError("Independently owned lifecycle callbacks required")
    prepare_source(root, **source)
    binding = submit_source(root, identity=source["identity"], submit=submit, now=now)
    for poll in range(max_source_polls):
        interrupted = advance_source(
            root, binding=binding, provider=provider, observe_booking=observe_booking
        )
        if (
            interrupted.get("interruption_verified") is True
            or interrupted.get("status") == "failed_interruption"
        ):
            break
        if poll + 1 < max_source_polls:
            _external(sleep, poll_interval)
    if interrupted.get("interruption_verified") is not True:
        return {
            **interrupted,
            "source_binding": binding.as_dict(),
            "implemented_offline": True,
            "native_acceptance": "unverified",
        }
    prepare_recovery(
        root,
        source_binding=binding,
        identity=recovery["identity"],
        test_definition=recovery["test_definition"],
        observe_booking=observe_booking,
    )
    recovered = submit_recovery(
        root, identity=recovery["identity"], submit=recovery["submit"]
    )
    for poll in range(max_recovery_polls):
        result = advance_recovery(
            root,
            binding=recovered,
            provider=provider,
            observe_booking=observe_booking,
            observe_delivery=observe_delivery,
        )
        if result.get("status") != "awaiting_terminal":
            break
        if poll + 1 < max_recovery_polls:
            _external(sleep, poll_interval)
    return {
        **result,
        "source_binding": binding.as_dict(),
        "recovery_binding": recovered.as_dict(),
    }


def _actual_recovery_evidence(provider, run, delivery, pre, binding):
    """Fresh independent provider GETs joined to native audit/CRM/projection rows."""
    lookup_proof = _executed_recovery_lookup(run, pre)
    expected = pre["expected_booking"]
    source = pre["source_binding"]
    booking = pre["native_booking"]
    booking["requests"][0]["id"]
    reservation_id = booking["reservations"][0]["id"]
    event = delivery["calendar_events"][0]
    if (
        event.get("reservation_id") != reservation_id
        or type(event.get("reservation_id")) is not int
        or event.get("starts_at") != expected["starts_at"]
        or event.get("ends_at") != expected["ends_at"]
        or event.get("booking_invocation_id") != source["invocation_id"]
        or not isinstance(event.get("calendar_id"), str)
        or not event["calendar_id"]
    ):
        raise SimulationError(
            "Exact native booking projection identity and interval required"
        )
    connected = delivery.get("staff_calendar", {})
    if (
        type(connected.get("staff_agent_id")) is not int
        or connected.get("staff_agent_id") != expected["staff_agent_id"]
        or connected.get("calendar_id") != event["calendar_id"]
    ):
        raise SimulationError("Independent connected staff calendar identity required")
    # The authenticated reader scopes this GET to the native connected staff
    # calendar. Google event bodies do not echo a calendar ID or our native FKs.
    actual = _external(
        provider.get_calendar_event, event["calendar_id"], event["provider_event_id"]
    )
    if (
        not isinstance(actual, dict)
        or actual.get("id") != event["provider_event_id"]
        or actual.get("status") != "confirmed"
        or datetime.fromisoformat(actual["start"]["dateTime"])
        != datetime.fromisoformat(expected["starts_at"])
        or datetime.fromisoformat(actual["end"]["dateTime"])
        != datetime.fromisoformat(expected["ends_at"])
    ):
        raise SimulationError(
            "Actual Google event must match exact native reservation and interval"
        )
    recipient = delivery.get("customer_recipient_sha256")
    if not isinstance(recipient, str) or not re.fullmatch("[0-9a-f]{64}", recipient):
        raise SimulationError(
            "Independent native notification recipient identity required"
        )
    ids = set()
    for notice in delivery["notifications"]:
        if (
            not _positive_id(notice.get("id"))
            or notice["id"] in ids
            or type(notice.get("attempt")) is not int
            or notice["attempt"] != 1
            or notice.get("run_id") != source["run_id"]
            or notice.get("case_id") != "C48"
            or notice.get("booking_invocation_id") != source["invocation_id"]
            or notice.get("recipient_sha256") != recipient
        ):
            raise SimulationError("Exact owned notification attempt required")
        ids.add(notice["id"])
        message = _external(provider.get_message, notice["provider_message_id"])
        if (
            not isinstance(message, dict)
            or message.get("sid") != notice["provider_message_id"]
            or message.get("status") != "delivered"
            or message.get("direction") not in ("outbound-api", "outbound-reply")
            or not isinstance(message.get("to"), str)
            or fingerprint(message["to"].removeprefix("whatsapp:")) != recipient
        ):
            raise SimulationError(
                "Actual provider notification delivery to owned recipient required"
            )
    return {
        "lookup_sha256": fingerprint(lookup_proof),
        "calendar_sha256": fingerprint(actual),
    }


def _executed_recovery_lookup(run, pre):
    """Actual agent-testing response fields; lookup rows use the native API schema."""
    calls = []
    results = []
    for response in run["agent_responses"]:
        for call in response.get("tool_calls", []):
            if call.get("tool_name") not in (
                "get_customer_appointments",
                "check_availability",
                "get_service_fields",
                "get_required_fields",
            ):
                raise SimulationError("Recovery invoked a mutation or unknown tool")
            if call.get("tool_name") == "get_customer_appointments":
                calls.append(call)
        results.extend(
            r
            for r in response.get("tool_results", [])
            if r.get("tool_name") == "get_customer_appointments"
        )
    if len(calls) != 1 or len(results) != 1:
        raise SimulationError(
            "One executed recovery lookup with paired result required"
        )
    call, result = calls[0], results[0]
    details = call["tool_details"]
    wanted_url = pre["tool_url"].replace(
        "name=book_appointment", "name=get_customer_appointments"
    )
    value = result["result_value"]
    if isinstance(value, str):
        value = json.loads(value)
    value = value.get("result", value)
    rows = value.get("appointments")
    if (
        call.get("type") != "webhook"
        or call.get("tool_has_been_called") is not True
        or details.get("type") != "webhook"
        or details.get("method") != "POST"
        or details.get("url") != wanted_url
        or not isinstance(call.get("request_id"), str)
        or not call["request_id"]
        or call["request_id"] != result.get("request_id")
        or result.get("is_error") is not False
        or value.get("success") is not True
        or not isinstance(rows, list)
        or len(rows) != 1
    ):
        raise SimulationError("Exact executed native recovery HTTP lookup required")
    row = rows[0]
    expected = pre["expected_booking"]
    request = pre["native_booking"]["requests"][0]
    returned = datetime.fromisoformat(row["appointment_datetime"])
    start = datetime.fromisoformat(expected["starts_at"])
    if returned.tzinfo is None:
        returned = returned.replace(tzinfo=start.tzinfo)
    if (
        not _positive_id(row.get("id"))
        or row["id"] != request["id"]
        or returned != start
        or row.get("booking_type") != "appointment"
        or row.get("service_type") != expected["service_type"]
        or type(row.get("duration_minutes")) is not int
        or row["duration_minutes"] != expected["duration_minutes"]
        or row.get("status") != request["status"]
    ):
        raise SimulationError(
            "Recovery lookup does not identify preserved native reservation owner"
        )
    return {
        "provider_request_id": call["request_id"],
        "native_request_id": row["id"],
        "native_reservation_id": pre["native_booking"]["reservations"][0]["id"],
    }
