"""Truthful voice outcomes on native HTTP and disposable PostgreSQL owners."""
from datetime import timedelta

import pytest

from e2e.scenarios import capacity_snapshot, service
from e2e.test_voice_and_reporting import voice
from serviceBot.services.google_calendar import (
    fetch_agent_events as native_fetch_agent_events,
)


def test_unconnected_owned_calendar_is_unknown_not_no_open_slots(api, db, scenario, monkeypatch, freeze_business_clock):
    freeze_business_clock(scenario['start'] - timedelta(days=2))
    # Real missing native Google binding; no revoked credentials or HTTP fault mock.
    staff = db("INSERT INTO staff_agents(name,email,phone_number) VALUES ('Owned unknown calendar','unknown@example.test','+15550100009') RETURNING id")[0]['id']
    service(api, 'Owned unknown availability', [staff], 30)
    assert db('SELECT agent_id FROM user_google_accounts WHERE agent_id=%s', (staff,)) == []
    monkeypatch.setattr('serviceBot.services.google_calendar.fetch_agent_events', native_fetch_agent_events)
    before = capacity_snapshot(db)
    result = voice(api, 'check_availability', {'service_type': 'Owned unknown availability',
        'preferred_date': scenario['date'], 'preferred_time': '10:00 AM'})
    assert result['success'] is False
    assert result['availability_status'] == 'unknown'
    assert result['error_code'] == 'AVAILABILITY_UNKNOWN' and result['retryable'] is True
    assert result['available_slots'] == []
    assert 'no open' not in result['message'].lower()
    assert capacity_snapshot(db) == before


@pytest.mark.parametrize('name', ['cba_webbook', 'cba_webhook', 'handoff', 'transfer_call'])
def test_open_shop_summary_is_not_completed_handoff_or_implicit_callback(api, db, scenario, freeze_business_clock, name):
    freeze_business_clock(scenario['start'])
    before = capacity_snapshot(db)
    result = voice(api, name, {'phone': '+15550100001', 'issue_description': 'Please connect me to a human; no callback.'})
    assert result['success'] is False
    assert result['handoff_status'] == 'unavailable' and result['transfer_completed'] is False
    assert 'Alex E2E' in result['summary']
    assert 'transfer_phone_number' not in result
    assert 'transferred' not in result['message'].lower()
    assert capacity_snapshot(db) == before


def test_portal_missing_owned_calendar_returns_unknown_503_without_effects(api, db, scenario, monkeypatch):
    from serviceBot.services import google_calendar
    staff = db("INSERT INTO staff_agents(name,email,phone_number) VALUES ('Owned portal unknown','portal-unknown@example.test','+15550100009') RETURNING id")[0]['id']
    monkeypatch.setattr(google_calendar, 'fetch_agent_events', native_fetch_agent_events)
    before = capacity_snapshot(db)
    response = api.get('/api/v1/portal/available-slots', params={'date': scenario['date'], 'staff_agent_id': staff})
    assert response.status_code == 503
    assert response.json()['detail']['availability_status'] == 'unknown'
    assert response.json()['detail']['retryable'] is True
    assert capacity_snapshot(db) == before


def test_portal_capacity_sql_failure_is_unknown_not_verified_empty(api, db, scenario, monkeypatch):
    from contextlib import contextmanager

    from serviceBot.db import queries
    real_cursor = queries.dict_cursor
    @contextmanager
    def unavailable_capacity(conn):
        with real_cursor(conn) as cursor:
            class Cursor:
                def execute(self, statement, *args):
                    if 'FROM mock_calendar_slots' in statement:
                        raise RuntimeError('private local capacity diagnostic')
                    return cursor.execute(statement, *args)
                def fetchall(self): return cursor.fetchall()
            yield Cursor()
    before = capacity_snapshot(db)
    monkeypatch.setattr(queries, 'dict_cursor', unavailable_capacity)
    response = api.get('/api/v1/portal/available-slots', params={'date': scenario['date'], 'staff_agent_id': 1})
    assert response.status_code == 503
    assert response.json()['detail']['error_code'] == 'AVAILABILITY_UNKNOWN'
    assert 'private' not in response.text
    assert capacity_snapshot(db) == before


