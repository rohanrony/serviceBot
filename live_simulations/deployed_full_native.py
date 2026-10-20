"""Compiled native readers for the full adapter, with no default execution.

All SQL delegates to the existing read-only medium owner. Calendar credentials
are read/decrypted for an authenticated GET only: no refresh, writes or fallback
credentials exist. Source support and native admission remain separate.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit
from zoneinfo import ZoneInfo

from . import deployed_medium as medium
from .core import SimulationError, fingerprint, number
from .deployed_full_conditions import (
    CASES,
    Conditions,
    Identity,
    TwilioMessages,
    _phone,
    _timestamp,
)
from .deployed_full_interruption import (
    Binding,
    _booking,
    _context,
    _external,
    _intent,
    _positive_id,
    _read,
    _same_binding,
)


def _canonical_phone(value):
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9 ().-]+", value):
        raise SimulationError("Native telephone identity unavailable")
    digits = re.sub(r"\D", "", value)
    if value.startswith("+"):
        result = "+" + digits
    elif len(digits) == 10:
        result = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        result = "+" + digits
    else:
        raise SimulationError("Native telephone country identity unavailable")
    _phone(result)
    return result


class NativeReader:
    def __init__(self, adapter):
        self.adapter = adapter

    def rows(self, statement, params=()):
        if (
            not isinstance(statement, str)
            or not re.match(r"^\s*SELECT\b", statement, re.IGNORECASE)
            or ";" in statement.rstrip().rstrip(";")
            or re.search(
                r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|REVOKE|TRUNCATE|CALL|EXECUTE|COPY|SET|RESET)\b",
                statement,
                re.IGNORECASE,
            )
        ):
            raise SimulationError(
                "Native bridge accepts fixed SELECT observations only"
            )
        rows = _external(medium._read, self.adapter.config, statement, params)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SimulationError("Native bridge rows unavailable")
        return [
            {
                key: _canonical_phone(value)
                if key in ("phone", "phone_number", "customer_phone", "recipient_phone")
                and value is not None
                else value
                for key, value in row.items()
            }
            for row in rows
        ]

    def request_rows(self, ids):
        if not isinstance(ids, (list, tuple, set)) or any(
            not _positive_id(i) for i in ids
        ):
            raise SimulationError("Exact native request observation IDs required")
        return _external(medium._request_rows, self.adapter.config, ids)


def _rows(reader, key, statement, params=()):
    value = _external(
        reader.rows, "SELECT /* native:" + key + " */ " + statement, params
    )
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise SimulationError("Native bridge rows unavailable")
    return value


def _now(reader):
    rows = _rows(
        reader,
        "clock",
        "EXTRACT(EPOCH FROM clock_timestamp())::double precision AS now_unix",
    )
    if len(rows) != 1 or type(rows[0].get("now_unix")) not in (int, float):
        raise SimulationError("Native database clock unavailable")
    return float(number(rows[0]["now_unix"], positive=True))


def _decrypt(value):
    # Existing cipher owner is used only when an explicit runtime actually reads.
    from serviceBot.services.encryption import decrypt_key

    return decrypt_key(value)


class GoogleEvents:
    """Authenticated event GET on one native staff account's actual primary calendar."""

    def __init__(self, reader, *, client, staff_agent_id, decrypt=_decrypt):
        if (
            not _positive_id(staff_agent_id)
            or not callable(getattr(client, "get", None))
            or not callable(decrypt)
        ):
            raise SimulationError(
                "Exact native staff and read-only Google transport required"
            )
        self.reader = reader
        self.client = client
        self.staff_agent_id = staff_agent_id
        self.decrypt = decrypt

    def account(self):
        rows = _rows(
            self.reader,
            "google_account",
            "agent_id,provider,google_account_id,email,access_token,expires_at,granted_scopes FROM user_google_accounts WHERE agent_id=%s AND provider=%s",
            (self.staff_agent_id, "google"),
        )
        now = _now(self.reader)
        if (
            len(rows) != 1
            or type(rows[0].get("agent_id")) is not int
            or rows[0]["agent_id"] != self.staff_agent_id
            or rows[0].get("provider") != "google"
            or not rows[0].get("google_account_id")
            or not rows[0].get("email")
            or not isinstance(rows[0].get("access_token"), str)
            or not rows[0]["access_token"]
            or number(rows[0].get("expires_at")) <= number(now) + 60
        ):
            raise SimulationError(
                "Native Google account identity or unexpired token unavailable; refresh is forbidden"
            )
        scopes = set(str(rows[0].get("granted_scopes", "")).split())
        if not scopes & {
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        }:
            raise SimulationError("Native Google calendar read scope unavailable")
        return rows[0]

    def get_calendar_event(self, calendar_id, event_id):
        if (
            calendar_id != "primary"
            or not isinstance(event_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,1024}", event_id)
        ):
            raise SimulationError(
                "Google observation requires native primary calendar and exact event ID"
            )
        account = self.account()
        token = _external(self.decrypt, account["access_token"])
        if (
            not isinstance(token, str)
            or not token.strip()
            or token.startswith("dummy_")
        ):
            raise SimulationError("Real unexpired Google token unavailable")

        def get():
            response = self.client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events/"
                + quote(event_id, safe=""),
                headers={"Authorization": "Bearer " + token},
                follow_redirects=False,
                timeout=10,
            )
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict) or value.get("id") != event_id:
                raise SimulationError("Google event identity differs")
            return value

        return _external(get)

    def permissions(self):
        """Read only list metadata, never original event bodies or a write probe."""
        account = self.account()
        token = _external(self.decrypt, account["access_token"])
        if (
            not isinstance(token, str)
            or not token.strip()
            or token.startswith("dummy_")
        ):
            raise SimulationError("Real unexpired Google token unavailable")

        def get():
            response = self.client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                params={"maxResults": 1, "fields": "kind,accessRole"},
                headers={"Authorization": "Bearer " + token},
                follow_redirects=False,
                timeout=10,
            )
            response.raise_for_status()
            value = response.json()
            if (
                not isinstance(value, dict)
                or value.get("kind") != "calendar#events"
                or value.get("accessRole") not in ("reader", "writer", "owner")
            ):
                raise SimulationError(
                    "Actual primary calendar read permission unavailable"
                )
            return {
                "staff_agent_id": self.staff_agent_id,
                "calendar_id": "primary",
                "read": True,
                "write": value["accessRole"] in ("writer", "owner")
                and bool(
                    set(str(account.get("granted_scopes", "")).split())
                    & {
                        "https://www.googleapis.com/auth/calendar",
                        "https://www.googleapis.com/auth/calendar.events",
                    }
                ),
                "account_sha256": fingerprint(account["google_account_id"]),
            }

        return _external(get)


