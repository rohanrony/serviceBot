"""Exact customer ownership gates voice mutations over HTTP and PostgreSQL."""
from datetime import timedelta

import pytest

from e2e.test_voice_and_reporting import voice
from e2e.test_workflows import book


def snapshot(db):
    tables = ('service_requests', 'appointment_reservations', 'appointment_reservation_segments',
              'service_request_audit_log', 'outbox_notifications', 'sms_messages')
    return {table: db(f'SELECT row_to_json(t) AS value FROM {table} t ORDER BY row_to_json(t)::text') for table in tables}


@pytest.mark.parametrize('tool', ['cancel_appointment', 'reschedule_appointment', 'consolidate_appointment_service'])
@pytest.mark.parametrize('invalid', ['foreign', 'malformed', 'foreign_source', 'suffix_collision'])
def test_rejected_mutation_preserves_booking_reservations_history_and_provider_queue(api, db, scenario, tool, invalid):
    own = book(api, scenario)
    other = book(api, scenario, phone='+15550100002', agent=2)
    args = {'phone': '+15550100001', 'appointment_id': str(own),
            'new_appointment_datetime': (scenario['start'] + timedelta(hours=1)).isoformat(),
            'additional_duration_minutes': 30, 'additional_service_type': 'Oil Change'}
    if invalid == 'foreign':
        args['appointment_id'] = str(other)
    elif invalid == 'malformed':
        args['appointment_id'] = 'not-an-id'
    elif invalid == 'foreign_source':
        args['source_appointment_ids'] = [str(other)]
    else:
        # Caller has no full-phone match; the last seven digits match the foreign owner.
        args.update(phone='+16660100002', appointment_id=str(other))
    before = snapshot(db)
    result = voice(api, tool, args)
    assert result['success'] is False
    assert result['error_code'] == 'APPOINTMENT_OWNERSHIP_REQUIRED'
    assert snapshot(db) == before


@pytest.mark.parametrize('tool', ['cancel_appointment', 'reschedule_appointment', 'consolidate_appointment_service'])
@pytest.mark.parametrize('explicit_id', [True, False])
def test_owned_string_id_or_unambiguous_default_preserves_valid_domain_mutations(api, db, scenario, tool, explicit_id):
    # The shared fixture already has an unscheduled pending request for 0001.
    # Use an empty owned customer baseline to exercise an unambiguous default.
    owner_phone = '+15550100001' if explicit_id else '+15550100999'
    own = book(api, scenario, phone=owner_phone)
    args = {'caller_phone': owner_phone, 'appointment_id': str(own),
            'new_appointment_datetime': (scenario['start'] + timedelta(hours=1)).isoformat(),
            'additional_duration_minutes': 30, 'additional_service_type': 'Oil Change',
            'additional_issue': 'Additional inspection'}
    if not explicit_id:
        args.pop('appointment_id')
    result = voice(api, tool, args)
    assert result['success'] is True, result
    row = db('SELECT status,duration_minutes,booking_time FROM service_requests WHERE id=%s', (own,))[0]
    if tool == 'cancel_appointment':
        assert row['status'] == 'cancelled'
        assert not db("SELECT id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'", (own,))
    elif tool == 'reschedule_appointment':
        assert str(row['booking_time'])[:19].replace(' ', 'T') == args['new_appointment_datetime'][:19]
    else:
        assert row['duration_minutes'] == 90
    assert db('SELECT id FROM outbox_notifications WHERE request_id=%s', (own,))


@pytest.mark.parametrize('alias', ['source_appointment_ids', 'source_appointment_id', 'cancelled_appointment_ids'])
def test_owned_source_alias_reaches_domain_and_preserves_other_customer(api, db, scenario, alias):
    target = book(api, scenario)
    source = book(api, scenario, start=scenario['start'] + timedelta(hours=3))
    foreign = book(api, scenario, phone='+15550100002', agent=2)
    foreign_before = db('SELECT row_to_json(s) AS value FROM service_requests s WHERE id=%s', (foreign,))
    result = voice(api, 'consolidate_appointment_service', {
        'phone': '+15550100001', 'appointment_id': str(target), alias: str(source),
        'additional_duration_minutes': 60, 'additional_service_type': 'Oil Change',
        'additional_issue': 'Merge existing owned service',
    })
    assert result['success'] is True, result
    assert result['cancelled_source_ids'] == [source]
    assert db('SELECT status,duration_minutes FROM service_requests WHERE id=%s', (target,))[0]['duration_minutes'] == 120
    assert db('SELECT status FROM service_requests WHERE id=%s', (source,))[0]['status'] == 'cancelled_by_customer'
    assert not db("SELECT id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'", (source,))
    assert not db('SELECT seg.* FROM appointment_reservation_segments seg JOIN appointment_reservations r ON r.id=seg.reservation_id WHERE r.service_request_id=%s', (source,))
    assert db('SELECT row_to_json(s) AS value FROM service_requests s WHERE id=%s', (foreign,)) == foreign_before
