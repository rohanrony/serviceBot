"""Actual PostgreSQL observations for the deployed medium native adapter."""
import os
from datetime import timedelta

import pytest

from e2e.test_live_medium_fixtures import CASES
from e2e.test_live_medium_fixtures import owned_runtime as _owned_runtime
from live_simulations import deployed_medium as medium
from live_simulations import fixtures
from live_simulations.core import SimulationError

owned_runtime = _owned_runtime


def observer(runtime, monkeypatch):
    monkeypatch.setenv('MEDIUM_OFFLINE_OBSERVER', os.environ['TEST_DATABASE_URL'])
    return {**runtime.config, 'deployed_medium': {'database_env': 'MEDIUM_OFFLINE_OBSERVER'}}


def test_observer_reads_native_active_reservations_and_rejects_database_writes(owned_runtime, monkeypatch):
    runtime, values = owned_runtime
    config = observer(runtime, monkeypatch)
    fixtures.arrange(runtime, CASES['C15'], values)
    ids = [r['id'] for r in runtime.rows('SELECT id FROM service_requests')]
    rows = medium._request_rows(config, ids)
    assert len(rows) == 2
    assert {r['customer_phone'] for r in rows} == {values['customer_phone']}
    assert all(r['reservation_status'] == 'ACTIVE' and r['segment_count'] == 4 and r['qualified'] for r in rows)
    assert rows[0]['ends_at'] == rows[1]['starts_at']
    assert rows[-1]['ends_at'] - rows[0]['starts_at'] == timedelta(minutes=120)
    assert all(r['make'] == 'Toyota' and r['model'] == 'Camry' and r['year'] == 2021 for r in rows)
    assert medium._read(config, "SELECT current_setting('transaction_read_only') AS state") == [{'state': 'on'}]
    before = runtime.rows('SELECT id,status FROM service_requests ORDER BY id')
    with pytest.raises(SimulationError, match='read-only observation failed'):
        medium._read(config, "UPDATE service_requests SET status='cancelled' RETURNING id")
    assert runtime.rows('SELECT id,status FROM service_requests ORDER BY id') == before


def test_observer_slot_ownership_witness_detects_active_reservation(owned_runtime, monkeypatch):
    runtime, values = owned_runtime
    config = observer(runtime, monkeypatch)
    from datetime import datetime
    start = datetime.fromisoformat(values['appointment_time'])
    before = medium._slots(config, 1, start, start + timedelta(minutes=60))
    assert len(before) == 4
    assert all(not r['active_reservation'] and not r['service_request_id'] and r['updated_at'] for r in before)
    fixtures.arrange(runtime, CASES['C15'], values)
    after = medium._slots(config, 1, start, start + timedelta(minutes=60))
    assert all(r['active_reservation'] and r['service_request_id'] for r in after)


