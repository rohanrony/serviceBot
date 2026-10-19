"""Ordered component contracts for grouped appointment mutations."""
import pytest

from serviceBot.services.booking import (
    BookingValidationError,
    _appointment_blocks,
    _validated_components,
)


def test_groups_by_first_technician_appearance_preserving_component_order():
    items = [{'name': name, 'duration': duration, 'booking_type': 'appointment', 'issue': name}
             for name, duration in [('Oil', 60), ('Brake', 30), ('Tire', 15)]]
    blocks = _appointment_blocks(items, [2, 1, 2])
    assert [(block['agent_id'], block['duration'], block['name']) for block in blocks] == [(2, 75, 'Oil, Tire'), (1, 30, 'Brake')]
    assert blocks[0]['service_components'] == [{'name': 'Oil', 'duration_minutes': 60}, {'name': 'Tire', 'duration_minutes': 15}]


def test_callbacks_remain_separate():
    items = [{'name': name, 'duration': 15, 'booking_type': 'callback', 'issue': name} for name in ['A', 'B']]
    assert len(_appointment_blocks(items, [1, 1])) == 2


@pytest.mark.parametrize('snapshot', [[], {}, [{'name': 'Oil', 'duration_minutes': True}],
    [{'name': 'Oil', 'duration_minutes': 16}], [{'name': '', 'duration_minutes': 15}],
    [{'name': 'Oil', 'duration_minutes': 60}, {'name': 'Oil', 'duration_minutes': 15}]])
def test_invalid_snapshot_fails_closed(snapshot):
    with pytest.raises(BookingValidationError):
        _validated_components({'service_components': snapshot, 'service_type': 'Oil', 'duration_minutes': 60})


def test_snapshot_duration_and_exact_label_must_match():
    row = {'service_components': [{'name': 'Oil', 'duration_minutes': 60}], 'service_type': 'Oil', 'duration_minutes': 60}
    assert _validated_components(row) == row['service_components']
    for change in [{'duration_minutes': 75}, {'service_type': 'oil'}]:
        with pytest.raises(BookingValidationError): _validated_components(dict(row, **change))


def test_database_datetime_remains_recognizable_when_business_clock_is_frozen(monkeypatch):
    from datetime import datetime

    from serviceBot.services import booking

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 19, 10, tzinfo=tz)

    database_timestamp = datetime(2026, 10, 28, 10, 15)
    monkeypatch.setattr(booking.dt_mod, 'datetime', FrozenDateTime)
    assert booking._as_datetime(database_timestamp) == database_timestamp
    assert booking._as_datetime('2026-10-28 10:15:00') == database_timestamp
    assert booking.dt_mod.datetime.now() == FrozenDateTime(2026, 10, 19, 10)
    assert booking._as_datetime(object()) is None
