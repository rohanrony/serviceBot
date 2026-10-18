"""Native writes have their own bounded timeout and remain unknown on timeout."""
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_medium as medium
from live_simulations.core import SimulationError


def campaign(config):
    snapshots = []
    result = SimpleNamespace(config={'deployed_url': 'https://app.example.test', **config},
                             manifest={'stage_authorization': {'id': 'owned'}})
    result.save = lambda: snapshots.append(deepcopy(result.manifest))
    return result, snapshots


@pytest.mark.parametrize('configured', [None, 75])
def test_native_timeout_overrides_client_default_without_changing_it(configured, monkeypatch):
    config = {} if configured is None else {'native_mutation_timeout_seconds': configured}
    owned, snapshots = campaign(config)
    clock = iter([10.0, 12.5])
    monkeypatch.setattr(medium, '_monotonic', lambda: next(clock))
    expected = 120 if configured is None else configured

    def respond(request):
        op = snapshots[-1]['deployed_medium']['operations'][-1]
        assert op['status'] == 'intent'
        assert op['timeout_seconds'] == expected
        assert request.extensions['timeout']['read'] == expected
        return httpx.Response(200, json={'success': True, 'id': 123})

    with httpx.Client(transport=httpx.MockTransport(respond), timeout=30) as client:
        result = medium.Adapter(owned, client)._mutate('POST', '/owned', {})
        assert result['id'] == 123
        assert client.timeout.read == 30
    op = snapshots[-1]['deployed_medium']['operations'][-1]
    assert op['status'] == 'observed'
    assert op['elapsed_seconds'] == 2.5


@pytest.mark.parametrize('value', [0, -1, 121, True, '120', float('inf'), float('nan')])
def test_invalid_timeout_fails_before_journal_or_network(value):
    owned, snapshots = campaign({'native_mutation_timeout_seconds': value})
    calls = []
    with (httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r))) as client,
          pytest.raises(SimulationError, match='timeout')):
        medium.Adapter(owned, client)._mutate('POST', '/owned', {})
    assert not snapshots
    assert not calls


def test_timeout_records_elapsed_but_never_retries_or_serializes_error_text(monkeypatch):
    owned, snapshots = campaign({})
    clock = iter([4.0, 124.25])
    monkeypatch.setattr(medium, '_monotonic', lambda: next(clock))
    calls = []

    def respond(request):
        calls.append(request)
        assert request.extensions['timeout']['read'] == 120
        raise httpx.ReadTimeout('secret-response-and-credentials', request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        adapter = medium.Adapter(owned, client)
        with pytest.raises(SimulationError, match='unknown'):
            adapter._mutate('POST', '/owned', {})
        op = snapshots[-1]['deployed_medium']['operations'][-1]
        assert op['status'] == 'unknown'
        assert op['timeout_seconds'] == 120
        assert op['elapsed_seconds'] == 120.25
        assert op['diagnostic']['error_type'] == 'ReadTimeout'
        assert 'secret-response-and-credentials' not in json.dumps(snapshots)
        with pytest.raises(SimulationError, match='reconciliation'):
            adapter._mutate('POST', '/owned', {})
        assert len(calls) == 1
