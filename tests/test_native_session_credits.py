"""Exact native billing totals under an explicitly verified synthetic unit contract."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_full_session as session
from live_simulations import runner
from live_simulations.core import SimulationError
from live_simulations.provider import ElevenLabs


@pytest.fixture
def setup_and_cleanup_test_db():
    yield


@pytest.fixture
def contract(monkeypatch):
    monkeypatch.setattr(runner, 'time', SimpleNamespace(time=lambda: 1000))
    config = {'budget': {'verified_credit_units': True,
        'native_session_credit_units_verified': True,
        'native_session_credit_subscription_tier': 'legacy-test',
        'monthly_credits': 1000, 'reset_unix': 2000}}
    subscription = {'tier': 'legacy-test', 'status': 'active',
        'character_count': 100, 'character_limit': 1000,
        'next_character_count_reset_unix': 2000, 'character_refresh_period': 'monthly_period'}
    return config, subscription


@pytest.mark.parametrize('status', ['done', 'failed'])
@pytest.mark.parametrize('amount', [0, 3, 123456789])
def test_exact_terminal_native_total(status, amount):
    detail = {'status': status, 'metadata': {'cost': amount,
        'cost_fiat': 0.0001, 'charging': {'call_charge': 999, 'platform_charge': 999,
        'llm_charge': 999, 'free_minutes_consumed': 1, 'llm_price': 5}}}
    assert session.native_credit_reader(detail) == amount
    assert type(session.native_credit_reader(detail)) is int


@pytest.mark.parametrize('detail', [None, [], {}, {'status': 'done'},
    {'status': 'processing', 'metadata': {'cost': 7}},
    {'status': 'done', 'metadata': None}, {'status': 'done', 'metadata': []},
    *[{'status': 'done', 'metadata': {'cost': value}} for value in
      [None, True, False, -1, '3', '', 3.0, 0.5, float('inf'), float('nan'), {}, []]],
    {'status': 'done', 'metadata': {'cost_fiat': 0.001,
        'charging': {'llm_charge': 1, 'call_charge': 2, 'platform_charge': 2}}},
])
def test_invalid_native_total_remains_unknown(detail):
    assert session.native_credit_reader(detail) is None


def test_fresh_quota_requires_verified_matching_account_contract(contract):
    config, sub = contract
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json=sub)
    provider = ElevenLabs('synthetic-key', client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert session.native_credit_remaining(config, provider) == Decimal(900)
    assert requests == [('GET', '/v1/user/subscription')]
    assert config['budget']['native_session_credit_subscription_tier'] == 'legacy-test'


@pytest.mark.parametrize('field,value', [
    ('tier', 'new-minute-plan'), ('status', 'past_due'),
    ('character_refresh_period', 'annual_period'),
    ('character_count', True), ('character_count', '100'), ('character_count', 100.0),
    ('character_count', -1), ('character_count', None),
    ('character_limit', True), ('character_limit', '1000'), ('character_limit', 1000.0),
    ('character_limit', 0), ('character_limit', 999),
    ('next_character_count_reset_unix', True), ('next_character_count_reset_unix', '2000'),
    ('next_character_count_reset_unix', 2000.0), ('next_character_count_reset_unix', 2001),
    ('next_character_count_reset_unix', 999),
])
def test_changed_or_malformed_subscription_denies_admission(contract, field, value):
    config, sub = contract
    sub[field] = value
    with pytest.raises(SimulationError):
        session.native_credit_remaining(config, SimpleNamespace(subscription=lambda: deepcopy(sub)))


@pytest.mark.parametrize('field,value', [
    ('verified_credit_units', False), ('native_session_credit_units_verified', False),
    ('native_session_credit_subscription_tier', None),
    ('native_session_credit_subscription_tier', ''),
])
def test_unit_or_pinned_tier_declarations_cannot_be_omitted(contract, field, value):
    config, _ = contract
    config['budget'][field] = value
    def forbidden():
        raise AssertionError('Missing verified unit contract must stop before a provider GET')
    with pytest.raises(SimulationError):
        session.native_credit_remaining(config, SimpleNamespace(subscription=forbidden))


def test_quota_failure_diagnostics_never_expose_provider_text(contract):
    config, _ = contract
    def failed():
        raise RuntimeError('Bearer private-do-not-retain')
    with pytest.raises(SimulationError) as error:
        session.native_credit_remaining(config, SimpleNamespace(subscription=failed))
    assert 'private-do-not-retain' not in str(error.value)