class NativeTwilio(TwilioMessages):
    def permissions(self):
        def get():
            response = self.client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}.json",
                auth=self.auth,
                follow_redirects=False,
                timeout=10,
            )
            response.raise_for_status()
            value = response.json()
            if (
                not isinstance(value, dict)
                or value.get("sid") != self.account_sid
                or value.get("status") != "active"
            ):
                raise SimulationError("Actual Twilio account permission unavailable")
            return {"account_sha256": fingerprint(self.account_sid), "active": True}

        return _external(get)

    def latest_inbound(self, phone):
        canonical = _canonical_phone(phone)

        def get():
            response = self.client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json",
                params={"From": "whatsapp:" + canonical, "PageSize": 1},
                auth=self.auth,
                follow_redirects=False,
                timeout=10,
            )
            response.raise_for_status()
            value = response.json()
            rows = value.get("messages") if isinstance(value, dict) else None
            if not isinstance(rows, list) or len(rows) != 1:
                raise SimulationError(
                    "Latest actual WhatsApp inbound timestamp unavailable"
                )
            message = rows[0]
            if (
                message.get("account_sid") != self.account_sid
                or message.get("direction") != "inbound"
                or message.get("from") != "whatsapp:" + canonical
                or not isinstance(message.get("sid"), str)
                or not re.fullmatch("SM[0-9a-fA-F]{32}", message["sid"])
            ):
                raise SimulationError(
                    "Actual WhatsApp inbound account/phone scope differs"
                )
            return {
                "sid": message["sid"],
                "received_at_unix": _timestamp(message["date_created"]),
                "customer_phone_sha256": _phone(canonical),
            }

        return _external(get)


class CompositeProvider:
    """Existing ElevenLabs owner plus scoped native read-only downstream providers."""

    def __init__(self, elevenlabs, *, google=None, twilio=None):
        self.elevenlabs = elevenlabs
        self.google = google
        self.twilio = twilio

    def get(self, invocation_id):
        return _external(self.elevenlabs.get, invocation_id)

    def cancel(self, invocation_id):
        return _external(self.elevenlabs.cancel, invocation_id)

    def get_calendar_event(self, calendar_id, event_id):
        if self.google is None:
            raise SimulationError(
                "Authenticated native Google GET observer unavailable"
            )
        return self.google.get_calendar_event(calendar_id, event_id)

    def get_message(self, sid):
        if self.twilio is None:
            raise SimulationError(
                "Authenticated native Twilio GET observer unavailable"
            )
        return self.twilio.get_message(sid)


