import httpx
import pytest

from live_simulations.core import SimulationError
from live_simulations.provider import ElevenLabs


def test_create_uses_modern_schema_and_run_uses_exact_item_shape():
    seen = []
    def transport(request):
        import json
        seen.append((request.method, request.url.path, json.loads(request.content or b'{}')))
        return httpx.Response(200, json={'id': 'owned-id'})
    p = ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(transport)))
    case = {'id': 'C01', 'scenario': 'Book fixture service', 'max_turns': 8,
            'success_conditions': ['Correct booking']}
    assert p.create(case, 'campaign', {'caller_phone': '2125551234'}, 'simulation') == 'owned-id'
    assert seen[0][1] == '/v1/convai/agent-testing/create'
    assert seen[0][2]['type'] == 'simulation'
    assert seen[0][2]['tool_mock_config']['mocking_strategy'] == 'none'
    assert seen[0][2]['simulation_environment'] == 'simulation'
    p.run('test-agent', 'owned-id', {'conversation_config': {}, 'platform_settings': {}})
    assert seen[1][2]['tests'] == [{'test_id': 'owned-id'}]
    assert seen[1][2]['repeat_count'] == 1


def test_ambiguous_post_timeout_is_never_retried():
    calls = []
    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout('ambiguous', request=request)
    p = ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(transport)))
    with pytest.raises(SimulationError, match='ambiguous'):
        p.run('agent', 'test', {})
    assert len(calls) == 1


def test_verified_owned_agent_runs_without_inline_tool_override():
    import json
    seen = []
    def transport(request):
        seen.append(request)
        return httpx.Response(200, json={'id': 'invocation'})
    provider = ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(transport)))
    provider.run('owned-clone', 'owned-test')
    assert seen[0].url.path == '/v1/convai/agents/owned-clone/run-tests'
    assert json.loads(seen[0].content) == {'tests': [{'test_id': 'owned-test'}], 'repeat_count': 1}
    override = {'conversation_config': {'agent': {'prompt': {'tool_ids': ['explicit']}}}}
    provider.run('other-agent', 'other-test', override)
    assert json.loads(seen[1].content)['agent_config_override'] == override


def test_per_run_metering_is_not_double_counted():
    result = {'test_runs': [{'status': 'passed', 'credits_used': 3}, {'status': 'passed', 'credits_used': 4}]}
    assert ElevenLabs.credits(result) == 7
    assert ElevenLabs.credits({'test_runs': [{'status': 'passed', 'credits_used': None}]}) is None


def test_override_redirects_inline_tools_without_mutating_original():
    original = {'conversation_config': {'agent': {'prompt': {'tools': [
        {'type': 'webhook', 'name': 'create_service_request', 'api_schema': {'url': 'https://original.invalid/tools', 'request_headers': {}}}
    ]}}}, 'platform_settings': {}}
    result = ElevenLabs.override(original, 'https://tunnel.example', 'token', 'isolated-webhook')
    tool = result['conversation_config']['agent']['prompt']['tools'][0]
    assert tool['api_schema']['url'] == 'https://tunnel.example/api/v1/voice/tools?name=create_service_request'
    assert tool['api_schema']['request_headers']['X-Live-Simulation-Token'] == 'token'
    assert original['conversation_config']['agent']['prompt']['tools'][0]['api_schema']['url'].startswith('https://original')


def test_unresolved_workflow_or_shared_tools_are_blocked():
    for prompt, workflow in [({'tool_ids': ['shared']}, {}), ({'tools': []}, {'nodes': {'node': {}}})]:
        with pytest.raises(SimulationError):
            ElevenLabs.override({'conversation_config': {'agent': {'prompt': prompt}},
                                 'platform_settings': {}, 'workflow': workflow}, 'https://tunnel.example', 'token')


def test_campaign_agent_is_new_owned_identity_and_delete_uses_recorded_id():
    seen = []
    def transport(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={'agent_id': 'owned-campaign-agent'})
    provider = ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(transport)))
    assert provider.create_agent({'conversation_config': {}, 'platform_settings': {}}, 'a' * 32) == 'owned-campaign-agent'
    provider.delete_agent('owned-campaign-agent')
    assert seen == [('POST', '/v1/convai/agents/create'), ('DELETE', '/v1/convai/agents/owned-campaign-agent')]


def test_owned_deletion_is_retryable_when_provider_already_removed_resource():
    provider = ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert provider.delete_test('owned-test') == {}
    assert provider.agent('owned-agent', missing_ok=True) is None