def test_native_catalog_case_fixture_and_cleanup_preserve_originals(owned_runtime, monkeypatch, api, tmp_path):
    from copy import deepcopy
    from types import SimpleNamespace
    runtime, values = owned_runtime
    config = observer(runtime, monkeypatch)
    owner = 'medium-e2e-owned'
    config.update(deployed_url=runtime.url, variables=values,
                  allowlisted_emails=['test1@example.test', 'test2@example.test'],
                  allowlisted_phone_numbers=['+15550100001', '+15550100002'])
    config['deployed_medium'].update(ownership_id=owner, technician_ids=[1, 2], services={
        'oil': {'name': owner+' Oil', 'duration_minutes': 60, 'price_range': '$60'},
        'second': {'name': owner+' Second', 'duration_minutes': 30, 'price_range': '$30'},
        'split': {'name': owner+' Split', 'duration_minutes': 60, 'price_range': '$60'}})
    runtime.rows("INSERT INTO user_google_accounts(agent_id,email,granted_scopes) VALUES(1,'test1@example.test','https://www.googleapis.com/auth/calendar'),(2,'test2@example.test','https://www.googleapis.com/auth/calendar')")
    original_catalog = api.get('/api/v1/portal/services').json()
    original_staff = api.get('/api/v1/portal/agents').json()
    original_settings = api.get('/api/v1/portal/config').json()
    assert medium.readiness(config, api, [CASES[c] for c in ('C07','C08','C10','C13','C14','C15','C16')], []) == []
    manifest = {'run_id': 'b'*32, 'stage_authorization': {'authorization_id': 'offline-medium'}, 'baseline': []}
    saved = []
    campaign = SimpleNamespace(config=config, manifest=manifest, folder=tmp_path, save=lambda: saved.append(deepcopy(manifest)))
    adapter = medium.Adapter(campaign, api)
    adapter.prepare_catalog()
    def captured_projection(_delay):
        # Capture the asynchronous calendar boundary deterministically. Domain
        # cancellation remains native HTTP; no provider or real sleep occurs.
        ids = sorted(adapter.owned_ids)
        runtime.rows("UPDATE outbox_notifications SET status='DELIVERED' WHERE request_id=ANY(%s) AND event_type='calendar_projection'", [ids])
        runtime.rows("UPDATE service_requests SET calendar_integration_status='DELETED' WHERE id=ANY(%s) AND status='cancelled'", [ids])
        runtime.rows("UPDATE appointment_reservations SET calendar_integration_status='DELETED' WHERE service_request_id=ANY(%s) AND status='CANCELLED'", [ids])
    monkeypatch.setattr(medium, '_sleep', captured_projection)
    assert len(adapter.state['services']) == 3
    for cid in ('C08', 'C10', 'C15', 'C16'):
        adapted, ids = adapter.arrange(CASES[cid], values)
        assert owner in adapted['scenario']
        if cid == 'C08':
            assert ids == []
            assert len(adapter.state['blocks']) == 4
        else:
            assert len(ids) == 2
            assert len(medium._request_rows(config, ids)) == 2
        adapter.cleanup_case()
        assert all(r['status'] == 'cancelled' and r['reservation_id'] is None for r in medium._request_rows(config, ids))
    adapter.cleanup_catalog()
    assert api.get('/api/v1/portal/services').json() == original_catalog
    assert api.get('/api/v1/portal/agents').json() == original_staff
    assert api.get('/api/v1/portal/config').json() == original_settings
    assert all(b['restored'] for b in adapter.state['blocks'])
    assert saved


@pytest.mark.browser
def test_scoped_browser_reload_checks_owned_subset_among_original_rows(owned_runtime, monkeypatch, api, tmp_path, browser_instance):
    from types import SimpleNamespace
    runtime, values = owned_runtime
    config = observer(runtime, monkeypatch)
    config['deployed_url'] = runtime.url
    assert browser_instance.is_connected()
    fixtures.arrange(runtime, CASES['C15'], values)
    # Existing unrelated rows must not make an owned subset read-back fail.
    runtime.rows("INSERT INTO customers(name,phone) VALUES('Unrelated customer','5550100099')")
    runtime.rows("INSERT INTO service_requests(customer_id,service_type) SELECT id,'Unrelated original service' FROM customers WHERE phone='5550100099'")
    ids = [r['id'] for r in runtime.rows("SELECT id FROM service_requests WHERE service_type<>'Unrelated original service'")]
    campaign = SimpleNamespace(config=config, manifest={'stage_authorization': {'authorization_id': 'offline'}}, folder=tmp_path, save=lambda: None)
    adapter = medium.Adapter(campaign, api)
    results = adapter._browser_checks(CASES['C15'], medium._request_rows(config, ids))
    assert results and all(c['passed'] for c in results), results
    assert (tmp_path / 'C15-portal.png').exists()


