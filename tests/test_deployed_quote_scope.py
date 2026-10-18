"""Existing visits retain consent and identity checks without a fresh booking quote."""
from types import SimpleNamespace

import pytest

from live_simulations.core import load_catalog
from live_simulations.deployed_medium import Adapter


@pytest.mark.parametrize('case', [c for c in load_catalog() if c['id'] in {f'C{i:02}' for i in range(7, 17)}], ids=lambda c: c['id'])
def test_quote_criterion_only_applies_to_requested_new_appointments(case):
    services = {key: {'name': f'owned {name}', 'price_range': '$1-$2', 'duration_minutes': 45}
                for key, name in [('oil', 'Oil Change'), ('second', 'Tire Rotation'), ('split', 'Brake Inspection')]}
    campaign = SimpleNamespace(config={}, manifest={'deployed_medium': {
        'services': services, 'owned_request_ids': []}})
    adapted = Adapter(campaign, None)._adapt(case)
    quote = [c for c in adapted['success_conditions'] if c.startswith('Before any appointment booking quote')]
    assert bool(quote) == (case['id'] in {'C07', 'C08', 'C09', 'C11', 'C13', 'C14'})
    original_nonquote = [c for c in case['success_conditions'] if not c.startswith('Before booking, quote catalog facts accurately:')]
    expected = original_nonquote
    for old, new in [('Oil Change', 'owned Oil Change'), ('Tire Rotation', 'owned Tire Rotation'), ('Brake Inspection', 'owned Brake Inspection')]:
        expected = [c.replace(old, new) for c in expected]
    assert adapted['success_conditions'][:len(expected)] == expected