def test_platform_override_preserves_settings_and_pins_test_callback():
    source = {'conversation_config': {'agent': {'prompt': {'tools': [
        {'type': 'system', 'name': 'end_call'}]}}},
        'platform_settings': {'privacy': {'record_voice': False},
                              'workspace_overrides': {'webhooks': {'post_call_webhook_id': 'production'}}}}
    result = ElevenLabs.override(source, 'https://tunnel.example', 'token', 'isolated-webhook')
    assert result['platform_settings']['privacy'] == {'record_voice': False}
    assert result['platform_settings']['workspace_overrides']['webhooks'] == {
        'post_call_webhook_id': 'isolated-webhook', 'events': ['transcript'],
        'transcript_format': 'json', 'exclude_transcript': False}
    assert source['platform_settings']['workspace_overrides']['webhooks']['post_call_webhook_id'] == 'production'
    with pytest.raises(SimulationError, match='webhook'):
        ElevenLabs.override(source, 'https://tunnel.example', 'token')


def test_callback_preflight_rejects_inheritance_wrong_destination_and_initiation():
    def provider(webhook, settings=None):
        return ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={'webhooks': [webhook]} if r.url.path == '/v1/workspace/webhooks' else (settings or {})))))
    correct = {'webhook_id': 'isolated', 'webhook_url': 'https://tunnel.example/api/v1/telephony/webhook',
               'auth_type': 'hmac', 'is_disabled': False, 'is_auto_disabled': False}
    provider(correct).verify_webhook('isolated', 'https://tunnel.example', {})
    for change in ({'webhook_url': 'https://production.example/webhook'}, {'is_disabled': True}, {'auth_type': 'none'}):
        with pytest.raises(SimulationError):
            provider({**correct, **change}).verify_webhook('isolated', 'https://tunnel.example', {})
    with pytest.raises(SimulationError):
        provider(correct, {'conversation_initiation_client_data_webhook': {'url': 'https://production.example'}}).verify_webhook('isolated', 'https://tunnel.example', {})


def test_standard_reference_resolves_shared_tools_using_only_get_requests():
    import copy
    tool = {'type': 'webhook', 'name': 'book_appointment', 'api_schema': {'url': 'https://standard.example/tools'}}
    agent = {'name': 'Standard service agent', 'conversation_config': {'agent': {'prompt': {'tools': [tool], 'tool_ids': ['shared-1']}}},
             'workflow': {'nodes': {'start': {'type': 'start', 'position': {'x': 0, 'y': 0}, 'edge_order': [], 'parent_subgraph_id': None}}, 'edges': {}, 'subgraphs': {}}}
    original = copy.deepcopy(agent)
    seen = []
    def transport(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={'id': 'shared-1', 'tool_config': tool})
    provider = ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(transport)))
    resolved = provider.resolve_reference(agent)
    override = provider.override(resolved, 'https://test.example', 'token', 'webhook-test')
    assert seen == [('GET', '/v1/convai/tools/shared-1')]
    assert override['conversation_config']['agent']['prompt']['tool_ids'] == []
    assert override['conversation_config']['agent']['prompt']['tools'][0]['api_schema']['url'].startswith('https://test.example/')
    assert agent == original


def test_changed_shared_definition_or_nontrivial_workflow_is_blocked():
    provider = ElevenLabs('synthetic', httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'id': 'shared', 'tool_config': {'name': 'book', 'type': 'webhook', 'api_schema': {'url': 'https://changed.example'}}}))))
    source = {'conversation_config': {'agent': {'prompt': {'tool_ids': ['shared'], 'tools': [
        {'name': 'book', 'type': 'webhook', 'api_schema': {'url': 'https://old.example'}}]}}}}
    with pytest.raises(SimulationError, match='changed'):
        provider.resolve_reference(source)
    for workflow in ({'nodes': {'start': {'type': 'start', 'edge_order': [], 'unexpected_action': {}}}},
                     {'nodes': {'start': {'type': 'start'}, 'agent': {'type': 'agent'}}, 'edges': {}}):
        with pytest.raises(SimulationError, match='workflow'):
            provider.override({'workflow': workflow, 'conversation_config': {'agent': {'prompt': {'tools': [{'type': 'system', 'name': 'end_call'}]}}}},
                              'https://test.example', 'token', 'webhook')


def test_reference_name_does_not_require_renaming_saved_standard_agent():
    from live_simulations.runner import load_reference
    seen = []
    class Provider:
        def agent(self, agent_id): seen.append(('get', agent_id)); return {'name': 'Davidson standard agent'}
        def resolve_reference(self, source): return {**source, 'resolved': True}
    assert load_reference({'agent_id': 'standard'}, Provider())['resolved'] is True
    assert seen == [('get', 'standard')]
