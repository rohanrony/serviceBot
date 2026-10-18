"""Owned PostgreSQL + native tool contracts for authoritative visit lookup identity."""
from datetime import datetime
from uuid import uuid4

import pytest

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.db.queries import get_customer_appointments

START = datetime.fromisoformat('2035-01-08 09:00:00')
PHONE = '2125550198'


@pytest.fixture
def appointments():
    customers = []
    def customer(phone=PHONE):
        with get_db_connection() as conn, dict_cursor(conn) as cursor:
            cursor.execute('INSERT INTO customers(name,phone,email) VALUES (%s,%s,%s) RETURNING id',
                           ('Lookup Test', phone, 'lookup@example.test'))
            identity = cursor.fetchone()['id']
            customers.append(identity)
            return identity
    def add(owner, *, group=None, when=START, kind='appointment', status='pending', service='Owned Oil', duration=45):
        with get_db_connection() as conn, dict_cursor(conn) as cursor:
            cursor.execute('''INSERT INTO service_requests(customer_id,service_type,issue_description,status,
                booking_type,booking_time,duration_minutes,visit_group_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (owner, service, service + ' issue', status, kind, when, duration, group))
            return cursor.fetchone()['id']
    yield customer, add
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute('DELETE FROM service_requests WHERE customer_id=ANY(%s)', (customers,))
        cursor.execute('DELETE FROM customers WHERE id=ANY(%s)', (customers,))


def metadata(row):
    return {name: row[name] for name in ('visit_group_id', 'visit_start', 'visit_anchor_id', 'visit_member_ids')}


def test_group_uses_earliest_component_not_smallest_id_and_keeps_existing_fields(appointments):
    customer, add = appointments
    owner, group = customer(), str(uuid4())
    later = add(owner, group=group, when=START.replace(hour=10), service='Owned Brake', duration=60)
    first = add(owner, group=group)
    rows = get_customer_appointments(PHONE)
    assert [row['id'] for row in rows] == [first, later]
    for row in rows:
        assert metadata(row) == {'visit_group_id': group, 'visit_start': str(START),
                                 'visit_anchor_id': first, 'visit_member_ids': [first, later]}
    original = next(row for row in rows if row['id'] == later)
    assert original['appointment_datetime'] == str(START.replace(hour=10))
    assert original['service_type'] == 'Owned Brake' and original['issue_description'] == 'Owned Brake issue'
    assert original['duration_minutes'] == 60 and original['status'] == 'pending'


def test_equal_starts_have_stable_id_anchor_and_members(appointments):
    customer, add = appointments
    owner, group = customer(), str(uuid4())
    first, second = add(owner, group=group), add(owner, group=group)
    rows = get_customer_appointments(PHONE)
    assert [row['id'] for row in rows] == [first, second]
    assert all(row['visit_anchor_id'] == first and row['visit_member_ids'] == [first, second] for row in rows)


def test_separate_same_phone_and_time_appointments_do_not_acquire_group_identity(appointments):
    customer, add = appointments
    owner = customer()
    ids = [add(owner), add(owner)]
    rows = get_customer_appointments(PHONE)
    assert {row['id'] for row in rows} == set(ids)
    assert all(metadata(row) == {'visit_group_id': None, 'visit_start': None,
        'visit_anchor_id': None, 'visit_member_ids': []} for row in rows)


def test_callback_never_joins_even_a_stored_appointment_group(appointments):
    customer, add = appointments
    owner, group = customer(), str(uuid4())
    appointment = add(owner, group=group)
    callback = add(owner, group=group, kind='callback', when=START.replace(hour=8))
    rows = {row['id']: row for row in get_customer_appointments(PHONE)}
    assert rows[appointment]['visit_member_ids'] == [appointment]
    assert metadata(rows[callback]) == {'visit_group_id': None, 'visit_start': None,
        'visit_anchor_id': None, 'visit_member_ids': []}


@pytest.mark.parametrize('other_phone', ['+12125550198', '6465550197'])
def test_matching_group_uuid_cannot_join_a_different_customer(appointments, other_phone):
    customer, add = appointments
    owner, other, group = customer(), customer(other_phone), str(uuid4())
    own = add(owner, group=group)
    foreign = add(other, group=group, when=START.replace(hour=8))
    rows = {row['id']: row for row in get_customer_appointments(PHONE)}
    assert rows[own]['visit_member_ids'] == [own]
    assert rows[own]['visit_anchor_id'] == own and rows[own]['visit_start'] == str(START)
    if other_phone == '+12125550198':
        assert rows[foreign]['visit_member_ids'] == [foreign]
    else:
        assert foreign not in rows


def test_cancelled_and_completed_companions_are_excluded(appointments):
    customer, add = appointments
    owner, group = customer(), str(uuid4())
    add(owner, group=group, when=START.replace(hour=7), status='cancelled')
    add(owner, group=group, when=START.replace(hour=8), status='completed')
    remaining = add(owner, group=group, status='confirmed')
    rows = get_customer_appointments(PHONE)
    assert len(rows) == 1
    assert rows[0]['visit_member_ids'] == [remaining] and rows[0]['visit_anchor_id'] == remaining
    assert rows[0]['visit_start'] == str(START)


def test_missing_active_component_start_exposes_uncertain_anchor(appointments):
    customer, add = appointments
    owner, group = customer(), str(uuid4())
    known = add(owner, group=group)
    unknown = add(owner, group=group, when=None)
    rows = get_customer_appointments(PHONE)
    assert all(row['visit_start'] is None and row['visit_anchor_id'] is None for row in rows)
    assert all(row['visit_member_ids'] == [known, unknown] for row in rows)


@pytest.mark.parametrize('branch', ['phone', 'caller_phone', 'subscriber_suffix'])
def test_native_api_serializes_metadata_across_every_lookup_branch(appointments, branch):
    from fastapi.testclient import TestClient

    from serviceBot.main import app
    customer, add = appointments
    owner, group = customer(), str(uuid4())
    first = add(owner, group=group)
    second = add(owner, group=group, when=START.replace(hour=10))
    args = {'phone': PHONE}
    if branch == 'caller_phone': args = {'phone': '6465550197', 'caller_phone': PHONE}
    if branch == 'subscriber_suffix': args = {'phone': '9995550198'}
    with TestClient(app) as client:
        response = client.post('/api/v1/voice/tools', json={'tool_call_id': 'visit-' + uuid4().hex,
            'name': 'get_customer_appointments', 'arguments': args})
    assert response.status_code == 200
    result = response.json()['result']
    assert result['success'] is True
    for key in ('appointments', 'upcoming_appointments'):
        rows = result[key]
        assert [row['id'] for row in rows] == [first, second]
        for row in rows:
            assert row['visit_group_id'] == group
            assert row['visit_start'] == '2035-01-08 09:00:00'
            assert row['visit_anchor_id'] == first and row['visit_member_ids'] == [first, second]
