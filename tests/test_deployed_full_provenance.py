"""Captured provider contracts; these tests perform no provider calls."""
import copy
import json
from types import SimpleNamespace

import pytest

from live_simulations import deployed_full_provenance as subject
from live_simulations.core import SimulationError, private_json


@pytest.fixture
def env(tmp_path, monkeypatch):
    run = 'a' * 32
    origin = 'https://owned.invalid'
    tools = [{'name': name, 'type': 'webhook', 'api_schema': {
        'method': 'POST', 'url': origin + '/api/v1/voice/tools?name=' + name,
        'request_headers': {}, 'request_body_schema': {'type': 'object'}}}
        for name in ('check_availability', 'create_service_request', 'book_appointment', 'cba_webbook')]
    agent = {'agent_id': 'clone', 'name': 'Live simulation ' + run,
             'tags': ['live_simulation', run], 'conversation_config': {'agent': {
                 'prompt': {'prompt': 'native policy', 'tools': tools, 'tool_ids': []}}}}
    folder = tmp_path / run
    folder.mkdir()
    manifest = {'run_id': run, 'campaign_agent_id': 'clone', 'invocations': ['inv'], 'provider_tests': ['test']}
    private_json(folder / 'manifest.json', manifest)
    private_json(tmp_path / 'usage-ledger.json', {'entries': [{
        'run_id': run, 'case_id': 'C23', 'test_id': 'test', 'invocation_id': 'inv', 'unsettled': True}]})
    adapter = SimpleNamespace(config={'agent_id': 'production', 'deployed_url': origin,
        'secrets': {'simulation_faults_cron_secret': 'OFFLINE_CRON'}},
        campaign=SimpleNamespace(folder=folder, manifest=manifest), state={})
    adapter._guard = lambda: None
    adapter._save = lambda: None
    class Provider:
        def __init__(self): self.current = copy.deepcopy(agent); self.writes = []; self.receipt = None
        def agent(self, identifier): assert identifier == 'clone'; return copy.deepcopy(self.current)
        def request(self, method, path, payload):
            assert method == 'PATCH' and path == '/v1/convai/agents/clone'
            self.writes.append(copy.deepcopy(payload))
            self.current.update(copy.deepcopy(payload))
            return copy.deepcopy(self.current)
        def get(self, invocation): assert invocation == 'inv'; return copy.deepcopy(self.receipt)
    monkeypatch.setenv('OFFLINE_CRON', 'private-cron-value')
    return adapter, Provider(), copy.deepcopy(agent)


def descriptor(adapter):
    token = adapter.campaign.folder / 'c35-fault-lease.json'
    private_json(token, {'lease_token': 'private-lease-value'})
    return {'name': 'create_service_request', 'method': 'POST',
        'url': adapter.config['deployed_url'] + '/api/v1/portal/internal/simulation-faults/11111111-1111-4111-8111-111111111111/tool',
        'credential_bindings': {'authorization_env': 'OFFLINE_CRON', 'authorization_prefix': 'Bearer ',
            'lease_token_file': str(token), 'lease_header': 'X-Simulation-Lease'},
        'request_schema': {'type': 'object', 'properties': {'phone': {'type': 'string'}}, 'required': ['phone']},
        'requires_owned_clone_readback': True, 'operator_execute_is_agent_proof': False}


def test_fault_changes_only_owned_clone_and_restores_exactly_without_persisting_secrets(env):
    adapter, provider, original = env
    subject.prepare_owned_case_agent(adapter, 'C35', descriptor(adapter), provider)
    tools = provider.current['conversation_config']['agent']['prompt']['tools']
    assert 'book_appointment' not in {t['name'] for t in tools}
    tool = next(t for t in tools if t['name'] == 'create_service_request')
    assert tool['api_schema']['request_headers']['Authorization'] == 'Bearer {{secret__simulation_fault_auth}}'
    values = subject.case_dynamic_variables(adapter, 'C35')
    assert values == {'secret__simulation_fault_auth': 'private-cron-value',
                      'secret__simulation_fault_lease': 'private-lease-value'}
    assert 'private-cron-value' not in json.dumps(provider.writes)
    for path in adapter.campaign.folder.glob('*'):
        if path.name != 'c35-fault-lease.json':
            assert 'private-lease-value' not in path.read_text()
            assert 'private-cron-value' not in path.read_text()
    subject.restore_owned_case_agent(adapter, provider)
    assert provider.current == original
    assert subject.case_dynamic_variables(adapter, 'C35') == {}