@pytest.mark.parametrize('failure', ['connection', 'staff', 'config'])
def test_portal_initial_observation_failure_is_safe_unknown(api, db, scenario, monkeypatch, failure):
    from contextlib import contextmanager

    from serviceBot.db import queries
    from serviceBot.services import calendar_sync

    before = capacity_snapshot(db)
    def fail(*args, **kwargs):
        raise RuntimeError('private initial observation diagnostic')
    real_cursor = queries.dict_cursor
    @contextmanager
    def unavailable_staff(conn):
        with real_cursor(conn) as cursor:
            class Cursor:
                def execute(self, statement, *args):
                    if 'FROM staff_agents' in statement:
                        fail()
                    return cursor.execute(statement, *args)
                def fetchall(self): return cursor.fetchall()
            yield Cursor()
    if failure == 'connection':
        monkeypatch.setattr(queries, 'get_db_connection', fail)
    elif failure == 'staff':
        monkeypatch.setattr(queries, 'dict_cursor', unavailable_staff)
    else:
        monkeypatch.setattr(calendar_sync, 'get_configured_business_hours', fail)
    response = api.get('/api/v1/portal/available-slots', params={'date': scenario['date'], 'staff_agent_id': 1})
    assert response.status_code == 503
    assert response.json()['detail']['error_code'] == 'AVAILABILITY_UNKNOWN'
    assert response.json()['detail']['available_slots'] == []
    assert 'private' not in response.text
    assert capacity_snapshot(db) == before


@pytest.mark.parametrize('storage', ['varchar', 'timestamp'])
def test_portal_capacity_read_supports_text_and_timestamp_legacy_rows(api, db, scenario, storage):
    # This database is disposable; every converted value is synthetic/known valid.
    db("INSERT INTO service_requests(customer_id,vehicle_id,staff_agent_id,service_type,status,booking_type,booking_time,duration_minutes) VALUES(1,1,1,'Legacy Oil','pending','appointment',%s,60)",
       (scenario['start'].isoformat(),))
    if storage == 'timestamp':
        db('ALTER TABLE service_requests ALTER COLUMN booking_time DROP DEFAULT')
        db('ALTER TABLE service_requests ALTER COLUMN booking_time TYPE timestamp USING booking_time::timestamp')
    try:
        before = capacity_snapshot(db)
        response = api.get('/api/v1/portal/available-slots', params={'date': scenario['date'], 'staff_agent_id': 1})
        assert response.status_code == 200, response.text
        slots = response.json()['available_slots']
        assert slots
        start = scenario['start'].strftime('%Y-%m-%d %H:%M:%S')
        assert all(slot['start_time'] != start for slot in slots)
        assert any(slot['start_time'] == (scenario['start'] + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S') for slot in slots)
        assert capacity_snapshot(db) == before
    finally:
        if storage == 'timestamp':
            db('ALTER TABLE service_requests ALTER COLUMN booking_time TYPE varchar(100) USING booking_time::text')
            db('ALTER TABLE service_requests ALTER COLUMN booking_time SET DEFAULT NULL')


@pytest.mark.parametrize('failure', ['connection', 'cursor', 'staff'])
def test_voice_initial_staff_failure_returns_safe_unknown(api, db, scenario, monkeypatch, failure):
    from contextlib import contextmanager

    from serviceBot.db import queries

    before = capacity_snapshot(db)
    def fail(*args, **kwargs):
        raise RuntimeError('private voice initial staff diagnostic')
    real_cursor = queries.dict_cursor
    @contextmanager
    def unavailable_staff(conn):
        with real_cursor(conn) as cursor:
            class Cursor:
                def execute(self, statement, *args):
                    if 'FROM staff_agents' in statement:
                        fail()
                    return cursor.execute(statement, *args)
                def fetchall(self): return cursor.fetchall()
            yield Cursor()
    if failure == 'connection':
        monkeypatch.setattr(queries, 'get_db_connection', fail)
    elif failure == 'cursor':
        monkeypatch.setattr(queries, 'dict_cursor', fail)
    else:
        monkeypatch.setattr(queries, 'dict_cursor', unavailable_staff)
    result = voice(api, 'check_availability', {'preferred_date': scenario['date']})
    assert result['success'] is False
    assert result['error_code'] == 'AVAILABILITY_UNKNOWN'
    assert result['availability_status'] == 'unknown'
    assert result['available_slots'] == []
    assert result['retryable'] is True
    assert 'private' not in str(result)
    assert capacity_snapshot(db) == before
