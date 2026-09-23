"""Unit tests for local calendar authority helpers."""

import datetime as dt_mod

import pytest

from serviceBot.services.calendar_availability import (
    CalendarError,
    parse_slot_datetime,
    provider_event_overlaps_slot,
    serialize_slot_datetime,
)


def test_slot_parser_requires_quarter_hour_and_normalizes_format():
    assert serialize_slot_datetime("2026-10-15T09:30:00") == "2026-10-15 09:30:00"
    assert parse_slot_datetime("2026-10-15 09:30:00") == dt_mod.datetime(2026, 10, 15, 9, 30)

    with pytest.raises(CalendarError, match="15-minute boundary"):
        parse_slot_datetime("2026-10-15 09:31:00")


def test_provider_busy_event_is_detected_without_fail_open():
    slot = dt_mod.datetime(2026, 10, 15, 9, 30)
    busy_event = {
        "status": "confirmed",
        "start": {"dateTime": "2026-10-15T09:15:00-04:00"},
        "end": {"dateTime": "2026-10-15T10:15:00-04:00"},
    }
    assert provider_event_overlaps_slot(busy_event, slot) is True
    assert provider_event_overlaps_slot({**busy_event, "status": "cancelled"}, slot) is False