def test_native_consolidated_c13_requires_both_qualifications_and_full_reservation(owned_runtime, monkeypatch, api, tmp_path):
    from types import SimpleNamespace

    from e2e.test_voice_and_reporting import voice
    runtime, values = owned_runtime
    config = observer(runtime, monkeypatch)
    services = {
        'oil': {'id':1, 'name':'Oil Change', 'duration_minutes':60, 'price_range':'$80-$120'},
        'second': {'id':2, 'name':'Tire Rotation', 'duration_minutes':30, 'price_range':'$30-$50'},
        'split': {'id':3, 'name':'Brake Inspection', 'duration_minutes':60, 'price_range':'$50-$90'}}
    config['deployed_url'] = runtime.url
    config['deployed_medium'].update(technician_ids=[1,2], services=services)
    campaign = SimpleNamespace(config=config, folder=tmp_path, manifest={
        'run_id':'c'*32, 'stage_authorization':{'authorization_id':'offline'}, 'baseline':[],
        'deployed_medium':{'services':services, 'operations':[], 'owned_request_ids':[], 'blocks':[], 'blocked':False}}, save=lambda:None)
    adapter = medium.Adapter(campaign, api)
    rows = adapter._create(values, ['oil'], values['appointment_time'])
    request_id = rows[0]['id']
    result = voice(api, 'consolidate_appointment_service', {'appointment_id':request_id,
        'phone':values['customer_phone'], 'additional_issue':'Tire Rotation',
        'additional_service_type':'Tire Rotation', 'additional_duration_minutes':30})
    assert result['success'], result
    native = medium._request_rows(config, [request_id])
    assert native[0]['service_type'] == 'Oil Change, Tire Rotation'
    assert native[0]['duration_minutes'] == 90 and native[0]['segment_count'] == 6
    assert native[0]['ends_at'] - native[0]['starts_at'] == timedelta(minutes=90)
    # Captured calendar projector acknowledgement, with the native reservation
    # and segment business state created entirely through deployed-style APIs.
    runtime.rows("UPDATE service_requests SET calendar_integration_status='CREATED' WHERE id=%s", [request_id])
    runtime.rows("UPDATE appointment_reservations SET calendar_integration_status='CREATED',calendar_event_id='captured-consolidated' WHERE service_request_id=%s", [request_id])
    assert all(c['passed'] for c in adapter.checks(CASES['C13'], values, [], [{'id':request_id}]))
    runtime.rows('DELETE FROM service_staff_agents WHERE service_id=2 AND staff_agent_id=1')
    assert not all(c['passed'] for c in adapter.checks(CASES['C13'], values, [], [{'id':request_id}]))


def test_native_identity_witness_excludes_other_same_phone_profile_only_from_hazard(owned_runtime, monkeypatch, api):
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C15'], values)
    config = observer(runtime, monkeypatch)
    identity = runtime.rows('SELECT id,name FROM customers WHERE name=%s', [values['customer_name']])[0]
    first_id = runtime.rows('SELECT min(id) AS id FROM service_requests')[0]['id']
    fixtures.actions(runtime, [{'kind':'http', 'path':'/api/v1/voice/tools', 'json':{'name':'cancel_appointment', 'arguments':{'phone':values['customer_phone'], 'appointment_id':first_id}}}], values)
    runtime.rows("INSERT INTO customers(name,phone) VALUES('Other same-phone profile',%s)", ['+1' + values['customer_phone']])
    runtime.rows("INSERT INTO service_requests(customer_id,service_type,status) SELECT id,'Other original issue','pending' FROM customers WHERE name='Other same-phone profile'")
    runtime.rows("INSERT INTO user_google_accounts(agent_id,email,granted_scopes) VALUES(1,'test1@example.test','https://www.googleapis.com/auth/calendar'),(2,'test2@example.test','https://www.googleapis.com/auth/calendar')")
    config.update(deployed_url=runtime.url, variables={**values,
        'appointment_time':'2026-12-07 10:00:00', 'new_time':'2026-12-08 10:00:00', 'callback_time':'2026-12-07 14:00:00'},
        existing_customer_identity=identity,
        allowlisted_emails=['test1@example.test','test2@example.test'],
        allowlisted_phone_numbers=['+15550100001','+15550100002'])
    config['deployed_medium'].update(ownership_id='medium-identity-owned', technician_ids=[1,2], services={
        'oil':{'name': 'medium-identity-owned Oil', 'duration_minutes': 60, 'price_range': '$60'},
        'second':{'name': 'medium-identity-owned Second', 'duration_minutes': 30, 'price_range': '$30'},
        'split':{'name': 'medium-identity-owned Split', 'duration_minutes': 60, 'price_range': '$60'}})
    baseline = api.get('/api/v1/portal/service-requests').json()
    assert len({r['customer_id'] for r in medium._request_rows(config, [r['id'] for r in baseline])}) == 2
    assert medium.readiness(config, api, [CASES['C13']], baseline) == []
    assert api.get('/api/v1/portal/service-requests').json() == baseline
    runtime.rows("INSERT INTO service_requests(customer_id,service_type,status) VALUES(%s,'Same identity undated original','pending')", [identity['id']])
    baseline = api.get('/api/v1/portal/service-requests').json()
    problems = medium.readiness(config, api, [CASES['C13']], baseline)
    assert any('original active or undated' in problem for problem in problems), problems
    assert api.get('/api/v1/portal/service-requests').json() == baseline
