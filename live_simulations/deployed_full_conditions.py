"""Read-only operational conditions for full cases, separate from live admission.

Every observation executes native SQL and GETs existing provider SIDs. Configuration
and saved receipts cannot establish a condition. Journals retain hashes of private
phones/message bodies; they never send, enroll, opt in, advance clocks or run workers.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .core import SimulationError, fingerprint, number
from .deployed_full_interruption import (
    _external,
    _intent,
    _positive_id,
    _read,
    _same_binding,
)
from .runner import campaign_lock

CASES = frozenset({"C33", "C37", *[f"C{i}" for i in range(38, 46)]})
DESIGNATED_PHONE = "+14242704893"


@dataclass(frozen=True)
class Identity:
    run_id: str
    case_id: str
    attempt: int
    customer_id: int
    request_id: int
    staff_agent_id: int
    other_customer_id: int | None = None
    original_staff_agent_id: int | None = None
    replacement_staff_agent_id: int | None = None

    def validate(self):
        if (
            not isinstance(self.run_id, str)
            or not re.fullmatch("[0-9a-f]{32}", self.run_id)
            or not isinstance(self.case_id, str)
            or self.case_id not in CASES
            or type(self.attempt) is not int
            or self.attempt < 1
            or any(
                not _positive_id(getattr(self, k))
                for k in ("customer_id", "request_id", "staff_agent_id")
            )
            or any(
                getattr(self, k) is not None and not _positive_id(getattr(self, k))
                for k in (
                    "other_customer_id",
                    "original_staff_agent_id",
                    "replacement_staff_agent_id",
                )
            )
        ):
            raise SimulationError("Exact owned operational condition identity required")


def _phone(value):
    if not isinstance(value, str):
        raise SimulationError("Native phone identity unavailable")
    value = value.removeprefix("whatsapp:")
    if not re.fullmatch(r"\+?[0-9 ().-]+", value):
        raise SimulationError("Native phone identity unavailable")
    digits = re.sub(r"\D", "", value)
    if value.startswith("+"):
        canonical = "+" + digits
    elif len(digits) == 10:
        canonical = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        canonical = "+" + digits
    else:
        raise SimulationError("Native phone country identity unavailable")
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", canonical):
        raise SimulationError("Native phone identity unavailable")
    return fingerprint(canonical)


def _timestamp(value):
    if type(value) in (int, float):
        return float(number(value, positive=True))
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(value)
    else:
        raise SimulationError("Native timestamp unavailable")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SimulationError("Native timestamp timezone unavailable")
    return dt.timestamp()


def _safe_row(row):
    result = {}
    for key, value in row.items():
        if key in ("phone", "phone_number", "recipient_phone", "customer_phone"):
            result[key] = _phone(value) if value is not None else None
        elif key in ("body", "reply"):
            result[key + "_sha256"] = fingerprint(value)
            if isinstance(value, str):
                match = re.fullmatch(
                    r"\s*(CONFIRM|C|YES|ACCEPT|DECLINE|NO)\s+#?(\d+)\s*",
                    value,
                    re.IGNORECASE,
                )
                if match:
                    result["action"] = (
                        "confirm"
                        if match[1].upper() in ("CONFIRM", "C", "YES", "ACCEPT")
                        else "decline"
                    )
                    result["action_request_id"] = int(match[2])
        elif key.endswith("_at") and value is not None:
            result[key] = _timestamp(value)
        elif key == "payload":
            result["payload_sha256"] = fingerprint(value)
            details = value.get("details", {}) if isinstance(value, dict) else {}
            result["voice_bypass"] = bool(
                isinstance(value, dict)
                and (
                    value.get("bypass_quiet_hours")
                    or value.get("triggered_by")
                    in (
                        "voice_agent",
                        "voice_tool",
                        "customer",
                        "telephony_voice_assistant",
                    )
                    or details.get("bypass_quiet_hours")
                    or details.get("triggered_by")
                    in (
                        "voice_agent",
                        "voice_tool",
                        "customer",
                        "telephony_voice_assistant",
                    )
                )
            )
        elif key == "agent_id" and isinstance(value, str) and value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value
    return result


class Conditions:
    """Inject trusted read owners; optional monotonic clock is for offline capture tests."""

    def __init__(self, root, *, reader, provider, monotonic=time.monotonic,
                 business_timezone="America/New_York"):
        if (
            not callable(getattr(reader, "rows", None))
            or not callable(getattr(provider, "get_message", None))
            or not callable(monotonic)
        ):
            raise SimulationError(
                "Independent native SQL and provider GET readers required"
            )
        self.root = Path(root)
        self.reader = reader
        self.provider = provider
        self.monotonic = monotonic
        try:
            self.business_timezone = str(ZoneInfo(business_timezone))
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise SimulationError("Native business timezone unavailable") from None

    def _paths(self, binding):
        binding.validate()
        folder = self.root / binding.run_id
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.is_symlink():
            raise SimulationError("Owned observation folder required")
        return folder, f"{binding.case_id}-{binding.attempt}-conditions"

    def _rows(self, key, statement, params=()):
        rows = _external(
            self.reader.rows, "SELECT /* conditions:" + key + " */ " + statement, params
        )
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise SimulationError("Native condition rows unavailable")
        normalized = [_safe_row(row) for row in rows]
        for row in normalized:
            if any(
                value is not None and not _positive_id(value)
                for key, value in row.items()
                if key == "id"
                or key
                in (
                    "customer_id",
                    "request_id",
                    "staff_agent_id",
                    "appointment_id",
                    "agent_id",
                )
            ):
                raise SimulationError(
                    "Native condition relational identity unavailable"
                )
        return normalized

    def _snapshot(self, b):
        # The business-naive deadline writer differs from database CURRENT_TIMESTAMP
        # and from UTC-naive queued-send timestamps. Preserve their actual contracts.
        business_zone = self.business_timezone.replace("'", "''")
        customer_ids = [b.customer_id] + (
            [b.other_customer_id] if b.other_customer_id else []
        )
        staff_ids = [b.staff_agent_id] + [
            i for i in (b.original_staff_agent_id, b.replacement_staff_agent_id) if i
        ]
        result = {
            "clock": self._rows(
                "clock",
                "EXTRACT(EPOCH FROM clock_timestamp())::double precision AS observed_at_unix",
            ),
            "customers": self._rows(
                "customers",
                "id,phone,sms_opt_in FROM customers WHERE id=ANY(%s) ORDER BY id",
                (customer_ids,),
            ),
            "requests": self._rows(
                "requests",
                f"id,customer_id,staff_agent_id,service_type,status,confirmation_status,escalation_status,escalation_reason,confirmation_cutoff_at AT TIME ZONE '{business_zone}' AS confirmation_cutoff_at,confirmed_at::text AS confirmed_at_wall_clock FROM service_requests WHERE id=%s",
                (b.request_id,),
            ),
            "staff": self._rows(
                "staff",
                "id,phone_number,is_active FROM staff_agents WHERE id=ANY(%s) ORDER BY id",
                (staff_ids,),
            ),
            "whitelist": self._rows(
                "whitelist",
                "w.phone_number,w.whatsapp_onboarded,w.twilio_verified FROM sms_whitelist w JOIN customers c ON c.phone=w.phone_number WHERE c.id=%s",
                (b.customer_id,),
            ),
            "logs": self._rows(
                "logs",
                "id,appointment_id,recipient_phone,recipient_type,status,error_code,twilio_message_sid,scheduled_send_at AT TIME ZONE 'UTC' AS scheduled_send_at,sent_at AT TIME ZONE current_setting('TimeZone') AS sent_at,created_at AT TIME ZONE current_setting('TimeZone') AS created_at FROM sms_log WHERE appointment_id=%s ORDER BY id",
                (b.request_id,),
            ),
            "messages": self._rows(
                "messages",
                "m.id,c.context_appointment_id AS appointment_id,c.customer_phone,m.direction,m.body,m.twilio_message_sid,m.created_at AT TIME ZONE current_setting('TimeZone') AS created_at FROM sms_messages m JOIN sms_conversations c ON c.id=m.conversation_id WHERE c.context_appointment_id=%s ORDER BY m.id",
                (b.request_id,),
            ),
            "audit": self._rows(
                "audit",
                "id,request_id,event_type,triggered_by,metadata->>'agent_id' AS agent_id,metadata->>'phone' AS phone,metadata->>'reply' AS reply,created_at AT TIME ZONE current_setting('TimeZone') AS created_at FROM service_request_audit_log WHERE request_id=%s ORDER BY id",
                (b.request_id,),
            ),
            "outbox": self._rows(
                "outbox",
                "id,request_id,event_type,status,payload,created_at AT TIME ZONE current_setting('TimeZone') AS created_at,updated_at AT TIME ZONE current_setting('TimeZone') AS updated_at FROM outbox_notifications WHERE request_id=%s ORDER BY id",
                (b.request_id,),
            ),
            "policy": self._rows(
                "policy",
                "quiet_hours_enabled,quiet_start_time::text,quiet_end_time::text FROM sms_config ORDER BY id",
            ),
            "qualifications": self._rows(
                "qualifications",
                "ssa.staff_agent_id,s.name AS service_name,a.is_active FROM service_staff_agents ssa JOIN services s ON s.id=ssa.service_id JOIN staff_agents a ON a.id=ssa.staff_agent_id JOIN service_requests sr ON sr.service_type=s.name WHERE sr.id=%s ORDER BY ssa.staff_agent_id",
                (b.request_id,),
            ),
        }
        if len(result["clock"]) != 1:
            raise SimulationError("Native clock unavailable")
        result["observed_at_unix"] = _timestamp(
            result.pop("clock")[0]["observed_at_unix"]
        )
        result["monotonic"] = float(number(_external(self.monotonic)))
        sids = {
            r.get("twilio_message_sid")
            for r in result["logs"] + result["messages"]
            if r.get("twilio_message_sid")
        }
        result["provider_messages"] = []
        if len(sids) > 100:
            raise SimulationError(
                "Owned provider observation scope exceeds bounded reads"
            )
        for sid in sorted(sids):
            if not isinstance(sid, str) or not re.fullmatch("SM[0-9a-fA-F]{32}", sid):
                raise SimulationError("Native provider message SID unavailable")
            raw = _external(self.provider.get_message, sid)
            if (
                not isinstance(raw, dict)
                or raw.get("sid") != sid
                or raw.get("direction")
                not in ("inbound", "outbound-api", "outbound-reply")
                or not isinstance(raw.get("status"), str)
            ):
                raise SimulationError("Provider message identity differs")
            if (
                raw.get("status")
                not in (
                    "accepted",
                    "scheduled",
                    "queued",
                    "sending",
                    "sent",
                    "delivered",
                    "undelivered",
                    "failed",
                    "receiving",
                    "received",
                    "read",
                    "canceled",
                )
                or raw.get("error_code") is not None
                and (type(raw["error_code"]) is not int or raw["error_code"] <= 0)
            ):
                raise SimulationError("Provider message status/code shape unavailable")
            row = {
                "sid": sid,
                "status": raw.get("status"),
                "direction": raw.get("direction"),
                "error_code": str(raw.get("error_code")),
                "from": _phone(raw.get("from")),
                "to": _phone(raw.get("to")),
                "body_sha256": fingerprint(raw.get("body")),
                "date_created": _timestamp(raw.get("date_created")),
            }
            if raw.get("date_sent") is not None:
                row["date_sent"] = _timestamp(raw["date_sent"])
            result["provider_messages"].append(row)
        return result

    def arrange(self, binding):
        """Read-only arrangement: record an owned immutable baseline, never seed it."""
        with campaign_lock(self.root):
            folder, prefix = self._paths(binding)
            value = {"binding": asdict(binding), "snapshot": self._snapshot(binding)}
            _intent(folder / (prefix + "-baseline.json"), value)
            return {
                "source_supported": True,
                "native_ready": False,
                "baseline_sha256": fingerprint(value),
            }

    def observe(self, binding):
        with campaign_lock(self.root):
            folder, prefix = self._paths(binding)
            baseline = _read(folder / (prefix + "-baseline.json"))
            if not _same_binding(baseline.get("binding"), asdict(binding)):
                raise SimulationError("Operational journal ownership differs")
            previous = baseline
            sequence = 1
            while (folder / f"{prefix}-{sequence}.json").exists():
                prior = _read(folder / f"{prefix}-{sequence}.json")
                if prior.get("previous_sha256") != fingerprint(previous):
                    raise SimulationError("Operational observation chain differs")
                previous = prior
                sequence += 1
            try:
                snapshot = self._snapshot(binding)
            except Exception:  # noqa: BLE001 - fixed diagnostics only
                report = self._report(
                    ["Independent native/provider condition observation unavailable"]
                )
                value = {
                    "binding": asdict(binding),
                    "previous_sha256": fingerprint(previous),
                    "snapshot": previous["snapshot"],
                    "report": report,
                }
                _intent(folder / f"{prefix}-{sequence}.json", value)
                return report
            old = previous["snapshot"]
            if (
                snapshot["observed_at_unix"] < old["observed_at_unix"]
                or snapshot["monotonic"] < old["monotonic"]
            ):
                raise SimulationError("Native or monotonic clock moved backwards")
            # Advancing wall time must also have elapsed in this observer process.
            if (
                snapshot["observed_at_unix"] - old["observed_at_unix"]
                > snapshot["monotonic"] - old["monotonic"] + 5
            ):
                raise SimulationError(
                    "Native clock advanced without real monotonic elapsed time"
                )
            report = self._checks(binding, baseline["snapshot"], snapshot)
            value = {
                "binding": asdict(binding),
                "previous_sha256": fingerprint(previous),
                "snapshot": snapshot,
                "report": report,
            }
            _intent(folder / f"{prefix}-{sequence}.json", value)
            return report

    def checks(self, binding):
        """Runner hook: always reobserve trusted sources; saved reports are not proof."""
        return self.observe(binding)

    def _checks(self, b, before, after):
        blockers = []
        customers = {r["id"]: r for r in after["customers"]}
        requests = after["requests"]
        staff = {r["id"]: r for r in after["staff"]}
        if (
            b.customer_id not in customers
            or len(requests) != 1
            or requests[0].get("id") != b.request_id
        ):
            blockers.append("Exact native customer/request scope unavailable")
            return self._report(blockers)
        customer = customers[b.customer_id]
        request = requests[0]
        if b.case_id != "C33" and (
            request.get("customer_id") != b.customer_id
            or request.get("status") == "cancelled"
        ):
            blockers.append("Owned booking customer/status identity differs")
        before_ids = {r["id"] for r in before["logs"]}
        logs = [
            r
            for r in after["logs"]
            if r["id"] not in before_ids and r.get("appointment_id") == b.request_id
        ]
        customer_logs = [
            r
            for r in logs
            if r.get("recipient_type") == "customer"
            and r.get("recipient_phone") == customer["phone"]
        ]
        provider = {r["sid"]: r for r in after["provider_messages"]}
        if before["policy"] != after["policy"]:
            blockers.append("Native messaging policy changed during observation")
        if b.case_id == "C33":
            other = customers.get(b.other_customer_id)
            if (
                not other
                or b.other_customer_id == b.customer_id
                or other["phone"] == customer["phone"]
                or request.get("customer_id") != b.other_customer_id
            ):
                blockers.append(
                    "Distinct native customer and separate phone ownership required"
                )
            if before["requests"] != requests:
                blockers.append("Other customer booking changed")
        elif b.case_id == "C37":
            matching = []
            for row in customer_logs:
                message = provider.get(row.get("twilio_message_sid"))
                native_code = str(row.get("error_code", ""))
                if (
                    row.get("status") in ("FAILED", "UNDELIVERED")
                    and message
                    and message["to"] == customer["phone"]
                    and message["direction"] in ("outbound-api", "outbound-reply")
                    and message["status"] in ("failed", "undelivered")
                    and native_code.isdigit()
                    and int(native_code) > 0
                    and message["error_code"] == native_code
                ):
                    matching.append(row)
            if len(matching) != 1:
                blockers.append(
                    "New exact native notification attempt and independently GET-read provider rejection required"
                )
        elif b.case_id in ("C38", "C39"):
            code = "63015" if b.case_id == "C38" else "63016"
            failures = [
                provider.get(r.get("twilio_message_sid"))
                for r in customer_logs
                if r.get("status") in ("FAILED", "UNDELIVERED")
            ]
            if not any(
                p
                and p["to"] == customer["phone"]
                and p["direction"].startswith("outbound")
                and p["status"] in ("failed", "undelivered")
                and p["error_code"] == code
                for p in failures
            ):
                blockers.append(
                    "Exact provider rejection from independently GET-read owned message required"
                )
            if b.case_id == "C38" and (
                not after["whitelist"]
                or any(
                    r.get("phone_number") != customer["phone"]
                    or r.get("whatsapp_onboarded") is not False
                    for r in after["whitelist"]
                )
            ):
                blockers.append(
                    "Actual unenrolled recipient unavailable; enrolled handset cannot substitute"
                )
            if b.case_id == "C39":
                inbound = [
                    p
                    for p in provider.values()
                    if p["direction"] == "inbound" and p["from"] == customer["phone"]
                ]
                if (
                    not inbound
                    or max(p["date_created"] for p in inbound) + 86400
                    > after["observed_at_unix"]
                ):
                    blockers.append(
                        "Provider-bound closed conversation window unavailable"
                    )
        elif b.case_id == "C40":
            if any(
                row.get("phone_number") == customer["phone"] for row in after["staff"]
            ):
                blockers.append(
                    "Shared staff/customer handset cannot prove isolated recipient opt-out"
                )
            old = next((r for r in before["customers"] if r["id"] == b.customer_id), {})
            if (
                old.get("sms_opt_in") is not False
                or customer.get("sms_opt_in") is not False
                or not customer_logs
                or any(
                    r.get("status") != "SKIPPED_OPT_OUT" or r.get("twilio_message_sid")
                    for r in customer_logs
                )
            ):
                blockers.append(
                    "Owned opt-out and new native suppression without provider send required"
                )
        elif b.case_id == "C41":
            blockers.append(
                "Voice/customer quiet-hours bypass policy requires owner decision"
            )
            if any(r.get("voice_bypass") for r in before["outbox"] + after["outbox"]):
                blockers.append(
                    "Voice/customer quiet-hours bypass policy requires owner decision"
                )
            queued = [
                r
                for r in before["logs"]
                if r.get("status") == "QUEUED"
                and r.get("scheduled_send_at")
                and r["scheduled_send_at"] > before["observed_at_unix"]
            ]
            released = []
            for row in queued:
                current = next((r for r in after["logs"] if r["id"] == row["id"]), {})
                p = provider.get(current.get("twilio_message_sid"))
                if (
                    current.get("status") in ("SENT", "DELIVERED")
                    and p
                    and p["status"] == "delivered"
                    and p.get("date_sent", 0) >= row["scheduled_send_at"]
                    and after["observed_at_unix"] >= row["scheduled_send_at"]
                ):
                    released.append(row)
            if len(queued) != 1 or len(released) != 1:
                blockers.append(
                    "Same native queued message must release once after actual deadline"
                )
        else:
            blockers.extend(self._staff(b, before, after, request, staff, provider))
        return self._report(blockers)

    @staticmethod
    def _report(blockers):
        return {
            "source_supported": True,
            "implementation_status": "implemented_offline",
            "evidence_complete": not blockers,
            "native_ready": False,
            "native_acceptance": "unverified",
            "blockers": blockers,
        }

    def _staff(self, b, before, after, request, staff, provider):
        blockers = []
        audit = [
            row
            for row in after["audit"]
            if row.get("id") not in {item.get("id") for item in before["audit"]}
            and row.get("created_at", 0) >= before["observed_at_unix"]
        ]
        pending = before["requests"][0] if before["requests"] else {}
        cutoff = pending.get("confirmation_cutoff_at")
        if b.case_id in ("C42", "C43") and (
            pending.get("staff_agent_id")
            != (b.original_staff_agent_id or b.staff_agent_id)
            or pending.get("confirmation_status") != "pending_agent_confirmation"
            or not cutoff
            or cutoff <= before["observed_at_unix"]
        ):
            blockers.append("Exact active original-staff pending offer window required")
        original = b.original_staff_agent_id or b.staff_agent_id
        source = staff.get(original)
        if not source:
            return ["Exact native original staff identity unavailable"]
        offers = [
            r
            for r in before["logs"]
            if r.get("recipient_type") == "agent"
            and r.get("recipient_phone") == source["phone_number"]
            and r.get("appointment_id") == b.request_id
            and r.get("twilio_message_sid")
        ]
        offer_proofs = [
            p
            for row in offers
            for p in before["provider_messages"]
            if p["sid"] == row["twilio_message_sid"]
            and p["direction"] in ("outbound-api", "outbound-reply")
            and p["to"] == source["phone_number"]
            and p["status"] in ("sent", "delivered")
            and any(
                r.get("id") == row["id"]
                and r.get("twilio_message_sid") == row["twilio_message_sid"]
                for r in after["logs"]
            )
        ]
        if len(offer_proofs) != 1:
            blockers.append(
                "Exact independently GET-read native original offer required"
            )
        if b.case_id == "C44":
            if any(
                r.get("staff_agent_id") != original and r.get("is_active") is True
                for r in after["qualifications"]
            ):
                blockers.append(
                    "Qualified replacement remains available; no-replacement prerequisite unproven"
                )
            previous = before["requests"][0] if before["requests"] else {}
            cutoff = previous.get("confirmation_cutoff_at")
            if (
                not cutoff
                or cutoff <= before["observed_at_unix"]
                or after["observed_at_unix"] < cutoff
                or request.get("escalation_status") != "escalated"
                or request.get("escalation_reason") != "TIMEOUT_NO_RESPONSE"
                or not any(
                    r.get("request_id") == b.request_id
                    and r.get("event_type") == "ESCALATION_TRIGGERED"
                    and r.get("created_at", 0) >= cutoff
                    for r in audit
                )
            ):
                blockers.append(
                    "Actual native offer timeout and later worker escalation required"
                )
            return blockers
        action = "decline" if b.case_id == "C43" else "confirm"
        messages = [
            r
            for r in after["messages"]
            if r.get("direction") == "inbound"
            and r.get("action") == action
            and r.get("action_request_id") == b.request_id
            and r.get("customer_phone") == source["phone_number"]
            and r["id"] not in {x["id"] for x in before["messages"]}
        ]
        paired = []
        for row in messages:
            p = provider.get(row.get("twilio_message_sid"))
            if (
                p
                and p["direction"] == "inbound"
                and p["from"] == source["phone_number"]
                and p["body_sha256"] == row.get("body_sha256")
                and before["observed_at_unix"]
                <= p["date_created"]
                <= after["observed_at_unix"]
                and (b.case_id == "C45" or cutoff and p["date_created"] <= cutoff)
            ):
                paired.append(row)
        if len(paired) != 1:
            blockers.append(
                "Actual targeted original-staff provider inbound and native message required"
            )
        offers = [
            r
            for r in before["logs"]
            if r.get("recipient_type") == "agent"
            and r.get("recipient_phone") == source["phone_number"]
            and r.get("appointment_id") == b.request_id
            and r.get("twilio_message_sid")
        ]
        if not offers:
            blockers.append("Native original offer with owned provider SID required")
        event = "AGENT_DECLINED" if action == "decline" else "AGENT_CONFIRMED"
        if b.case_id == "C45" and not any(
            r.get("event_type") in ("AGENT_CONFIRM_REJECTED", "AGENT_CONFIRM_IGNORED")
            and r.get("request_id") == b.request_id
            and r.get("agent_id") == original
            and r.get("phone") == source["phone_number"]
            and paired
            and r.get("reply_sha256") == paired[0].get("body_sha256")
            for r in audit
        ):
            blockers.append("Native explicit late-original rejection audit unavailable")
        if b.case_id != "C45" and not any(
            r.get("event_type") == event
            and r.get("request_id") == b.request_id
            and r.get("agent_id") == original
            and r.get("phone") == source["phone_number"]
            and paired
            and r.get("reply_sha256") == paired[0].get("body_sha256")
            for r in audit
        ):
            blockers.append(
                "Native staff transition audit must match provider-backed reply"
            )
        if b.case_id == "C42" and (
            request.get("confirmation_status") != "confirmed"
            or request.get("staff_agent_id") != original
        ):
            blockers.append("Original technician confirmation not durably assigned")
        if b.case_id in ("C43", "C45"):
            replacement = staff.get(b.replacement_staff_agent_id)
            if (
                not replacement
                or replacement.get("is_active") is not True
                or replacement["id"] == original
                or replacement["phone_number"] == source["phone_number"]
                or request.get("staff_agent_id") != replacement["id"]
                or not any(
                    r.get("staff_agent_id") == replacement["id"]
                    and r.get("service_name") == request.get("service_type")
                    for r in after["qualifications"]
                )
            ):
                blockers.append(
                    "Distinct qualified replacement and phone identity required"
                )
            if b.case_id == "C45" and (
                before["requests"] != after["requests"]
                or request.get("confirmation_status") != "confirmed"
            ):
                blockers.append(
                    "Late original reply must preserve confirmed replacement exactly"
                )
        return blockers


class TwilioMessages:
    """Actual Twilio REST GET transport; authentication is injected, never loaded.

    No send, enrollment, webhook replay or configuration method is exposed.
    The caller owns an authenticated HTTP client and separately approved runtime.
    """

    def __init__(self, account_sid, *, client, auth):
        if (
            not isinstance(account_sid, str)
            or not re.fullmatch("AC[0-9a-fA-F]{32}", account_sid)
            or not callable(getattr(client, "get", None))
        ):
            raise SimulationError(
                "Exact Twilio account and read-only transport required"
            )
        self.account_sid = account_sid
        self.client = client
        self.auth = auth

    def get_message(self, sid):
        if not isinstance(sid, str) or not re.fullmatch("SM[0-9a-fA-F]{32}", sid):
            raise SimulationError("Exact native Twilio message SID required")

        def get():
            response = self.client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages/{sid}.json",
                auth=self.auth,
                follow_redirects=False,
                timeout=10,
            )
            response.raise_for_status()
            value = response.json()
            if (
                not isinstance(value, dict)
                or value.get("account_sid") != self.account_sid
                or value.get("sid") != sid
            ):
                raise SimulationError("Twilio account/message identity differs")
            return value

        return _external(get)
