"""Unknown native writes retain bounded diagnostics without response text."""
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from live_simulations.core import SimulationError
from live_simulations.deployed_medium import Adapter


@pytest.mark.parametrize(('failure', 'stage', 'kind', 'status', 'error_type'), [
    ('transport', 'request', 'transport', None, 'ReadTimeout'),
    ('http', 'http_status', 'rejected', 403, 'HTTPStatusError'),
    ('json', 'decode', 'unknown', 200, 'JSONDecodeError'),
    ('result', 'result', 'rejected', 200, 'SimulationError'),
])
def test_unknown_write_diagnostic_is_sanitized_and_stops_next_mutation(
    failure, stage, kind, status, error_type,
):
    secret = 'credential-and-customer-must-never-appear'
    calls, snapshots = [], []
    manifest = {'stage_authorization': {'id': 'owned'}}
    campaign = SimpleNamespace(config={'deployed_url': 'https://app.example.test'}, manifest=manifest)
    campaign.save = lambda: snapshots.append(deepcopy(manifest))

    def respond(request):
        calls.append(request)
        assert snapshots[-1]['deployed_medium']['operations'][-1]['status'] == 'intent'
        if failure == 'transport':
            raise httpx.ReadTimeout(secret, request=request)
        if failure == 'http':
            return httpx.Response(403, text=secret)
        if failure == 'json':
            return httpx.Response(200, text=secret)
        return httpx.Response(200, json={'success': False, 'message': secret})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        adapter = Adapter(campaign, client)
        with pytest.raises(SimulationError, match='unknown') as raised:
            adapter._mutate('PATCH', '/owned-path', {'id': 123})
        operation = manifest['deployed_medium']['operations'][-1]
        assert operation['diagnostic'] == {
            'error_type': error_type, 'status_code': status, 'stage': stage, 'kind': kind,
        }
        assert secret not in json.dumps(manifest)
        assert secret not in str(raised.value)
        assert operation['status'] == 'unknown'
        assert manifest['deployed_medium']['blocked']
        with pytest.raises(SimulationError, match='reconciliation'):
            adapter._mutate('PATCH', '/owned-path', {'id': 123})
        assert len(calls) == 1