@pytest.mark.parametrize('mutation', ['primary', 'foreign_name', 'foreign_tag', 'foreign_target', 'unsafe_token'])
def test_clone_and_target_ownership_fail_before_patch(env, mutation):
    adapter, provider, _ = env
    d = descriptor(adapter)
    if mutation == 'primary': adapter.config['agent_id'] = 'clone'
    elif mutation == 'foreign_name': provider.current['name'] = 'shared agent'
    elif mutation == 'foreign_tag': provider.current['tags'] = ['live_simulation', 'other']
    elif mutation == 'foreign_target': d['url'] = 'https://foreign.invalid/tool'
    else: (adapter.campaign.folder / 'c35-fault-lease.json').chmod(0o644)
    with pytest.raises(SimulationError): subject.prepare_owned_case_agent(adapter, 'C35', d, provider)
    assert provider.writes == []


def test_restore_refuses_concurrent_clone_edit(env):
    adapter, provider, _ = env
    subject.prepare_owned_case_agent(adapter, 'C35', descriptor(adapter), provider)
    provider.current['conversation_config']['agent']['prompt']['prompt'] += ' external edit'
    with pytest.raises(SimulationError): subject.restore_owned_case_agent(adapter, provider)
    assert len(provider.writes) == 1


def negative_receipt(name, arguments, result, *, url):
    return {'id': 'inv', 'agent_id': 'clone', 'cancelled': False, 'test_runs': [{
        'test_id': 'test', 'test_invocation_id': 'inv', 'status': 'passed', 'agent_responses': [{
            'tool_calls': [{'type': 'webhook', 'tool_name': name, 'tool_has_been_called': True,
                'request_id': 'call1', 'params_as_json': json.dumps(arguments),
                'tool_details': {'type': 'webhook', 'method': 'POST', 'url': url}}],
            'tool_results': [{'tool_name': name, 'request_id': 'call1', 'is_error': False,
                'result_value': json.dumps({'result': result})}]}]}]}


def test_negative_proof_joins_actual_invocation_call_result_and_immutable_arguments(env):
    adapter, provider, _ = env
    args = {'service_type': 'owned unknown service', 'preferred_date': '2026-11-11',
            'preferred_time': '10:00 AM', 'booking_type': 'appointment'}
    adapter.state['full_negative_cases'] = {'C23': {'arguments': args}}
    subject.bind_negative_invocation(adapter, 'C23', 'inv', 'test', provider)
    result = {'success': False, 'availability_status': 'unknown', 'available_slots': [],
              'error_code': 'AVAILABILITY_UNKNOWN', 'retryable': True}
    provider.receipt = negative_receipt('check_availability', args, result,
        url=adapter.config['deployed_url'] + '/api/v1/voice/tools?name=check_availability')
    assert all(c['passed'] for c in subject.negative_checks(adapter, 'C23', provider))
    provider.receipt['test_runs'][0]['agent_responses'][0]['tool_calls'][0]['params_as_json'] = json.dumps(args | {'service_type': 'Oil Change'})
    assert not all(c['passed'] for c in subject.negative_checks(adapter, 'C23', provider))


def test_negative_cannot_adopt_a_foreign_ledger_entry(env):
    adapter, provider, _ = env
    with pytest.raises(SimulationError): subject.bind_negative_invocation(adapter, 'C47', 'inv', 'test', provider)


def test_negative_rejects_uncorrelated_result_or_mutation_tool(env):
    adapter, provider, _ = env
    args = {'service_type': 'owned service'}
    adapter.state['full_negative_cases'] = {'C23': {'arguments': args}}
    subject.bind_negative_invocation(adapter, 'C23', 'inv', 'test', provider)
    result = {'success': False, 'availability_status': 'unknown', 'available_slots': [],
              'error_code': 'AVAILABILITY_UNKNOWN', 'retryable': True}
    provider.receipt = negative_receipt('check_availability', args, result,
        url=adapter.config['deployed_url'] + '/api/v1/voice/tools?name=check_availability')
    response = provider.receipt['test_runs'][0]['agent_responses'][0]
    response['tool_results'][0]['request_id'] = 'other'
    assert not all(c['passed'] for c in subject.negative_checks(adapter, 'C23', provider))
    response['tool_results'][0]['request_id'] = 'call1'
    response['tool_calls'].append({'tool_name': 'create_service_request'})
    assert not all(c['passed'] for c in subject.negative_checks(adapter, 'C23', provider))


# Neutral fields observed in scratch/full-delta-20261019/tool-create-readback-defaults-v7.json.
_NEUTRAL_PROPERTY_DEFAULTS={'allowed_values':None,'allowed_values_dynamic_variable':'',
    'constant_value':'','dynamic_variable':'','enum':None,'is_omitted':False,'is_system_provided':False}


