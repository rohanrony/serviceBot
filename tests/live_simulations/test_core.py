"""Offline contracts for paid-work admission; no provider requests."""
from decimal import Decimal

import pytest

from live_simulations.core import Budget, SimulationError, load_catalog, select_cases, redact


def test_catalog_has_cumulative_coverage_and_complete_recipes():
    catalog = load_catalog()
    assert [len(select_cases(catalog, tier)) for tier in ('minimal', 'medium', 'full')] == [6, 16, 50]
    assert len({c['id'] for c in catalog}) == 50
    for case in catalog:
        assert all(case[k] for k in ('scenario', 'success_conditions', 'checks', 'setup', 'cleanup', 'requirements'))
        assert case['max_turns'] <= 20


def test_selecting_dependent_case_includes_its_setup_chain_but_not_full_tier():
    cases = select_cases(load_catalog(), 'minimal', ['C03'])
    assert [c['id'] for c in cases] == ['C01', 'C02', 'C03']
    with pytest.raises(SimulationError):
        select_cases(load_catalog(), 'minimal', ['C50'])


def test_budget_is_decimal_capped_with_twenty_percent_reserve():
    budget = Budget('10000', 'minimal', '9000')
    assert budget.cap == Decimal('100')
    assert budget.can_start('80')
    assert not budget.can_start('80.01')
    budget.settle('i1', '50')
    assert budget.can_start('30')
    assert not budget.can_start('31')


def test_unknown_billing_or_duplicate_settlement_never_admits_more_spend():
    budget = Budget('10000', 'minimal', '9000')
    budget.settle('i1', None)
    assert not budget.can_start('1')
    with pytest.raises(SimulationError):
        budget.settle('i1', '1')


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '-1', '0'])
def test_invalid_monthly_allowance_fails_closed(amount):
    with pytest.raises(SimulationError):
        Budget(amount, 'minimal', '100')


def test_remaining_quota_is_a_second_limit():
    assert not Budget('10000', 'full', '3').can_start('4')


def test_redaction_masks_nested_secrets_contact_data_and_free_text():
    value = redact({'authorization': 'Bearer secret', 'arguments': {'phone': '+12125551234'},
                    'message': 'Email alex@example.com or +1 (212) 555-1234', 'api_key': 'key'})
    assert 'secret' not in str(value) and 'alex@example.com' not in str(value)
    assert '5551234' not in str(value) and value['api_key'] == '[redacted]'


def test_redaction_preserves_booking_timestamps_and_resource_ids():
    text = 'Booking 2026-10-21 10:00:00 for request 42, provider SMabcdef1234567890abcdef1234567890'
    assert redact(text) == text
