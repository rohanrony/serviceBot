"""Exact deployed service vocabulary reaches the captured simulator create API."""
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from live_simulations.core import load_catalog, render
from live_simulations.deployed_medium import Adapter
from live_simulations.provider import ElevenLabs

SERVICES = {
    'oil': {'name': 'LIVE TEST owned Oil Change', 'price_range': '$79-$119', 'duration_minutes': 45},
    'second': {'name': 'LIVE TEST owned Tire Rotation', 'price_range': '$39-$89', 'duration_minutes': 30},
    'split': {'name': 'LIVE TEST owned Brake Inspection', 'price_range': '$150-$350', 'duration_minutes': 60},
}
VALUES = {
    'customer_name': 'Fixture Person', 'customer_phone': '4242704893',
    'appointment_time': '2026-11-09 10:00:00', 'new_time': '2026-11-10 10:00:00',
    'callback_time': '2026-11-09 14:00:00',
}


def captured(cid):
    original = next(case for case in load_catalog() if case['id'] == cid)
    untouched = deepcopy(original)
    campaign = SimpleNamespace(config={}, manifest={'deployed_medium': {
        'services': deepcopy(SERVICES), 'owned_request_ids': [],
    }})
    adapter = Adapter(campaign, None)
    adapted = adapter._adapt(original)
    payloads = []

    def respond(request):
        assert request.method == 'POST'
        assert request.url.path == '/v1/convai/agent-testing/create'
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'captured-test'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        ElevenLabs('synthetic-key', client).create(render(adapted, VALUES), 'owned', VALUES, {})
    assert original == untouched
    return original, payloads[0]


@pytest.mark.parametrize('cid', [f'C{i:02}' for i in range(7, 17) if i != 12])
def test_exact_service_names_lead_actual_provider_payload(cid):
    original, payload = captured(cid)
    keys = ['oil', 'second'] if cid in ('C10', 'C13') else ['oil', 'split'] if cid in ('C14', 'C15', 'C16') else ['oil']
    names = [SERVICES[key]['name'] for key in keys]
    opening = 'Use these exact service names from the start of the conversation: ' + '; '.join(names) + '.'
    assert payload['simulation_scenario'].startswith(opening)
    lifecycle = render(original['scenario'], VALUES)
    for generic, key in [('Oil Change', 'oil'), ('Tire Rotation', 'second'), ('Brake Inspection', 'split')]:
        lifecycle = lifecycle.replace(generic, SERVICES[key]['name'])
    if cid == 'C08':
        lifecycle = lifecycle.replace('Ask for the occupied', f"Ask for {SERVICES['oil']['name']} at the occupied")
    assert lifecycle in payload['simulation_scenario']
    for key in keys if cid in {'C07', 'C08', 'C09', 'C11', 'C13', 'C14'} else []:
        service = SERVICES[key]
        assert any(f"{service['name']}: {service['price_range']}, {service['duration_minutes']} minutes" in condition for condition in payload['success_conditions'])
    assert payload['tool_mock_config']['mocked_tool_ids'] == []


def test_occupied_opening_explicitly_requests_owned_service_before_time():
    _, payload = captured('C08')
    assert f"Ask for {SERVICES['oil']['name']} at the occupied {VALUES['appointment_time']}" in payload['simulation_scenario']
    assert 'Never accept a claimed booking in the occupied slot.' in payload['simulation_scenario']
    assert f"explicitly accept {VALUES['new_time']} if it is available" in payload['simulation_scenario']


def test_callback_does_not_seed_a_catalog_appointment():
    original, payload = captured('C12')
    assert payload['simulation_scenario'].startswith(render(original['scenario'], VALUES))
    assert all(service['name'] not in payload['simulation_scenario'] for service in SERVICES.values())
    assert not any('quote the actual requested catalog service facts' in condition for condition in payload['success_conditions'])
