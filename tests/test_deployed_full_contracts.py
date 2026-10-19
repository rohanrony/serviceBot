"""Offline contract gates never manufacture deployed evidence."""
import json
from pathlib import Path

import pytest

from live_simulations.core import SimulationError
from live_simulations.deployed_full import (
    CASE_CONTRACTS,
    FULL_IDS,
    readiness,
    validate_delta,
)
from live_simulations.deployed_full_adapter import SUPPORTED_CASE_IDS


@pytest.fixture
def cases():
    return json.loads(Path('live_simulations/scenarios.json').read_text())[16:]


def test_exact_catalog_contracts(cases):
    assert tuple(CASE_CONTRACTS) == FULL_IDS == tuple(c['id'] for c in cases)
    for case in cases:
        contract = CASE_CONTRACTS[case['id']]
        assert contract.setup == case['setup']
        assert all((contract.mechanisms, contract.owned_resources, contract.expected_effects,
                    contract.forbidden_effects, contract.assertions, contract.observations,
                    contract.cleanup, contract.prerequisites))
    validate_delta(cases)


@pytest.mark.parametrize('change', ['earlier', 'repeat', 'partial', 'order', 'scope', 'fixture'])
def test_delta_rejects_scope_drift(cases, change):
    kwargs = {}
    if change == 'earlier': cases[0] = dict(cases[0], id='C16')
    if change == 'repeat': kwargs['repeat'] = 2
    if change == 'partial': cases.pop()
    if change == 'order': cases.reverse()
    if change == 'scope': kwargs['tier'] = 'medium'
    if change == 'fixture': cases[0] = dict(cases[0], setup='foreign_customer')
    with pytest.raises(SimulationError): validate_delta(cases, **kwargs)


def test_flags_do_not_prove_native_capability(cases):
    report = readiness({'deployed_full': {'ready': True}, 'native_inbox_mode': 'unverified'}, cases,
                       capabilities={cid: {'ready': True} for cid in FULL_IDS})
    assert report['ready'] is False
    assert report['supported_case_ids'] == sorted(SUPPORTED_CASE_IDS)
    assert report['unsupported_case_ids'] == [cid for cid in FULL_IDS if cid not in SUPPORTED_CASE_IDS]
    assert report['blocked_case_ids'] == list(FULL_IDS)
    assert report['native_inbox_receiving'] == 'unverified'
    assert len(report['cases']) == 34


def test_implementation_support_is_source_owned_and_does_not_prove_native_readiness(cases):
    report = readiness({'deployed_full': {'supported_case_ids': list(FULL_IDS)}}, cases)
    assert report['supported_case_ids'] == sorted(SUPPORTED_CASE_IDS)
    assert report['cases']['C21']['implementation_status'] == 'implemented_offline'
    assert report['cases']['C25']['implementation_status'] == 'implemented_offline'
    assert report['cases']['C30']['implementation_status'] == 'implemented_offline'
    assert report['cases']['C31']['implementation_status'] == 'implemented_offline'
    assert report['cases']['C23']['implementation_status'] == 'partial_blocked'
    assert 'C23' in report['unsupported_case_ids']
    assert report['cases']['C47']['implementation_status'] == 'implemented_offline'
    assert report['cases']['C38']['implementation_status'] == 'missing'
    assert report['ready'] is False
    assert report['blocked_case_ids'] == list(FULL_IDS)


@pytest.mark.parametrize(('cid', 'fragment'), [
    ('C30', 'selected-only'), ('C41', 'voice-bypass'), ('C33', 'distinct customer'), ('C38', 'unenrolled'),
    ('C45', 'distinct original sender'), ('C23', 'local gateway'),
    ('C35', 'local gateway'), ('C36', 'local gateway'),
    ('C48', 'seeded booking'), ('C50', 'synthetic signature'),
])
def test_native_substitutes_remain_blocking(cases, cid, fragment):
    report = readiness({}, cases)
    assert fragment in ' '.join(report['cases'][cid]['blockers'])


def test_untagged_service_uses_any_eligible_allowlisted_active_technician():
    contract = CASE_CONTRACTS['C26']
    assert contract.expected_effects == ('eligible active technician assigned under mappingless service policy',)
    assert 'inactive or ineligible assignment' in contract.forbidden_effects
    assert 'all possible eligible technician destinations must be allowlisted' in contract.prerequisites


def test_unenrolled_case_requires_real_provider_failure_without_false_delivery():
    contract = CASE_CONTRACTS['C38']
    assert contract.expected_effects == ('actual unenrolled-provider rejection or failure persisted',)
    assert 'false delivery claim' in contract.forbidden_effects
    assert any('actual provider unenrolled state' in prerequisite for prerequisite in contract.prerequisites)


def test_unknown_calendar_is_disconnected_dependency_and_handoff_needs_actual_absence(cases):
    assert 'external Google outage' in ' '.join(CASE_CONTRACTS['C23'].prerequisites)
    assert 'unconnected' in ' '.join(CASE_CONTRACTS['C23'].mechanisms)
    assert 'business-window' in ' '.join(CASE_CONTRACTS['C47'].prerequisites)
    assert 'capability absence' in ' '.join(CASE_CONTRACTS['C47'].prerequisites)
    report = readiness({}, cases)
    assert report['cases']['C23']['status'] == report['cases']['C47']['status'] == 'blocked'
    assert report['cases']['C23']['native_setup_allowed'] is False