def normalized_provider(provider):
    original=provider.request
    def normalize_node(node):
        if not isinstance(node,dict): return
        for child in node.get('properties',{}).values():
            for key,value in _NEUTRAL_PROPERTY_DEFAULTS.items(): child.setdefault(key,value)
            normalize_node(child)
        if isinstance(node.get('items'),dict):
            for key,value in _NEUTRAL_PROPERTY_DEFAULTS.items(): node['items'].setdefault(key,value)
            normalize_node(node['items'])
    def request(method,path,payload):
        original(method,path,payload)
        for tool in provider.current['conversation_config']['agent']['prompt']['tools']:
            api=tool.get('api_schema',{})
            api.setdefault('path_params_schema',{})
            api.setdefault('query_params_schema',{'properties':{},'required':[]})
            api.setdefault('auth_connection',None)
            normalize_node(api.get('request_body_schema'))
            normalize_node(api.get('query_params_schema'))
        return copy.deepcopy(provider.current)
    provider.request=request
    return provider


def test_provider_neutral_defaults_allow_exact_patch_and_restoration_readback(env):
    adapter,provider,original=env
    normalized_provider(provider)
    result=subject.prepare_owned_case_agent(adapter,'C35',descriptor(adapter),provider)
    assert result['agent_id']=='clone'
    patched=provider.current['conversation_config']['agent']['prompt']['tools'][-1]['api_schema']
    assert patched['path_params_schema']=={}
    assert patched['query_params_schema']=={'properties':{},'required':[]}
    assert patched['request_body_schema']['properties']['phone']['constant_value']==''
    subject.restore_owned_case_agent(adapter,provider)
    assert subject._material(provider.current)==subject._material(original)


@pytest.mark.parametrize('key,value',[
    ('allowed_values',['foreign']),('allowed_values_dynamic_variable','caller_phone'),
    ('constant_value','foreign'),('dynamic_variable','system__caller_id'),('enum',['foreign']),
    ('is_omitted',True),('is_system_provided',True),('is_system_provided',0),
])
def test_active_property_material_is_never_normalized_away(env,key,value):
    adapter,provider,_=env
    normalized_provider(provider)
    request=provider.request
    def altered(method,path,payload):
        request(method,path,payload)
        tool=provider.current['conversation_config']['agent']['prompt']['tools'][-1]
        tool['api_schema']['request_body_schema']['properties']['phone'][key]=value
        return copy.deepcopy(provider.current)
    provider.request=altered
    with pytest.raises(SimulationError,match='unknown'):
        subject.prepare_owned_case_agent(adapter,'C35',descriptor(adapter),provider)
    assert adapter.state['blocked'] is True and len(provider.writes)==1


@pytest.mark.parametrize('mutation',['header','url','body','auth','path','query'])
def test_other_runtime_material_drift_is_rejected_after_patch(env,mutation):
    adapter,provider,_=env
    normalized_provider(provider)
    request=provider.request
    def altered(method,path,payload):
        request(method,path,payload)
        api=provider.current['conversation_config']['agent']['prompt']['tools'][-1]['api_schema']
        if mutation=='header': api['request_headers']['Authorization']='Bearer wrong'
        elif mutation=='url': api['url']='https://foreign.invalid/tool'
        elif mutation=='body': api['request_body_schema']['required']=[]
        elif mutation=='auth': api['auth_connection']={'auth_connection_id':'foreign'}
        elif mutation=='path': api['path_params_schema']={'foreign':{'type':'string'}}
        else: api['query_params_schema']={'properties':{'foreign':{'type':'string'}},'required':['foreign']}
        return copy.deepcopy(provider.current)
    provider.request=altered
    with pytest.raises(SimulationError,match='unknown'):
        subject.prepare_owned_case_agent(adapter,'C35',descriptor(adapter),provider)
    assert adapter.state['blocked'] is True


def test_active_property_added_after_patch_prevents_restore_overwrite(env):
    adapter,provider,_=env
    normalized_provider(provider)
    subject.prepare_owned_case_agent(adapter,'C35',descriptor(adapter),provider)
    tool=provider.current['conversation_config']['agent']['prompt']['tools'][-1]
    tool['api_schema']['request_body_schema']['properties']['phone']['constant_value']='foreign'
    with pytest.raises(SimulationError,match='changed'):
        subject.restore_owned_case_agent(adapter,provider)
    assert len(provider.writes)==1


def test_full_existing_schema_is_preserved_while_old_routing_and_auth_are_removed(env):
    adapter,provider,_original=env
    api=provider.current['conversation_config']['agent']['prompt']['tools'][1]['api_schema']
    api.update(content_type='application/json',auth_connection={'auth_connection_id':'old'},
        path_params_schema={'old':{'type':'string'}},
        query_params_schema={'properties':{'old':{'type':'string'}},'required':['old']})
    subject.prepare_owned_case_agent(adapter,'C35',descriptor(adapter),provider)
    current=provider.current['conversation_config']['agent']['prompt']['tools'][-1]['api_schema']
    assert current['content_type']=='application/json'
    assert 'auth_connection' not in current
    assert current['path_params_schema']=={} and current['query_params_schema']=={'properties':{},'required':[]}
    subject.restore_owned_case_agent(adapter,provider)
    restored=provider.current['conversation_config']['agent']['prompt']['tools'][1]['api_schema']
    assert restored==api
