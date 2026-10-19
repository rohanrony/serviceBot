"""Remaining deployed coverage is inspectable without paid or fixture effects."""
import copy
from decimal import Decimal

import pytest

from live_simulations import deployed
from live_simulations.core import SimulationError
from live_simulations.deployed_full import FULL_IDS


def config():
    return {
        'target': 'deployed', 'environment': 'STAGING',
        'deployed_url': 'https://example.test',
        'email_receipt_mode': 'operator',
        'variables': {'customer_name': 'Designated', 'customer_phone': '4242704893',
                      'customer_email': 'designated@example.test'},
        'budget': {'verified_credit_units': True, 'monthly_credits': 45676,
                   'remaining_credits': 21904, 'case_upper_estimate': 900},
    }


def forbid_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Preflight must not create resources, claims or paid invocations')
    monkeypatch.setattr(deployed, 'Campaign', forbidden)
    monkeypatch.setattr(deployed, 'claim_stage', forbidden)
    return forbidden


def test_full_preview_is_pure_exact_delta_and_exposes_native_gaps(monkeypatch):
    forbidden = forbid_effects(monkeypatch)
    monkeypatch.setattr(deployed.httpx, 'Client', forbidden)
    cfg = config()
    before = copy.deepcopy(cfg)
    report = deployed.execute(cfg, 'full', requested=list(FULL_IDS))
    assert cfg == before
    assert report['selected'] == list(FULL_IDS)
    assert report['status'] == 'blocked'
    assert report['native_contracts']['blocked_case_ids'] == list(FULL_IDS)
    assert report['native_contracts']['native_inbox_receiving'] == 'unverified'
    assert report['partial_case_estimate_credits'] == '30600'
    assert report['estimated_credits'] is None
    assert report['proposed_credit_ceiling'] is None
    assert report['minimum_paid_invocations'] == 35
    assert report['missing_budget_estimates'] == ['c48_recovery_upper_estimate']
    assert report['remaining_credits'] == '21904'
    assert report['credit_units_verified'] is True
    assert report['estimate_is_measured_bound'] is False
    assert report['new_paid_submissions'] == 0


@pytest.mark.parametrize('requested,repeat', [(None, 1), (['C01', *FULL_IDS], 1),
                                           (list(FULL_IDS[:-1]), 1), (list(FULL_IDS), 2),
                                           (list(reversed(FULL_IDS)), 1), ([*FULL_IDS, 'C17'], 1)])
def test_invalid_or_overlapping_full_scope_stops_before_network(monkeypatch, requested, repeat):
    forbidden = forbid_effects(monkeypatch)
    monkeypatch.setattr(deployed.httpx, 'Client', forbidden)
    with pytest.raises(SimulationError, match='C17-C50'):
        deployed.execute(config(), 'full', requested=requested, repeat=repeat, check=True)


@pytest.mark.parametrize('stage_tier', ['medium', 'full', None])
def test_full_live_never_spends_from_ready_flags_or_stage_declarations(monkeypatch, stage_tier):
    forbidden = forbid_effects(monkeypatch)
    monkeypatch.setattr(deployed.httpx, 'Client', forbidden)
    cfg = config()
    if stage_tier:
        cfg['stage_authorization'] = {'tier': stage_tier, 'credit_ceiling': 40000, 'approved': True}
    cfg['deployed_full'] = {'ready': True, 'capabilities': {cid: True for cid in FULL_IDS}}
    with pytest.raises(SimulationError, match='Full authorization|native full execution'):
        deployed.execute(cfg, 'full', live=True, requested=list(FULL_IDS))


def test_check_reads_current_native_allowance_but_creates_no_stage(monkeypatch):
    forbid_effects(monkeypatch)
    calls = []
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda cfg, client: (calls.append('deployment') or [], []))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda cfg, client: (calls.append('provider') or {'remaining': Decimal(17000)}, []))
    cfg = config()
    cfg['previous_stage_authorization'] = {'tier': 'medium', 'credit_ceiling': 11250}
    before = copy.deepcopy(cfg)
    report = deployed.execute(cfg, 'full', requested=list(FULL_IDS), check=True)
    assert calls == ['deployment', 'provider']
    assert cfg == before
    assert report['remaining_credits'] == '17000'
    assert report['credit_shortfall_to_estimate'] is None
    assert report['partial_case_estimate_credits'] == '30600'
    assert any('c48_recovery_upper_estimate' in problem for problem in report['problems'])
    assert report['native_readiness_checked'] is True
    assert any('medium' in problem.lower() for problem in report['problems'])
    assert report['status'] == 'blocked'


