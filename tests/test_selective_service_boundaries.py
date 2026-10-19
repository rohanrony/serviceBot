"""Selective removal must never fall through to whole-visit cancellation."""
import ast
import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from serviceBot.api import telephony
from serviceBot.main import app
from serviceBot.services.booking import BookingService


@pytest.fixture(scope='session', autouse=True)
def setup_and_cleanup_test_db():
    yield


@pytest.fixture
def effects(monkeypatch):
    selective = Mock(return_value={'success': True, 'removed_service': 'Oil Change',
                                  'duration_minutes': 30, 'message': 'Projection queued'})
    whole = Mock(return_value={'success': True})
    monkeypatch.setattr(BookingService, 'remove_appointment_service', selective, raising=False)
    monkeypatch.setattr(telephony, 'cancel_appointment', whole)
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 7}])
    return selective, whole


def cancel(arguments):
    return asyncio.run(telephony.voice_tools({'name': 'cancel_appointment', 'arguments': {
        'phone': '+14242704893', 'appointment_id': 7, **arguments,
    }}))['result']


@pytest.mark.parametrize('name', [None, '', '  ', 7, False, ['Oil Change']])
def test_explicit_invalid_service_never_cancels_visit(effects, name):
    result = cancel({'service_name': name})
    assert result['success'] is False
    for effect in effects:
        effect.assert_not_called()


def test_foreign_selection_never_reaches_either_domain(effects):
    result = cancel({'appointment_id': 99, 'service_name': 'Oil Change'})
    assert result['error_code'] == 'APPOINTMENT_OWNERSHIP_REQUIRED'
    for effect in effects:
        effect.assert_not_called()


def test_exact_selective_service_delegates_and_returns_truthful_domain_result(effects):
    selective, whole = effects
    result = cancel({'service_name': 'Oil Change', 'reason': 'No longer needed'})
    selective.assert_called_once_with(request_id=7, service_name='Oil Change',
        customer_consent_obtained=True, triggered_by='voice_agent', reason='No longer needed')
    assert result == selective.return_value
    whole.assert_not_called()


def test_selective_domain_rejection_is_not_whole_cancellation(effects):
    selective, whole = effects
    selective.return_value = {'success': False, 'message': 'Unknown service'}
    assert cancel({'service_name': 'Unknown'}) == selective.return_value
    whole.assert_not_called()


def test_selective_domain_exception_never_falls_through(effects):
    selective, whole = effects
    selective.side_effect = ValueError('Component snapshot is stale')
    assert cancel({'service_name': 'Oil Change'})['success'] is False
    whole.assert_not_called()


def test_omitted_service_keeps_whole_visit_cancellation(effects):
    selective, whole = effects
    assert cancel({})['success'] is True
    whole.assert_called_once()
    selective.assert_not_called()


@pytest.mark.parametrize('body', [
    {'service_name': 'Oil Change'},
    {'service_name': 'Oil Change', 'customer_consent_obtained': False},
    {'service_name': 'Oil Change', 'customer_consent_obtained': 'true'},
    {'service_name': None, 'customer_consent_obtained': True},
    {'service_name': '  ', 'customer_consent_obtained': True},
    {'service_name': 7, 'customer_consent_obtained': True},
])
def test_portal_requires_exact_name_and_explicit_boolean_consent(effects, body):
    response = TestClient(app).post('/api/v1/portal/service-requests/7/remove-service', json=body)
    assert response.status_code in (400, 422)
    for effect in effects:
        effect.assert_not_called()


def test_portal_selective_delegation_preserves_domain_result(effects):
    selective, whole = effects
    response = TestClient(app).post('/api/v1/portal/service-requests/7/remove-service', json={
        'service_name': 'Oil Change', 'customer_consent_obtained': True,
    })
    assert response.status_code == 200
    assert response.json() == selective.return_value
    selective.assert_called_once_with(request_id=7, service_name='Oil Change',
        customer_consent_obtained=True, triggered_by='portal')
    whole.assert_not_called()


def test_static_cancel_schema_exposes_optional_selective_service_without_importing_sync():
    # The sync script performs .env/provider work at module scope. Inspect only
    # its syntax tree; never import or execute it during validation.
    path = Path(__file__).resolve().parents[1] / 'scripts/sync_elevenlabs_tools.py'
    tree = ast.parse(path.read_text())
    tools = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'TOOL_DEFINITIONS' for target in node.targets))
    cancel_node = next(node for node in tools.elts if any(
        isinstance(key, ast.Constant) and key.value == 'name'
        and isinstance(value, ast.Constant) and value.value == 'cancel_appointment'
        for key, value in zip(node.keys, node.values)))
    class StaticURL(ast.NodeTransformer):
        def visit_Name(self, node):
            assert node.id == 'WEBHOOK_URL'
            return ast.Constant(value='offline-schema-inspection')
    definition = ast.literal_eval(StaticURL().visit(cancel_node))
    body = definition['api_schema']['request_body_schema']
    assert 'service_name' not in body['required']
    assert body['properties']['service_name']['type'] == 'string'
    assert 'whole linked visit' in definition['description']
