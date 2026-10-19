"""Read-only component/grid evidence for grouped full-native appointment cases."""
from __future__ import annotations

from datetime import timedelta

from . import deployed_medium as medium
from .core import SimulationError


def components(adapter, ids):
    ids = set(ids)
    if not ids <= adapter.owned_ids or ids & adapter.original_ids:
        raise SimulationError('Component observation requires exact owned request IDs')
    rows = medium._read(adapter.config, 'SELECT id,service_components FROM service_requests WHERE id=ANY(%s) ORDER BY id', (sorted(ids),)) if ids else []
    if {r['id'] for r in rows} != ids:
        raise SimulationError('Owned component snapshots are unavailable')
    return {r['id']: r['service_components'] for r in rows}


def exact_reservation(row, snapshot, expected, staff, config):
    try:
        start, end = medium._dt(row['starts_at'], config), medium._dt(row['ends_at'], config)
        duration = sum(item['duration_minutes'] for item in expected)
        return (start.minute % 15 == 0 and start.second == 0 and start.microsecond == 0
                and snapshot == expected and bool(expected)
                and all(set(item) == {'name', 'duration_minutes'} and type(item['duration_minutes']) is int
                        and item['duration_minutes'] > 0 and item['duration_minutes'] % 15 == 0 for item in snapshot)
                and row['service_type'] == ', '.join(item['name'] for item in expected)
                and row['staff_agent_id'] == staff and row['booking_type'] == 'appointment'
                and row['status'] != 'cancelled' and bool(row['reservation_id']) and row['reservation_status'] == 'ACTIVE'
                and {item['name'] for item in expected} <= set(row['qualified_service_names'])
                and row['duration_minutes'] == duration and end-start == timedelta(minutes=duration)
                and start == medium._dt(row['booking_time'], config) and row['segment_count'] == duration // 15
                and [medium._dt(value, config) for value in row['reservation_segments']] ==
                    [start+timedelta(minutes=i) for i in range(0, duration, 15)])
    except (KeyError, TypeError, ValueError):
        return False


def grouped_three_service_visit(rows, snapshots, config, services, when):
    try:
        if len(rows) != 2 or len({r['id'] for r in rows}) != 2:
            return False
        ordered = sorted(rows, key=lambda r: medium._dt(r['starts_at'], config))
        first, second = ordered
        expected_first = [{'name': services[k]['name'], 'duration_minutes': services[k]['duration_minutes']} for k in ('oil', 'second')]
        expected_second = [{'name': services['split']['name'], 'duration_minutes': services['split']['duration_minutes']}]
        staff = config['deployed_medium']['technician_ids']
        return (exact_reservation(first, snapshots[first['id']], expected_first, staff[0], config)
                and exact_reservation(second, snapshots[second['id']], expected_second, staff[1], config)
                and bool(first['visit_group_id']) and first['visit_group_id'] == second['visit_group_id']
                and medium._dt(first['starts_at'], config) == medium._dt(when, config)
                and medium._dt(first['ends_at'], config) == medium._dt(second['starts_at'], config)
                and medium._dt(second['ends_at'], config) - medium._dt(when, config) == timedelta(minutes=150)
                and len({r['calendar_event_id'] for r in rows}) == 2)
    except (KeyError, TypeError, ValueError):
        return False


def preserved_component_appointment(current, original, snapshot, original_snapshot, config, services):
    fields = ('id', 'customer_id', 'customer_phone', 'customer_name', 'make', 'model', 'year',
              'status', 'service_type', 'booking_type', 'booking_time', 'duration_minutes',
              'staff_agent_id', 'reservation_id', 'reservation_status', 'starts_at', 'ends_at',
              'segment_count', 'reservation_segments', 'visit_group_id')
    expected = [{'name': services['split']['name'], 'duration_minutes': services['split']['duration_minutes']}]
    return (snapshot == original_snapshot == expected
            and all(medium._serial(current.get(k)) == medium._serial(original.get(k)) for k in fields)
            and exact_reservation(current, snapshot, expected, config['deployed_medium']['technician_ids'][1], config))


def retired_selected_projection(row):
    return (row.get('request_calendar_status') == 'DELETED' and row.get('has_event') is True and row.get('active_count') == 0
            and row.get('segment_count') == 0 and bool(row.get('reservation_calendar_statuses'))
            and all(status == 'DELETED' for status in row['reservation_calendar_statuses'])
            and bool(row.get('projection_statuses'))
            and all(status == 'DELIVERED' for status in row['projection_statuses']))


def separated_specialist_callbacks(rows, snapshots, config, services, when):
    """Callbacks keep 15-minute reservations and the explicit 15-minute gap."""
    try:
        if len(rows) != 2 or len({r['id'] for r in rows}) != 2:
            return False
        start = medium._dt(when, config)
        if start.minute % 15 or start.second or start.microsecond:
            return False
        indexed = {r['service_type']: r for r in rows}
        names = [services[key]['name'] for key in ('oil', 'split')]
        if set(indexed) != set(names):
            return False
        for offset, name, staff in zip((0, 30), names, config['deployed_medium']['technician_ids'], strict=True):
            row = indexed[name]
            expected_start = start + timedelta(minutes=offset)
            if (snapshots[row['id']] is not None or row['booking_type'] != 'callback'
                    or row['status'] == 'cancelled' or row['staff_agent_id'] != staff
                    or not row['qualified'] or name not in row['qualified_service_names']
                    or row['duration_minutes'] != 15 or not row['reservation_id'] or row['reservation_status'] != 'ACTIVE'
                    or medium._dt(row['booking_time'], config) != expected_start
                    or medium._dt(row['starts_at'], config) != expected_start
                    or medium._dt(row['ends_at'], config) != expected_start + timedelta(minutes=15)
                    or row['segment_count'] != 1
                    or [medium._dt(value, config) for value in row['reservation_segments']] != [expected_start]
                    or row.get('calendar_integration_status') != 'CREATED'
                    or row.get('request_calendar_status') != 'CREATED' or not row.get('calendar_event_id')):
                return False
        return len({r['calendar_event_id'] for r in rows}) == 2
    except (KeyError, TypeError, ValueError):
        return False
