"""Owned clone changes and independently bound negative-case provider evidence.

No function runs automatically. The full executor supplies its existing claimed
campaign and provider. Secret header values are passed only as secret dynamic
variables; saved tools and ordinary journals contain placeholders.
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

from .core import SimulationError, fingerprint, private_json
from .evidence import check

_SCOPES = ('conversation_config', 'platform_settings', 'workflow', 'name', 'tags')
_MUTATIONS = {'book_appointment', 'create_service_request', 'reschedule_appointment',
              'cancel_appointment', 'consolidate_appointment_service', 'request_callback'}


# Captured provider defaults from tool-create-readback-defaults-v7.json.
# Only exact neutral values at schema-property nodes are equivalent to absence.
_NEUTRAL_PROPERTY_DEFAULTS = {
    'allowed_values': None, 'allowed_values_dynamic_variable': '',
    'constant_value': '', 'dynamic_variable': '', 'enum': None,
    'is_omitted': False, 'is_system_provided': False,
}


def _snapshot(agent):
    return {key: copy.deepcopy(agent[key]) for key in _SCOPES if key in agent}


def _schema_material(node, *, property_node=False):
    if not isinstance(node, dict):
        return copy.deepcopy(node)
    result = copy.deepcopy(node)
    if property_node:
        for key, neutral in _NEUTRAL_PROPERTY_DEFAULTS.items():
            if key in result and type(result[key]) is type(neutral) and result[key] == neutral:
                del result[key]
    if isinstance(result.get('properties'), dict):
        result['properties'] = {key: _schema_material(value, property_node=True)
                                for key, value in result['properties'].items()}
    if isinstance(result.get('items'), dict):
        result['items'] = _schema_material(result['items'], property_node=True)
    return result


def _material(agent):
    result = _snapshot(agent)
    tools = result.get('conversation_config', {}).get('agent', {}).get('prompt', {}).get('tools', [])
    for tool in tools:
        if tool.get('type') != 'webhook' or not isinstance(tool.get('api_schema'), dict):
            continue
        api = tool['api_schema']
        api.setdefault('path_params_schema', {})
        api.setdefault('query_params_schema', {'properties': {}, 'required': []})
        if api.get('auth_connection', object()) is None:
            api.pop('auth_connection')
        for key in ('request_body_schema', 'query_params_schema'):
            if key in api:
                api[key] = _schema_material(api[key])
        if isinstance(api.get('path_params_schema'), dict):
            api['path_params_schema'] = {key: _schema_material(value, property_node=True)
                                         for key, value in api['path_params_schema'].items()}
    return result


def _owned(adapter, provider):
    adapter._guard()
    manifest = adapter.campaign.manifest
    run, identifier = manifest.get('run_id'), manifest.get('campaign_agent_id')
    if not isinstance(run, str) or not isinstance(identifier, str) or identifier == adapter.config.get('agent_id'):
        raise SimulationError('Case tools require a distinct campaign-owned clone')
    actual = provider.agent(identifier)
    if (actual.get('agent_id') != identifier or actual.get('name') != 'Live simulation ' + run
            or set(actual.get('tags', [])) != {'live_simulation', run}):
        raise SimulationError('Campaign clone ownership differs from provider read-back')
    return actual


def _restore_path(adapter):
    return Path(adapter.campaign.folder) / 'owned-case-agent-restore.json'


def prepare_owned_case_agent(adapter, cid, descriptor, provider):
    if cid not in {'C35', 'C36'}:
        raise SimulationError('Case-specific clone changes are restricted to owned native faults')
    actual = _owned(adapter, provider)
    target, origin = urlsplit(descriptor.get('url', '')), urlsplit(adapter.config['deployed_url'])
    try:
        pieces = target.path.split('/')
        if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
            raise ValueError
        if target.username or target.password or target.query or target.fragment:
            raise ValueError
        if ('/'.join(pieces[:-2]) != '/api/v1/portal/internal/simulation-faults'
                or pieces[-1] != 'tool' or str(uuid.UUID(pieces[-2])) != pieces[-2]
                or descriptor['name'] != 'create_service_request' or descriptor['method'] != 'POST'
                or descriptor['requires_owned_clone_readback'] is not True
                or descriptor['operator_execute_is_agent_proof'] is not False):
            raise ValueError
        credentials = descriptor['credential_bindings']
        expected_env = adapter.config['secrets']['simulation_faults_cron_secret']
        token_path = Path(credentials['lease_token_file'])
        if (credentials['authorization_env'] != expected_env or credentials['authorization_prefix'] != 'Bearer '
                or credentials['lease_header'] != 'X-Simulation-Lease'
                or token_path != Path(adapter.campaign.folder) / (cid.lower() + '-fault-lease.json')
                or token_path.is_symlink() or not token_path.is_file() or token_path.stat().st_mode & 0o077):
            raise ValueError
        auth, lease = os.environ[expected_env], json.loads(token_path.read_text())['lease_token']
        if not isinstance(auth, str) or not auth or not isinstance(lease, str) or not lease:
            raise ValueError
    except (KeyError, TypeError, ValueError, IndexError, OSError):
        raise SimulationError('Owned native fault descriptor or private credential binding is unsafe') from None
    path = _restore_path(adapter)
    if path.exists() or path.is_symlink() or getattr(adapter, '_owned_case_agent', None):
        raise SimulationError('Existing case clone intent must be reconciled before another change')
    original = _snapshot(actual)
    patched = copy.deepcopy(original)
    prompt = patched['conversation_config']['agent']['prompt']
    if prompt.get('tool_ids'):
        raise SimulationError('Case clone must have resolved inline tools only')
    tools = prompt.get('tools', [])
    candidates = [t for t in tools if t.get('name') == 'create_service_request' and t.get('type') == 'webhook']
    if len(candidates) != 1:
        raise SimulationError('Exact native booking tool required on owned clone')
    tool = copy.deepcopy(candidates[0])
    api = copy.deepcopy(tool['api_schema'])
    api.update(url=descriptor['url'], method='POST',
        request_headers={'Authorization': 'Bearer {{secret__simulation_fault_auth}}',
                         'X-Simulation-Lease': '{{secret__simulation_fault_lease}}'},
        request_body_schema=copy.deepcopy(descriptor['request_schema']),
        path_params_schema={}, query_params_schema={'properties': {}, 'required': []})
    api.pop('auth_connection', None)
    tool['api_schema'] = api
    tool['description'] = 'Create this explicitly consented appointment using the exact canonical service, phone and booking time supplied by the caller.'
    prompt['tools'] = [t for t in tools if t.get('name') not in _MUTATIONS] + [tool]
    prompt['prompt'] = prompt.get('prompt', '') + (
        '\nFor this owned simulation use create_service_request to book only after the caller explicitly '
        'confirms the exact service and time. Supply customer_consent_obtained=true only after that confirmation. '
        'Do not substitute service names or repeat a booking after a lost response.')
    record = {'case_id': cid, 'agent_id': actual['agent_id'], 'run_id': adapter.campaign.manifest['run_id'],
              'original': original, 'patched_fingerprint': fingerprint(_material(patched)), 'status': 'patch_intent'}
    private_json(path, record)
    adapter._owned_case_agent = {'case_id': cid, 'variables': {
        'secret__simulation_fault_auth': auth, 'secret__simulation_fault_lease': lease}}
    try:
        provider.request('PATCH', '/v1/convai/agents/' + quote(actual['agent_id'], safe=''), patched)
        if _material(_owned(adapter, provider)) != _material(patched):
            raise SimulationError('Owned clone fault tool read-back differs')
    except Exception:  # noqa: BLE001 - ambiguous writes must stop without replay
        adapter.state['blocked'] = True
        adapter._save()
        raise SimulationError('Case clone change is unknown; inspect and reconcile without replay') from None
    record['status'] = 'patched_verified'
    private_json(path, record)
    return {'case_id': cid, 'agent_id': actual['agent_id'], 'fingerprint': record['patched_fingerprint']}


def case_dynamic_variables(adapter, cid):
    memory = getattr(adapter, '_owned_case_agent', None)
    if memory is None:
        return {}
    if memory['case_id'] != cid:
        raise SimulationError('Case clone secret variables belong to a different case')
    record = json.loads(_restore_path(adapter).read_text())
    if record.get('status') != 'patched_verified':
        raise SimulationError('Case clone is not verified for provider submission')
    return dict(memory['variables'])


def restore_owned_case_agent(adapter, provider):
    path = _restore_path(adapter)
    if not path.exists():
        if getattr(adapter, '_owned_case_agent', None):
            raise SimulationError('Case clone restoration journal is missing')
        return
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise SimulationError('Case clone restoration journal is unsafe')
    record = json.loads(path.read_text())
    actual = _owned(adapter, provider)
    if (record.get('run_id') != adapter.campaign.manifest['run_id']
            or record.get('agent_id') != actual['agent_id']
            or fingerprint(_material(actual)) != record.get('patched_fingerprint')
            or record.get('status') != 'patched_verified'):
        raise SimulationError('Case clone changed; refuse to overwrite concurrent or unknown configuration')
    record['status'] = 'restore_intent'
    private_json(path, record)
    try:
        provider.request('PATCH', '/v1/convai/agents/' + quote(actual['agent_id'], safe=''), record['original'])
        if _material(_owned(adapter, provider)) != _material(record['original']):
            raise SimulationError('Owned clone restoration read-back differs')
    except Exception:  # noqa: BLE001 - ambiguous writes must stop without replay
        adapter.state['blocked'] = True
        adapter._save()
        raise SimulationError('Case clone restoration unknown; reconcile without replay') from None
    # Keep an immutable audit record under its case name; permit the next case.
    record['status'] = 'restored_verified'
    private_json(path.with_name(record['case_id'].lower() + '-owned-agent-restored.json'), record)
    path.unlink()
    adapter._owned_case_agent = None


def _binding(adapter, cid, invocation_id, test_id):
    manifest = json.loads((Path(adapter.campaign.folder) / 'manifest.json').read_text())
    ledger = json.loads((Path(adapter.campaign.folder).parent / 'usage-ledger.json').read_text())
    if (manifest.get('run_id') != adapter.campaign.manifest['run_id']
            or manifest.get('campaign_agent_id') != adapter.campaign.manifest['campaign_agent_id']
            or invocation_id not in manifest.get('invocations', []) or test_id not in manifest.get('provider_tests', [])):
        raise SimulationError('Actual provider identities are not campaign owned')
    entries = [e for e in ledger.get('entries', []) if e.get('invocation_id') == invocation_id]
    if (len(entries) != 1 or any(entries[0].get(k) != v for k, v in {
        'run_id': manifest['run_id'], 'case_id': cid, 'test_id': test_id}.items())):
        raise SimulationError('Actual provider identity differs from common usage ledger')
    return {'run_id': manifest['run_id'], 'agent_id': manifest['campaign_agent_id'],
            'case_id': cid, 'invocation_id': invocation_id, 'test_id': test_id}


def bind_negative_invocation(adapter, cid, invocation_id, test_id, provider):
    if cid not in {'C23', 'C47'}:
        raise SimulationError('Unknown negative provenance case')
    binding = _binding(adapter, cid, invocation_id, test_id)
    actual = _owned(adapter, provider)
    record = adapter.state['full_negative_cases'][cid]
    if record.get('provider_binding'):
        raise SimulationError('Negative invocation cannot be rebound')
    name = 'check_availability' if cid == 'C23' else record['capability']['tool_name']
    tools = actual['conversation_config']['agent']['prompt']['tools']
    matching = [t for t in tools if t.get('name') == name and t.get('type') == 'webhook']
    if len(matching) != 1 or matching[0]['api_schema'].get('method') != 'POST':
        raise SimulationError('Exact native negative tool unavailable')
    url = matching[0]['api_schema']['url']
    target, origin = urlsplit(url), urlsplit(adapter.config['deployed_url'])
    if ((target.scheme, target.netloc) != (origin.scheme, origin.netloc)
            or target.username or target.password or target.fragment
            or target.path != '/api/v1/voice/tools'
            or target.query not in ('', 'name=' + name)):
        raise SimulationError('Negative tool must target the exact native deployed route')
    record['provider_binding'] = binding | {'tool_name': name, 'tool_url': url,
        'arguments_fingerprint': fingerprint(record['arguments'])}
    adapter._save()


def negative_checks(adapter, cid, provider):
    from .deployed_full_negative import unavailable, unknown
    passed = False
    try:
        adapter._guard()
        record = adapter.state['full_negative_cases'][cid]
        binding = record['provider_binding']
        _binding(adapter, cid, binding['invocation_id'], binding['test_id'])
        if fingerprint(record['arguments']) != binding['arguments_fingerprint']:
            raise ValueError
        receipt = provider.get(binding['invocation_id'])
        runs = receipt['test_runs']
        if (receipt['id'] != binding['invocation_id'] or receipt['agent_id'] != binding['agent_id']
                or receipt['cancelled'] is not False or len(runs) != 1):
            raise ValueError
        run = runs[0]
        if (run['test_id'] != binding['test_id'] or run['test_invocation_id'] != binding['invocation_id']
                or run['status'] not in {'passed', 'failed'}):
            raise ValueError
        calls, results = [], []
        for response in run['agent_responses']:
            for call in response.get('tool_calls', []):
                if call.get('tool_name') in _MUTATIONS:
                    raise ValueError
                if call.get('tool_name') == binding['tool_name']:
                    calls.append(call)
            results.extend(r for r in response.get('tool_results', []) if r.get('tool_name') == binding['tool_name'])
        if len(calls) != 1 or len(results) != 1:
            raise ValueError
        call, result = calls[0], results[0]
        args = json.loads(call['params_as_json']) if isinstance(call['params_as_json'], str) else call['params_as_json']
        value = json.loads(result['result_value']) if isinstance(result['result_value'], str) else result['result_value']
        value = value.get('result', value)
        expected = record['arguments']
        # A handoff summary is model-generated; its presence is checked while
        # the designated phone is immutable. Availability arguments are exact.
        arguments_match = (args == expected if cid == 'C23' else
            args.get('phone') == expected['phone'] and isinstance(args.get('summary_text'), str)
            and bool(args['summary_text'].strip()) and set(args) <= {'phone', 'summary_text'})
        passed = bool(arguments_match and call['type'] == 'webhook' and call['tool_has_been_called'] is True
            and isinstance(call['request_id'], str) and bool(call['request_id'])
            and result['request_id'] == call['request_id'] and result['is_error'] is False
            and call['tool_details']['type'] == 'webhook' and call['tool_details']['method'] == 'POST'
            and call['tool_details']['url'] == binding['tool_url']
            and (unknown(value) if cid == 'C23' else unavailable(value)))
    except (KeyError, TypeError, ValueError, AttributeError, OSError, SimulationError):
        passed = False
    return [check('actual owned invocation has paired native negative tool call and result', passed)]