class C48Observers:
    """Native row compilation around the coordinator's immutable exact binding."""

    def __init__(self, adapter, *, identity, expected_booking, reader=None):
        probe = Binding(**identity, invocation_id="preparation")
        probe.validate()
        self.adapter = adapter
        self.identity = dict(identity)
        self.expected = dict(expected_booking)
        self.reader = reader or NativeReader(adapter)
        if (
            self.identity["run_id"] != adapter.campaign.manifest.get("run_id")
            or self.identity["agent_id"]
            != adapter.campaign.manifest.get("campaign_agent_id")
            or self.expected.get("service_type")
            != adapter.state.get("services", {}).get("oil", {}).get("name")
        ):
            raise SimulationError(
                "C48 native observers require exact owned campaign oil service"
            )

    def _customer(self):
        rows = _rows(
            self.reader,
            "customer",
            "id,phone FROM customers WHERE id=%s",
            (self.expected["customer_id"],),
        )
        if (
            len(rows) != 1
            or type(rows[0].get("id")) is not int
            or rows[0]["id"] != self.expected["customer_id"]
        ):
            raise SimulationError("Exact native C48 customer unavailable")
        _phone(rows[0]["phone"])
        return rows[0]

    def _customer_requests(self):
        return _rows(
            self.reader,
            "baseline_requests",
            "id,customer_id,service_type,status,booking_type,booking_time,duration_minutes,staff_agent_id FROM service_requests WHERE customer_id=%s ORDER BY id",
            (self.expected["customer_id"],),
        )

    def baseline(self):
        self.adapter._guard()
        customer = self._customer()
        requests = self._customer_requests()
        reservations = _rows(
            self.reader,
            "baseline_reservations",
            "r.id,r.service_request_id FROM appointment_reservations r JOIN service_requests s ON s.id=r.service_request_id WHERE s.customer_id=%s ORDER BY r.id",
            (customer["id"],),
        )
        notes = _rows(
            self.reader,
            "history_notes",
            "id FROM crm_notes WHERE customer_id=%s ORDER BY id",
            (customer["id"],),
        )
        events = _rows(
            self.reader,
            "history_events",
            "id FROM webhook_events WHERE provider='elevenlabs' ORDER BY id",
        )
        if any(
            not _positive_id(row.get("id"))
            for row in requests + reservations + notes + events
        ):
            raise SimulationError("Native C48 baseline relational IDs unavailable")
        active = [
            r for r in requests if r.get("status") not in ("cancelled", "completed")
        ]
        return {
            "source": "native_postgresql",
            "customer_id": customer["id"],
            "observed_at_unix": _now(self.reader),
            "request_ids": [r["id"] for r in requests],
            "reservation_ids": [r["id"] for r in reservations],
            "active_request_ids": [
                r["id"]
                for r in active
                if r.get("service_type") == self.expected["service_type"]
            ],
            "active_scope": {
                "customer_id": customer["id"],
                "service_type": self.expected["service_type"],
            },
            "original_active_request_ids": [r["id"] for r in active],
            "original_request_sha256_by_id": {
                str(r["id"]): fingerprint(medium._serial(r)) for r in requests
            },
            "customer_phone_sha256": _phone(customer["phone"]),
            "baseline_note_ids": [r["id"] for r in notes],
            "baseline_event_ids": [r["id"] for r in events],
        }

    def source_binding(self):
        path = (
            Path(self.adapter.campaign.folder)
            / f"C48-{self.identity['attempt']}-interruption-journal.json"
        )
        journal = _read(path)
        values = journal.get("binding")
        if not isinstance(values, dict):
            raise SimulationError("Owned C48 source journal unavailable")
        binding = Binding(**values)
        binding.validate()
        if not _same_binding(
            {k: v for k, v in values.items() if k != "invocation_id"}, self.identity
        ):
            raise SimulationError("Native C48 observer source ownership differs")
        return binding, _context(Path(self.adapter.campaign.root), binding)[1]

    def _iso(self, value):
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        zone = ZoneInfo(self.adapter.config["app_config"]["business_timezone"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
        return dt.astimezone(zone).isoformat()

    def booking(self):
        self.adapter._guard()
        binding, journal = self.source_binding()
        baseline = journal["baseline"]
        requests = self._customer_requests()
        original = baseline.get("original_request_sha256_by_id", {})
        if any(
            str(row["id"]) in original
            and fingerprint(medium._serial(row)) != original[str(row["id"])]
            for row in requests
        ):
            raise SimulationError("Original customer request changed during C48")
        if set(original) - {str(r["id"]) for r in requests}:
            raise SimulationError("Original customer request disappeared during C48")
        ids = [
            r["id"]
            for r in requests
            if r["id"] not in baseline["request_ids"]
            and r.get("service_type") == self.expected["service_type"]
        ]
        if len(ids) != 1 or set(ids) & set(self.adapter.original_ids):
            raise SimulationError("Exactly one new owned C48 booking required")
        rows = _external(self.reader.request_rows, ids)
        if (
            len(rows) != 1
            or rows[0].get("id") != ids[0]
            or rows[0].get("customer_id") != self.expected["customer_id"]
        ):
            raise SimulationError("Native C48 request/reservation join unavailable")
        reservations = _rows(
            self.reader,
            "reservations",
            "id,service_request_id,staff_agent_id,status,starts_at,ends_at,calendar_event_id,calendar_integration_status FROM appointment_reservations WHERE service_request_id=%s ORDER BY id",
            (ids[0],),
        )
        reservations = [r for r in reservations if r.get("status") == "ACTIVE"]
        segments = _rows(
            self.reader,
            "segments",
            "p.reservation_id,p.staff_agent_id,p.segment_start FROM appointment_reservation_segments p JOIN appointment_reservations r ON r.id=p.reservation_id WHERE r.service_request_id=%s AND r.status=%s ORDER BY p.segment_start",
            (ids[0], "ACTIVE"),
        )
        row = rows[0]
        observation = {
            "source": "native_postgresql",
            "customer_id": self.expected["customer_id"],
            "requests": [
                {
                    k: row[k]
                    for k in (
                        "id",
                        "customer_id",
                        "service_type",
                        "status",
                        "booking_type",
                        "duration_minutes",
                        "staff_agent_id",
                    )
                }
                | {
                    "booking_start_at": self._iso(row["starts_at"]),
                    "booking_end_at": self._iso(row["ends_at"]),
                }
            ],
            "reservations": [
                {
                    k: r[k]
                    for k in ("id", "service_request_id", "staff_agent_id", "status")
                }
                | {
                    "starts_at": self._iso(r["starts_at"]),
                    "ends_at": self._iso(r["ends_at"]),
                }
                for r in reservations
            ],
            "segments": [
                {k: r[k] for k in ("reservation_id", "staff_agent_id")}
                | {"segment_start": self._iso(r["segment_start"])}
                for r in segments
            ],
        }
        _booking(observation, journal)
        # Only journal ownership of an independently verified new exact effect.
        fresh = _read(Path(self.adapter.campaign.folder) / "manifest.json")
        if (
            fresh.get("run_id") != binding.run_id
            or fresh.get("campaign_agent_id") != binding.agent_id
        ):
            raise SimulationError(
                "Owned coordinator manifest changed before native registration"
            )
        for key in ("invocations", "provider_tests"):
            current = self.adapter.campaign.manifest.get(key, [])
            saved = fresh.get(key, [])
            if not isinstance(current, list) or not isinstance(saved, list):
                raise SimulationError(
                    "Owned coordinator manifest resource lists unavailable"
                )
            self.adapter.campaign.manifest[key] = list(
                dict.fromkeys([*saved, *current])
            )
        self.adapter.owned_ids.update(ids)
        self.adapter.current_ids.update(ids)
        self.adapter._save()
        return observation

    def delivery(self):
        binding, _journal = self.source_binding()
        booking = self.booking()
        customer = self._customer()
        request = booking["requests"][0]
        reservation = booking["reservations"][0]
        rows = _rows(
            self.reader,
            "reservations",
            "id,service_request_id,staff_agent_id,status,starts_at,ends_at,calendar_event_id,calendar_integration_status FROM appointment_reservations WHERE service_request_id=%s ORDER BY id",
            (request["id"],),
        )
        row = next((r for r in rows if r.get("id") == reservation["id"]), None)
        if (
            not row
            or row.get("calendar_integration_status") != "CREATED"
            or not isinstance(row.get("calendar_event_id"), str)
            or not row["calendar_event_id"]
        ):
            raise SimulationError("Native C48 calendar projection remains unverified")
        accounts = _rows(
            self.reader,
            "google_account",
            "agent_id,provider,google_account_id,email,expires_at,granted_scopes FROM user_google_accounts WHERE agent_id=%s AND provider=%s",
            (request["staff_agent_id"], "google"),
        )
        if (
            len(accounts) != 1
            or type(accounts[0].get("agent_id")) is not int
            or accounts[0]["agent_id"] != request["staff_agent_id"]
            or accounts[0].get("provider") != "google"
            or not accounts[0].get("google_account_id")
        ):
            raise SimulationError("Native C48 connected staff account unavailable")
        projection = _rows(
            self.reader,
            "projection",
            "id,request_id,event_type,status,payload FROM outbox_notifications WHERE request_id=%s AND event_type=%s ORDER BY id",
            (request["id"], "calendar_projection"),
        )
        matching = [
            p
            for p in projection
            if p.get("status") == "DELIVERED"
            and p.get("request_id") == request["id"]
            and isinstance(p.get("payload"), dict)
            and p["payload"].get("reservation_id") == reservation["id"]
            and p["payload"].get("agent_id") == request["staff_agent_id"]
            and p["payload"].get("calendar_event_id") == row["calendar_event_id"]
        ]
        if len(matching) != 1:
            raise SimulationError("Exact delivered native projection attempt required")
        messages = _rows(
            self.reader,
            "notifications",
            "id,appointment_id,recipient_type,recipient_phone,status,retry_count,twilio_message_sid FROM sms_log WHERE appointment_id=%s AND recipient_type=%s ORDER BY id",
            (request["id"], "customer"),
        )
        notices = []
        for msg in messages:
            if (
                not _positive_id(msg.get("id"))
                or msg.get("appointment_id") != request["id"]
                or msg.get("recipient_type") != "customer"
                or _phone(msg.get("recipient_phone")) != _phone(customer["phone"])
                or type(msg.get("retry_count")) is not int
                or not isinstance(msg.get("twilio_message_sid"), str)
                or not re.fullmatch("SM[0-9a-fA-F]{32}", msg["twilio_message_sid"])
            ):
                raise SimulationError("Native C48 notification ownership unavailable")
            notices.append(
                {
                    "id": msg["id"],
                    "service_request_id": request["id"],
                    "status": str(msg.get("status", "")).lower(),
                    "provider_message_id": msg["twilio_message_sid"],
                    "recipient_sha256": _phone(msg["recipient_phone"]),
                    "attempt": msg["retry_count"] + 1,
                    "run_id": binding.run_id,
                    "case_id": "C48",
                    "booking_invocation_id": binding.invocation_id,
                }
            )
        if not notices:
            raise SimulationError("Native C48 owned notification unavailable")
        return {
            "source": "native_postgresql",
            "customer_id": customer["id"],
            "service_request_id": request["id"],
            "reservation_id": reservation["id"],
            "customer_recipient_sha256": _phone(customer["phone"]),
            "staff_calendar": {
                "staff_agent_id": request["staff_agent_id"],
                "calendar_id": "primary",
                "account_sha256": fingerprint(accounts[0]["google_account_id"]),
            },
            "calendar_events": [
                {
                    "service_request_id": request["id"],
                    "reservation_id": reservation["id"],
                    "staff_agent_id": request["staff_agent_id"],
                    "starts_at": reservation["starts_at"],
                    "ends_at": reservation["ends_at"],
                    "status": "confirmed",
                    "calendar_id": "primary",
                    "provider_event_id": row["calendar_event_id"],
                    "booking_invocation_id": binding.invocation_id,
                }
            ],
            "notifications": notices,
        }


class NativeBridge:
    def __init__(
        self,
        adapter,
        elevenlabs,
        *,
        reader=None,
        google_client=None,
        twilio_client=None,
        twilio_account_sid=None,
        twilio_auth=None,
        decrypt=_decrypt,
        monotonic=time.monotonic,
        capability_headers=None,
    ):
        self.adapter = adapter
        self.reader = reader or NativeReader(adapter)
        self.elevenlabs = elevenlabs
        self.google_client = google_client
        self.decrypt = decrypt
        self.capability_headers = capability_headers
        self.twilio = (
            NativeTwilio(twilio_account_sid, client=twilio_client, auth=twilio_auth)
            if twilio_client is not None
            else None
        )
        self.conditions = Conditions(
            adapter.campaign.root,
            reader=self.reader,
            provider=CompositeProvider(elevenlabs, twilio=self.twilio),
            monotonic=monotonic,
        )

    def c48_observers(self, *, identity, expected_booking):
        observers = C48Observers(
            self.adapter,
            identity=identity,
            expected_booking=expected_booking,
            reader=self.reader,
        )
        google = (
            GoogleEvents(
                self.reader,
                client=self.google_client,
                staff_agent_id=expected_booking["staff_agent_id"],
                decrypt=self.decrypt,
            )
            if self.google_client is not None
            else None
        )
        provider = CompositeProvider(self.elevenlabs, google=google, twilio=self.twilio)
        return {
            "observe_baseline": observers.baseline,
            "observe_booking": observers.booking,
            "observe_delivery": observers.delivery,
            "provider": provider,
        }

    def _condition_rows(self, customer_id):
        return _rows(
            self.reader,
            "condition_poll",
            "s.id,s.customer_id,s.staff_agent_id,s.service_type,s.confirmation_status,s.confirmation_cutoff_at,s.created_at,c.phone AS customer_phone FROM service_requests s JOIN customers c ON c.id=s.customer_id WHERE c.id=%s AND s.service_type=%s AND s.status<>%s ORDER BY s.id",
            (customer_id, self.adapter.state["services"]["oil"]["name"], "cancelled"),
        )

    def _condition_pre(self, cid):
        record = self.adapter.state.get("full_condition_prepared", {}).get(cid)
        if not isinstance(record, dict):
            raise SimulationError(
                "Condition pre-request observation must precede provider submission"
            )
        path = Path(self.adapter.campaign.folder) / record["journal"]
        value = _read(path)
        if fingerprint(value) != record.get("sha256"):
            raise SimulationError("Condition pre-request journal differs")
        return value

    def _condition_identity(self, cid, values):
        records = self.adapter.state.get("full_condition_bindings", {})
        if cid in records:
            binding = Identity(**records[cid])
            binding.validate()
            return binding
        pre = self._condition_pre(cid)
        if cid == "C33":
            request_id = values.get("other_request_id")
            if request_id not in self.adapter.owned_ids:
                return None
            candidates = _external(self.reader.request_rows, [request_id])
            candidates = [
                r
                for r in candidates
                if r.get("customer_id") == values.get("other_customer_id")
            ]
        else:
            rows = self._condition_rows(pre["customer_id"])
            candidates = [
                r
                for r in rows
                if r.get("id") not in pre["candidate_request_ids"]
                and r.get("id") not in self.adapter.original_ids
                and r.get("customer_id") == pre["customer_id"]
                and r.get("service_type")
                == self.adapter.state["services"]["oil"]["name"]
                and medium._digits(r.get("customer_phone"))
                == medium._digits(values.get("customer_phone"))
            ]
        if not candidates:
            return None
        if len(candidates) != 1:
            raise SimulationError(
                "Condition observation found multiple new owned booking candidates"
            )
        row = candidates[0]
        if row["id"] not in self.adapter.owned_ids:
            register = getattr(self.adapter, "_register", None)
            if not callable(register):
                raise SimulationError(
                    "Native booking ownership registration hook required before conditions"
                )
            _external(register, [row["id"]], values)
        identity = Identity(
            run_id=self.adapter.campaign.manifest["run_id"],
            case_id=cid,
            attempt=pre["attempt"],
            customer_id=pre["customer_id"],
            request_id=row["id"],
            staff_agent_id=row["staff_agent_id"],
            other_customer_id=values.get("other_customer_id"),
            original_staff_agent_id=values.get("original_staff_agent_id"),
            replacement_staff_agent_id=values.get("replacement_staff_agent_id"),
        )
        identity.validate()
        if cid in ("C42", "C43", "C44", "C45"):
            offers = _rows(
                self.reader,
                "condition_offer",
                "l.id,l.appointment_id,l.recipient_type,l.recipient_phone,l.status,l.twilio_message_sid,s.confirmation_status,s.staff_agent_id,s.confirmation_cutoff_at FROM sms_log l JOIN service_requests s ON s.id=l.appointment_id WHERE s.id=%s AND l.recipient_type=%s ORDER BY l.id",
                (identity.request_id, "agent"),
            )
            if not any(
                r.get("appointment_id") == identity.request_id
                and r.get("twilio_message_sid")
                and r.get("status") in ("SENT", "DELIVERED")
                for r in offers
            ):
                return None
            if cid != "C45" and any(
                r.get("confirmation_status") != "pending_agent_confirmation"
                for r in offers
            ):
                raise SimulationError(
                    "Original staff reply preceded immutable offer baseline"
                )
        elif cid == "C41":
            queue = _rows(
                self.reader,
                "condition_queue",
                "id,status,scheduled_send_at FROM sms_log WHERE appointment_id=%s AND status=%s ORDER BY id",
                (identity.request_id, "QUEUED"),
            )
            if not queue:
                return None
        self.adapter.state.setdefault("full_condition_bindings", {})[cid] = asdict(
            identity
        )
        self.adapter._save()
        return identity

    def arrange_conditions(self, cid, values):
        """Call before paid submission; unknown future request IDs stay unbound."""
        self.adapter._guard()
        if cid not in CASES:
            raise SimulationError("Unsupported operational condition case")
        if cid in self.adapter.state.get("full_condition_prepared", {}):
            raise SimulationError(
                "Condition preparation already journaled; resume read-only polling"
            )
        customer_id = medium._identity_id(self.adapter.config)
        staff = self.adapter.config.get("deployed_medium", {}).get("technician_ids", [])
        if not _positive_id(customer_id) or not staff or not _positive_id(staff[0]):
            raise SimulationError(
                "Exact customer and staff identities required before condition preparation"
            )
        attempt = values.get("attempt", 1)
        if type(attempt) is not int or attempt < 1:
            raise SimulationError("Exact condition attempt required")
        # An actual WHERE request_id=0 native read captures customer/policy state
        # before a future request exists. It never stands in for a booking row.
        provisional = SimpleNamespace(
            customer_id=customer_id,
            request_id=0,
            staff_agent_id=staff[0],
            other_customer_id=values.get("other_customer_id"),
            original_staff_agent_id=values.get("original_staff_agent_id"),
            replacement_staff_agent_id=values.get("replacement_staff_agent_id"),
        )
        snapshot = self.conditions._snapshot(provisional)
        rows = self._condition_rows(customer_id)
        value = {
            "run_id": self.adapter.campaign.manifest["run_id"],
            "case_id": cid,
            "attempt": attempt,
            "customer_id": customer_id,
            "candidate_request_ids": [r["id"] for r in rows],
            "snapshot": snapshot,
        }
        name = f"{cid}-{attempt}-condition-pre-request.json"
        _intent(Path(self.adapter.campaign.folder) / name, value)
        self.adapter.state.setdefault("full_condition_prepared", {})[cid] = {
            "journal": name,
            "sha256": fingerprint(value),
        }
        self.adapter._save()
        return self.poll_conditions(cid, values)

    def poll_conditions(self, cid, values):
        """Poll hook during call: bind only new owned request and original offer."""
        self.adapter._guard()
        if cid not in CASES:
            raise SimulationError("Unsupported operational condition case")
        binding = self._condition_identity(cid, values)
        if binding is None:
            return {
                "source_supported": True,
                "native_ready": False,
                "status": "awaiting_owned_request_and_offer",
            }
        folder = Path(self.adapter.campaign.folder)
        baseline = folder / f"{cid}-{binding.attempt}-conditions-baseline.json"
        if not baseline.exists():
            if cid in ("C37", "C38", "C39", "C40"):
                pre = self._condition_pre(cid)
                _intent(
                    baseline,
                    {
                        "binding": asdict(binding),
                        "snapshot": pre["snapshot"],
                        "pre_request_sha256": fingerprint(pre),
                    },
                )
            else:
                self.conditions.arrange(binding)
                return {
                    "source_supported": True,
                    "native_ready": False,
                    "status": "awaiting_operator_reply"
                    if cid in ("C42", "C43", "C45")
                    else "awaiting_native_deadline",
                    "binding": asdict(binding),
                }
        return self.conditions.observe(binding)

    def observe_conditions(self, cid, values):
        return self.poll_conditions(cid, values)

    def _capability(self, path, name):
        if (
            not isinstance(self.capability_headers, dict)
            or set(self.capability_headers) != {"Authorization"}
            or not isinstance(self.capability_headers["Authorization"], str)
            or not self.capability_headers["Authorization"].startswith("Bearer ")
        ):
            raise SimulationError(
                "Authenticated native mechanism capability GET unavailable"
            )

        def get():
            response = self.adapter.client.get(
                self.adapter.config["deployed_url"].rstrip("/") + path,
                headers=self.capability_headers,
                follow_redirects=False,
                timeout=10,
            )
            response.raise_for_status()
            value = response.json()
            if (
                not isinstance(value, dict)
                or value.get("success") is not True
                or value.get("enabled") is not True
                or value.get("capability") != name
            ):
                raise SimulationError(
                    "Native mechanism capability is disabled or unavailable"
                )
            return value

        return _external(get)

    def fault_capabilities(self):
        value = self._capability(
            "/api/v1/portal/internal/simulation-faults", "owned-faults-v1"
        )
        if (
            value.get("schema_ready") is not True
            or not isinstance(value.get("modes"), list)
            or not value["modes"]
            or any(not isinstance(mode, str) or not mode for mode in value["modes"])
            or not isinstance(value.get("allowlisted_technician_ids"), list)
            or any(not _positive_id(i) for i in value["allowlisted_technician_ids"])
            or not isinstance(value.get("allowlisted_phone_fingerprints"), list)
            or any(
                not isinstance(v, str) or not re.fullmatch("[0-9a-f]{64}", v)
                for v in value["allowlisted_phone_fingerprints"]
            )
        ):
            raise SimulationError(
                "Native fault mechanism schema or recipient scope unavailable"
            )
        return value

    def staff_capabilities(self):
        return self._capability(
            "/api/v1/portal/internal/simulation-staff", "owned-staff-v1"
        )

    def session_capabilities(self):
        value = self._capability(
            "/api/v1/portal/internal/simulation-session-capabilities",
            "owned-session-v1",
        )
        if (
            value.get("audit_schema_ready") is not True
            or value.get("hmac_configured") is not True
            or value.get("verification_bypass_active") is not False
        ):
            raise SimulationError(
                "Native authenticated callback audit or HMAC mechanism unavailable"
            )
        return value

    def c50_delivery(self, *, expected_booking, request_id, conversation_id):
        """Fresh native session, booking, Google and WhatsApp proof; no C48 IDs.

        Receiving email remains explicitly unverified and is owned by the generic
        required-evidence gate. No native/provider writes or credit conversions.
        """
        from .deployed_full_causal import verify_native_history
        from .deployed_full_session import _known_context
        from .evidence import check

        checks = []

        def passed(name):
            checks.append(check(name, True))

        def report():
            return {
                "source_supported": True,
                "evidence_complete": bool(checks)
                and all(c.get("passed") is True for c in checks),
                "checks": checks,
                "blockers": [c["name"] for c in checks if c.get("passed") is not True],
                "native_inbox_receiving": "unverified",
                "native_acceptance": "unverified",
            }

        step = "exact C50 owned native session identity"
        try:
            self.adapter._guard()
            baseline, _root, _folder, intent, _ledger, entry, cid = _known_context(
                self.adapter
            )
            if (
                cid != conversation_id
                or not isinstance(conversation_id, str)
                or not conversation_id
                or entry.get("unsettled") is not False
                or entry.get("credits") is None
                or not _positive_id(request_id)
                or request_id not in self.adapter.owned_ids
                or request_id not in self.adapter.current_ids
                or request_id in self.adapter.original_ids
                or expected_booking.get("customer_id") != baseline["customer_id"]
            ):
                raise SimulationError("Owned C50 session/booking identity differs")
            passed(step)
            step = "fresh authenticated C50 conversation and native CRM callback proof"
            detail = _external(
                self.elevenlabs.request,
                "GET",
                "/v1/convai/conversations/" + quote(cid, safe=""),
            )
            notes = _rows(
                self.reader,
                "c50_notes",
                "id,call_id,customer_id,summary,transcript,created_at FROM crm_notes WHERE customer_id=%s AND call_id=%s ORDER BY id",
                (baseline["customer_id"], cid),
            )
            events = _rows(
                self.reader,
                "c50_events",
                "id,provider,event_id,payload_hash,status,completed_at AT TIME ZONE current_setting('TimeZone') AS completed_at FROM webhook_events WHERE provider='elevenlabs' AND event_id=%s ORDER BY id",
                (cid,),
            )
            audit = _rows(
                self.reader,
                "c50_audit",
                "provider,event_id,conversation_id,payload_hash,verified_at FROM authenticated_webhook_ingress WHERE provider='elevenlabs' AND event_id=%s ORDER BY verified_at",
                (cid,),
            )
            history = medium._serial({"notes": notes, "events": events, "audit": audit})
            if not verify_native_history(
                history,
                detail,
                customer_id=baseline["customer_id"],
                conversation_id=cid,
                agent_id=intent["agent_id"],
                baseline_note_ids=baseline["baseline_note_ids"],
                baseline_event_ids=baseline["baseline_event_ids"],
                dynamic_variables=intent["dynamic_variables"],
                expected_user_id=baseline["customer_phone"],
            ):
                raise SimulationError(
                    "C50 provider/native authenticated history join differs"
                )
            passed(step)
            step = "exact C50 native booking reservation and capacity"
            raw = _external(self.reader.request_rows, [request_id])
            if len(raw) != 1 or raw[0].get("id") != request_id:
                raise SimulationError("C50 booking join unavailable")
            row = raw[0]
            reservations = _rows(
                self.reader,
                "reservations",
                "id,service_request_id,staff_agent_id,status,starts_at,ends_at,calendar_event_id,calendar_integration_status FROM appointment_reservations WHERE service_request_id=%s ORDER BY id",
                (request_id,),
            )
            active = [r for r in reservations if r.get("status") == "ACTIVE"]
            segments = _rows(
                self.reader,
                "segments",
                "p.reservation_id,p.staff_agent_id,p.segment_start FROM appointment_reservation_segments p JOIN appointment_reservations r ON r.id=p.reservation_id WHERE r.service_request_id=%s AND r.status='ACTIVE' ORDER BY p.segment_start",
                (request_id,),
            )
            zone = ZoneInfo(self.adapter.config["app_config"]["business_timezone"])

            def iso(value):
                dt = (
                    value
                    if isinstance(value, datetime)
                    else datetime.fromisoformat(value)
                )
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=zone)
                return dt.astimezone(zone).isoformat()

            booking = {
                "source": "native_postgresql",
                "customer_id": baseline["customer_id"],
                "requests": [
                    {
                        k: row[k]
                        for k in (
                            "id",
                            "customer_id",
                            "service_type",
                            "status",
                            "booking_type",
                            "duration_minutes",
                            "staff_agent_id",
                        )
                    }
                    | {
                        "booking_start_at": iso(row["starts_at"]),
                        "booking_end_at": iso(row["ends_at"]),
                    }
                ],
                "reservations": [
                    {
                        k: r[k]
                        for k in (
                            "id",
                            "service_request_id",
                            "staff_agent_id",
                            "status",
                        )
                    }
                    | {"starts_at": iso(r["starts_at"]), "ends_at": iso(r["ends_at"])}
                    for r in active
                ],
                "segments": [
                    {k: r[k] for k in ("reservation_id", "staff_agent_id")}
                    | {"segment_start": iso(r["segment_start"])}
                    for r in segments
                ],
            }
            original_reservations = [
                r["reservation_id"]
                for r in self.adapter.campaign.manifest.get("baseline", [])
                if _positive_id(r.get("reservation_id"))
            ]
            _booking(
                booking,
                {
                    "expected_booking": expected_booking,
                    "baseline": {
                        "request_ids": sorted(self.adapter.original_ids),
                        "reservation_ids": original_reservations,
                    },
                },
            )
            passed(step)
            step = "actual C50 conversation executed booking bound to native request"
            _c50_executed_booking(
                detail,
                booking,
                expected_booking,
                self.adapter.config["deployed_url"],
                baseline["customer_phone"],
            )
            passed(step)
            step = "exact C50 delivered native calendar projection attempt"
            reservation = active[0]
            event_id = reservation.get("calendar_event_id")
            if (
                reservation.get("calendar_integration_status") != "CREATED"
                or not isinstance(event_id, str)
                or not event_id
            ):
                raise SimulationError("Native C50 calendar projection incomplete")
            projection = _rows(
                self.reader,
                "projection",
                "id,request_id,event_type,status,payload FROM outbox_notifications WHERE request_id=%s AND event_type=%s ORDER BY id",
                (request_id, "calendar_projection"),
            )
            joined = [
                r
                for r in projection
                if r.get("request_id") == request_id
                and r.get("status") == "DELIVERED"
                and isinstance(r.get("payload"), dict)
                and r["payload"].get("reservation_id") == reservation["id"]
                and r["payload"].get("agent_id") == expected_booking["staff_agent_id"]
                and r["payload"].get("calendar_event_id") == event_id
            ]
            if len(joined) != 1:
                raise SimulationError("Native C50 projection attempt identity differs")
            passed(step)
            step = "actual C50 Google event on connected staff calendar"
            if self.google_client is None:
                raise SimulationError("Authenticated Google observer unavailable")
            google = GoogleEvents(
                self.reader,
                client=self.google_client,
                staff_agent_id=expected_booking["staff_agent_id"],
                decrypt=self.decrypt,
            )
            actual = google.get_calendar_event("primary", event_id)
            if (
                actual.get("status") != "confirmed"
                or datetime.fromisoformat(actual["start"]["dateTime"])
                != datetime.fromisoformat(expected_booking["starts_at"])
                or datetime.fromisoformat(actual["end"]["dateTime"])
                != datetime.fromisoformat(expected_booking["ends_at"])
            ):
                raise SimulationError("Actual C50 calendar interval differs")
            passed(step)
            step = "exact C50 owned customer WhatsApp attempt"
            messages = _rows(
                self.reader,
                "c50_notifications",
                "id,appointment_id,recipient_type,recipient_phone,channel,status,retry_count,twilio_message_sid,created_at AT TIME ZONE current_setting('TimeZone') AS created_at FROM sms_log WHERE appointment_id=%s AND recipient_type='customer' AND channel='WHATSAPP' ORDER BY id",
                (request_id,),
            )
            if len(messages) != 1:
                raise SimulationError("One actual owned WhatsApp attempt required")
            message = messages[0]
            if (
                not _positive_id(message.get("id"))
                or message.get("appointment_id") != request_id
                or message.get("recipient_type") != "customer"
                or message.get("channel") != "WHATSAPP"
                or message.get("status") != "DELIVERED"
                or type(message.get("retry_count")) is not int
                or message["retry_count"] != 0
                or _phone(message.get("recipient_phone"))
                != _phone(baseline["customer_phone"])
                or not isinstance(message.get("twilio_message_sid"), str)
                or not re.fullmatch("SM[0-9a-fA-F]{32}", message["twilio_message_sid"])
            ):
                raise SimulationError(
                    "Exact native C50 WhatsApp recipient/attempt differs"
                )
            passed(step)
            step = "actual C50 delivered WhatsApp from authenticated Twilio account"
            if self.twilio is None:
                raise SimulationError("Authenticated Twilio observer unavailable")
            self.twilio.permissions()
            actual_message = self.twilio.get_message(message["twilio_message_sid"])
            if (
                actual_message.get("status") != "delivered"
                or actual_message.get("direction")
                not in ("outbound-api", "outbound-reply")
                or actual_message.get("to")
                != "whatsapp:" + _canonical_phone(baseline["customer_phone"])
                or _timestamp(actual_message.get("date_created"))
                < _timestamp(message["created_at"]) - 5
            ):
                raise SimulationError("Actual C50 WhatsApp delivery/recipient differs")
            passed(step)
            result = report()
            result["provider_conversation_id"] = cid
            return result
        except Exception:  # noqa: BLE001 - retain no external/private diagnostic text or types
            checks.append(
                check(
                    step,
                    False,
                    "Independent native/provider evidence unavailable or inconsistent",
                )
            )
            return report()

    def preflight(self, case_ids):
        customer_id = medium._identity_id(self.adapter.config)
        customers = _rows(
            self.reader,
            "preflight_customer",
            "id,phone,sms_opt_in FROM customers WHERE id=%s",
            (customer_id,),
        )
        staff_ids = self.adapter.config.get("deployed_medium", {}).get(
            "technician_ids", []
        )
        staff = _rows(
            self.reader,
            "preflight_staff",
            "id,phone_number,is_active FROM staff_agents WHERE id=ANY(%s) ORDER BY id",
            (staff_ids,),
        )
        policy = _rows(
            self.reader,
            "preflight_policy",
            "quiet_hours_enabled,quiet_start_time::text,quiet_end_time::text FROM sms_config ORDER BY id",
        )
        enrollment = _rows(
            self.reader,
            "preflight_enrollment",
            "w.phone_number,w.whatsapp_onboarded FROM sms_whitelist w JOIN customers c ON c.phone=w.phone_number WHERE c.id=%s",
            (customer_id,),
        )
        google_permissions = {}
        twilio_observed = False
        if self.google_client is not None:
            for staff_id in staff_ids:
                try:
                    google_permissions[staff_id] = GoogleEvents(
                        self.reader,
                        client=self.google_client,
                        staff_agent_id=staff_id,
                        decrypt=self.decrypt,
                    ).permissions()
                except Exception:  # noqa: BLE001 - fixed preflight blocker, never credential diagnostics
                    google_permissions[staff_id] = None
        if self.twilio is not None:
            try:
                twilio_observed = self.twilio.permissions().get("active") is True
            except Exception:  # noqa: BLE001 - actual GET permission remains unverified
                twilio_observed = False
        reports = {}
        for cid in case_ids:
            blockers = []
            if (
                len(customers) != 1
                or len(staff) != len(staff_ids)
                or any(r.get("is_active") is not True for r in staff)
            ):
                blockers.append(
                    "Native customer and designated active staff identities unavailable"
                )
            phones = {_phone(r["phone_number"]) for r in staff if r.get("phone_number")}
            if cid == "C33":
                blockers.append(
                    "Distinct customer phone ownership and recipient permission require independent native binding"
                )
            if cid == "C37" and (
                not enrollment
                or any(r.get("whatsapp_onboarded") is not False for r in enrollment)
            ):
                blockers.append(
                    "Distinct permitted unenrolled provider-rejection recipient unavailable; enrolled handset cannot establish failure"
                )
            if cid == "C38" and (
                not enrollment
                or any(r.get("whatsapp_onboarded") is not False for r in enrollment)
            ):
                blockers.append(
                    "Actual unenrolled recipient unavailable; enrolled handset cannot substitute"
                )
            if cid == "C39":
                try:
                    latest = self.twilio.latest_inbound(customers[0]["phone"])
                    closed = latest["received_at_unix"] + 86400 < _now(self.reader)
                except Exception:  # noqa: BLE001 - scoped provider read remains unknown
                    closed = False
                if not closed:
                    blockers.append(
                        "Actual provider-bound last inbound timestamp must establish closed messaging window"
                    )
            if (
                cid == "C40"
                and customers
                and (
                    _phone(customers[0]["phone"]) in phones
                    or customers[0].get("sms_opt_in") is not False
                )
            ):
                blockers.append(
                    "Isolated opted-out customer phone unavailable; shared staff handset cannot substitute"
                )
            if cid == "C41":
                blockers.append(
                    "Voice/customer quiet-hours bypass policy requires owner decision"
                )
            if cid in ("C43", "C45") and len(phones) < 2:
                blockers.append(
                    "Distinct original and replacement staff phone ownership unavailable"
                )
            if (
                cid in ("C37", "C38", "C39", "C42", "C43", "C45")
                and not twilio_observed
            ):
                blockers.append(
                    "Authenticated Twilio read-only account mechanism unavailable"
                )
            if cid in ("C44", "C41") and not policy:
                blockers.append(
                    "Native messaging deadline/policy mechanism unavailable"
                )
            if cid == "C50":
                try:
                    self.session_capabilities()
                except Exception:  # noqa: BLE001 - fixed native capability diagnostic
                    blockers.append(
                        "Native authenticated callback audit/HMAC mechanism unavailable"
                    )
                try:
                    from . import deployed_full_session as session
                    remaining=session.native_credit_remaining(self.adapter.config,self.elevenlabs)
                    budget=self.adapter.config['budget']
                    estimate=number(budget.get('case_estimates',{}).get('C50',budget.get('case_upper_estimate')),positive=True)
                    if remaining<estimate:
                        raise SimulationError('Insufficient native quota')
                except Exception:  # noqa: BLE001 - no account/credential detail crosses readiness
                    blockers.append(
                        "Native session provider credit units, pinned account tier and refreshed quota require independent verification"
                    )
            if cid == "C48":
                if not google_permissions or any(
                    not p or p.get("write") is not True
                    for p in google_permissions.values()
                ):
                    blockers.append(
                        "Authenticated Google event GET mechanism unavailable"
                    )
                if not twilio_observed:
                    blockers.append(
                        "Authenticated Twilio delivery GET mechanism unavailable"
                    )
                blockers.append(
                    "Native provider credit units and refreshed two-phase quota require independent verification"
                )
            reports[cid] = {
                "source_supported": cid in CASES or cid in ("C48", "C50"),
                "native_ready": False,
                "native_acceptance": "unverified",
                "blockers": blockers,
                "mechanism_observed": not any(
                    "mechanism unavailable" in b for b in blockers
                ),
            }
        return reports


def _c50_executed_booking(detail, booking, expected, base_url, phone):
    calls = []
    results = []
    for turn in detail["transcript"]:
        for call in turn.get("tool_calls", []):
            if call.get("tool_name") in ("book_appointment", "create_service_request"):
                calls.append(call)
            elif call.get("tool_name") in (
                "cancel_appointment",
                "reschedule_appointment",
                "consolidate_appointment_service",
                "request_callback",
            ):
                raise SimulationError("Unexpected C50 booking mutation")
        results.extend(
            r
            for r in turn.get("tool_results", [])
            if r.get("tool_name") in ("book_appointment", "create_service_request")
        )
    if len(calls) != 1 or len(results) != 1:
        raise SimulationError("One actual executed C50 booking result required")
    call, result = calls[0], results[0]
    target = urlsplit(call["tool_details"]["url"])
    origin = urlsplit(base_url)
    query = parse_qs(target.query, strict_parsing=True)
    params = call["params_as_json"]
    params = json.loads(params) if isinstance(params, str) else params
    value = result["result_value"]
    value = json.loads(value) if isinstance(value, str) else value
    value = value.get("result", value)
    if (
        call.get("type") != "webhook"
        or call.get("tool_has_been_called") is not True
        or call["tool_details"].get("method") != "POST"
        or call["tool_details"].get("type") != "webhook"
        or not isinstance(call.get("request_id"), str)
        or not call["request_id"]
        or result.get("request_id") != call["request_id"]
        or result.get("tool_name") != call["tool_name"]
        or result.get("is_error") is not False
        or target.scheme != origin.scheme
        or target.netloc != origin.netloc
        or target.path != "/api/v1/voice/tools"
        or query not in ({}, {"name": [call["tool_name"]]})
        or target.fragment
        or params.get("service_type") != expected["service_type"]
        or _phone(params.get("phone")) != _phone(phone)
        or value.get("success") is not True
    ):
        raise SimulationError("Exact executed C50 native HTTP booking effect required")
    ids = [
        value[k]
        for k in ("service_request_id", "appointment_id", "request_id")
        if value.get(k) is not None
    ]
    appointments = value.get("appointments", [])
    if not isinstance(appointments, list) or len(appointments) > 1:
        raise SimulationError("C50 native booking result scope differs")
    ids.extend(
        r["service_request_id"] for r in appointments if "service_request_id" in r
    )
    if not ids or any(
        not _positive_id(v) or v != booking["requests"][0]["id"] for v in ids
    ):
        raise SimulationError(
            "Actual C50 booking result identifies another native request"
        )
    if any(
        r.get("reservation_id") is not None
        and (
            not _positive_id(r["reservation_id"])
            or r["reservation_id"] != booking["reservations"][0]["id"]
        )
        for r in appointments
    ):
        raise SimulationError(
            "Actual C50 booking result identifies another native reservation"
        )
