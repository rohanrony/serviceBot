"""Integration contracts for source-complete fixtures; no live effects."""
from datetime import datetime
from types import SimpleNamespace

import pytest
from psycopg2.extensions import cursor as tuple_cursor

from live_simulations import deployed_full_negative as negative
from serviceBot.services import simulation_staff


@pytest.mark.parametrize('change', ["role='Adviser'", "name=name||'-edited'"])
def test_owned_staff_cleanup_preserves_every_intervening_staff_edit(change):
    from serviceBot.db.connection import get_db_connection
    with get_db_connection() as conn:
        owned = simulation_staff.create(conn, 'edited-staff-' + str(abs(hash(change))), 'synthetic-key')
        with conn.cursor(cursor_factory=tuple_cursor) as cur:
            cur.execute('UPDATE staff_agents SET ' + change + ' WHERE id=%s', (owned['staff_id'],))
        conn.commit()
        with pytest.raises(simulation_staff.LifecycleDenied):
            simulation_staff.cleanup(conn, owned['receipt'], 'synthetic-key')


@pytest.mark.parametrize('change', ["description='operator edit'", "price_range='$10'", 'req_location=NOT COALESCE(req_location,FALSE)'])
def test_owned_cleanup_preserves_every_intervening_service_edit(change):
    from serviceBot.db.connection import get_db_connection
    with get_db_connection() as conn:
        owned = simulation_staff.create(conn, 'edited-service-' + str(abs(hash(change))), 'synthetic-key')
        with conn.cursor(cursor_factory=tuple_cursor) as cur:
            cur.execute('UPDATE services SET ' + change + ' WHERE id=%s', (owned['service_id'],))
        conn.commit()
        with pytest.raises(simulation_staff.LifecycleDenied):
            simulation_staff.cleanup(conn, owned['receipt'], 'synthetic-key')


def test_unknown_fixture_uses_server_owned_pair_without_remapping_original_catalog(monkeypatch):
    policy = {'min_booking_buffer_hours': 4, 'business_days': [0, 1, 2, 3, 4],
              'business_hours_start': 7, 'business_hours_end': 18}
    owned = {'id': 90, 'service_id': 91, 'service_name': 'server-owned-c23', 'cleanup_complete': False}
    adapter = SimpleNamespace(config={'app_config': {'business_timezone': 'UTC'}}, state={'services': {'oil': {'id': 1, 'name': 'original oil'}}},
                              _policy=lambda: policy, _save=lambda: None)
    def create(a):
        a.state['full_unconnected_staff'] = owned
        return owned
    observed = []
    monkeypatch.setattr(negative, 'create_owned_staff', create)
    monkeypatch.setattr(negative, '_verify_unconnected', lambda a, **kw: observed.append(kw))
    monkeypatch.setattr(negative, 'observe', lambda a, cid, name, args: observed.append(args))
    monkeypatch.setattr(negative.medium, '_now', lambda config: datetime.fromisoformat('2030-01-07T09:00:00+00:00'))
    # Tests an internal compiled-source path, not native admission or config flags.
    monkeypatch.setattr(negative, 'native_setup_allowed', lambda: True)
    negative.arrange_unknown(adapter, {'appointment_time': '2030-01-08T10:00:00+00:00'})
    assert adapter.state['services']['oil'] == {'id': 1, 'name': 'original oil'}
    assert 'mapping_restore' not in adapter.state
    assert observed[0] == {'active': True, 'mapped': [91]}
    assert observed[-1]['service_type'] == 'server-owned-c23'


def test_negative_footprint_excludes_only_journaled_owned_pair(monkeypatch):
    adapter = SimpleNamespace(config={}, state={'services': {'oil': {'id': 1}},
                                               'full_unconnected_staff': {'id': 90, 'service_id': 91}})
    seen = []
    def read(config, statement, params):
        seen.append(params)
        return [{'scope': s, 'rows': 0, 'fingerprint': '0'*32} for s in (
            *negative.BUSINESS_TABLES, 'original_services', 'original_service_mappings', 'original_staff', 'oauth_identity')]
    monkeypatch.setattr(negative.medium, '_read', read)
    negative.footprint(adapter)
    assert set(seen[0][0]) == {1, 91}
    assert seen[0][2] == 90


def test_owned_lifecycle_capability_probe_is_authenticated_and_read_only(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serviceBot.api.portal import router
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setenv('SIMULATION_STAFF_ENABLED', 'true')
    monkeypatch.setenv('CRON_SECRET', 'offline-local-probe')
    with TestClient(app) as client:
        assert client.get('/api/v1/portal/internal/simulation-staff').status_code == 403
        response = client.get('/api/v1/portal/internal/simulation-staff',
                              headers={'Authorization': 'Bearer offline-local-probe'})
    assert response.status_code == 200
    assert response.json() == {'success': True, 'enabled': True, 'capability': 'owned-staff-v1'}