def test_native_readiness_failure_is_retained_as_blocking(monkeypatch):
    forbid_effects(monkeypatch)
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda cfg, client: (['Native identity unavailable'], []))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda cfg, client: ({}, ['Provider quota unavailable']))
    report = deployed.execute(config(), 'full', requested=list(FULL_IDS), check=True)
    assert 'Native identity unavailable' in report['problems']
    assert 'Provider quota unavailable' in report['problems']
    assert report['status'] == 'blocked'
    assert report['new_paid_submissions'] == 0


@pytest.mark.parametrize('extra', [None, True, False, 0, -1, 'NaN', 'Infinity', '-Infinity', float('nan'), float('inf'), -float('inf'), '', [], {}])
def test_missing_or_invalid_recovery_cost_never_masquerades_as_total(monkeypatch, extra):
    forbidden = forbid_effects(monkeypatch)
    monkeypatch.setattr(deployed.httpx, 'Client', forbidden)
    cfg = config()
    cfg['budget']['c48_recovery_upper_estimate'] = extra
    before = copy.deepcopy(cfg)
    report = deployed.execute(cfg, 'full', requested=list(FULL_IDS))
    assert cfg == before
    assert report['partial_case_estimate_credits'] == '30600'
    assert report['estimated_credits'] is None
    assert report['proposed_credit_ceiling'] is None
    assert report['credit_shortfall_to_estimate'] is None
    assert report['missing_budget_estimates'] == ['c48_recovery_upper_estimate']
    assert report['minimum_paid_invocations'] == 35
    assert report['estimate_is_measured_bound'] is False
    assert report['status'] == 'blocked'
    assert report['new_paid_submissions'] == 0
    assert report['native_contracts']['blocked_case_ids'] == list(FULL_IDS)


def test_recovery_estimate_and_case_overrides_reserve_both_c48_phases(monkeypatch):
    forbidden = forbid_effects(monkeypatch)
    monkeypatch.setattr(deployed.httpx, 'Client', forbidden)
    cfg = config()
    cfg['budget'].update(c48_recovery_upper_estimate='1200.5', case_estimates={'C48': 1000, 'C17': 850})
    before = copy.deepcopy(cfg)
    report = deployed.execute(cfg, 'full', requested=list(FULL_IDS))
    assert cfg == before
    assert report['partial_case_estimate_credits'] == '30650'
    assert report['c48_recovery_upper_estimate'] == '1200.5'
    assert report['estimated_credits'] == '31850.5'
    assert report['proposed_credit_ceiling'] == '39813.125'
    assert Decimal(report['proposed_credit_ceiling']) * Decimal('.8') == Decimal(report['estimated_credits'])
    assert report['credit_shortfall_to_estimate'] == '9946.5'
    assert report['missing_budget_estimates'] == []
    assert report['minimum_paid_invocations'] == 35
    assert report['selected'] == list(FULL_IDS)
    assert report['estimate_is_measured_bound'] is False
    assert report['status'] == 'blocked' and report['new_paid_submissions'] == 0
    assert report['native_contracts']['blocked_case_ids'] == list(FULL_IDS)



def test_check_combines_recovery_with_fresh_allowance_without_side_effects(monkeypatch):
    forbid_effects(monkeypatch)
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda cfg, client: ([], []))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda cfg, client: ({'remaining': Decimal(17000)}, []))
    cfg = config()
    cfg['budget']['c48_recovery_upper_estimate'] = 1200
    before = copy.deepcopy(cfg)
    report = deployed.execute(cfg, 'full', requested=list(FULL_IDS), check=True)
    assert cfg == before
    assert report['estimated_credits'] == '31800'
    assert report['proposed_credit_ceiling'] == '39750'
    assert report['remaining_credits'] == '17000'
    assert report['credit_shortfall_to_estimate'] == '14800'
    assert report['minimum_paid_invocations'] == 35
    assert report['native_readiness_checked'] is True
    assert report['status'] == 'blocked' and report['new_paid_submissions'] == 0
    assert report['native_contracts']['blocked_case_ids'] == list(FULL_IDS)
