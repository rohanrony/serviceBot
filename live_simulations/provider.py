"""Modern ElevenLabs testing API; writes are never automatically retried."""
from __future__ import annotations

import copy
import time
from decimal import Decimal
from urllib.parse import quote

import httpx

from .core import SimulationError, number


def empty_workflow(workflow):
    if not workflow:
        return True
    if not isinstance(workflow, dict) or set(workflow) - {'nodes', 'edges', 'subgraphs', 'prevent_subagent_loops'}:
        return False
    if workflow.get('edges') or workflow.get('subgraphs'):
        return False
    nodes = workflow.get('nodes', {})
    if not isinstance(nodes, dict) or len(nodes) != 1:
        return False
    node = next(iter(nodes.values()))
    return (isinstance(node, dict) and node.get('type') == 'start'
            and not node.get('edge_order') and not node.get('parent_subgraph_id')
            and not (set(node) - {'type', 'position', 'edge_order', 'parent_subgraph_id'}))


class ElevenLabs:
    def __init__(self, key, client=None):
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.headers = {'xi-api-key': key}

    def request(self, method, path, payload=None, *, missing_ok=False):
        try:
            response = self.client.request(method, 'https://api.elevenlabs.io' + path,
                                           headers=self.headers, json=payload)
            if response.status_code == 404 and (method == 'DELETE' or missing_ok):
                return None if missing_ok else {}
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.TransportError:
            label = 'ambiguous provider write; inspect owned resources before retry' if method != 'GET' else 'provider unavailable'
            raise SimulationError(label) from None
        except (httpx.HTTPStatusError, ValueError):
            raise SimulationError(f'Provider rejected {method} request') from None

    def agent(self, agent_id, *, missing_ok=False):
        return self.request('GET', '/v1/convai/agents/' + quote(agent_id, safe=''), missing_ok=missing_ok)

    def resolve_reference(self, agent):
        """Read shared definitions; no original tool or agent is ever patched."""
        resolved = copy.deepcopy(agent)
        prompt = resolved['conversation_config'].get('agent', {}).get('prompt', {})
        tools = prompt.setdefault('tools', [])
        names = [tool.get('name') for tool in tools]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise SimulationError('Reference tool names must be present and unique')
        for tool_id in prompt.get('tool_ids', []):
            if not isinstance(tool_id, str) or not tool_id:
                raise SimulationError('Invalid shared tool reference')
            response = self.request('GET', '/v1/convai/tools/' + quote(tool_id, safe=''))
            tool = response.get('tool_config')
            if response.get('id') != tool_id or not isinstance(tool, dict) or not tool.get('name'):
                raise SimulationError('Shared tool lookup did not resolve its exact identity')
            matching = next((item for item in tools if item.get('name') == tool['name']), None)
            if matching is not None and matching != tool:
                raise SimulationError('Shared tool changed since reference was read; retry read-only setup')
            if matching is None:
                tools.append(copy.deepcopy(tool))
        prompt['tool_ids'] = []
        return resolved

    def subscription(self):
        return self.request('GET', '/v1/user/subscription')

    def verify_webhook(self, webhook_id, tunnel, agent):
        if not webhook_id:
            raise SimulationError('An explicit dedicated post-call webhook ID is required')
        settings = self.request('GET', '/v1/convai/settings')
        overrides = agent.get('platform_settings', {}).get('workspace_overrides', {})
        if (settings.get('conversation_initiation_client_data_webhook')
                or overrides.get('conversation_initiation_client_data_webhook')):
            raise SimulationError('Configured initiation webhook needs an independently isolated workspace')
        webhooks = self.request('GET', '/v1/workspace/webhooks?include_usages=false').get('webhooks', [])
        matches = [w for w in webhooks if w.get('webhook_id') == webhook_id]
        expected = tunnel.rstrip('/') + '/api/v1/telephony/webhook'
        if (len(matches) != 1 or matches[0].get('webhook_url') != expected
                or matches[0].get('is_disabled') is not False
                or matches[0].get('is_auto_disabled') is not False
                or matches[0].get('auth_type') != 'hmac'):
            raise SimulationError('Dedicated webhook must be enabled, HMAC signed and target this isolated tunnel')

    def create_agent(self, override, run_id):
        result = self.request('POST', '/v1/convai/agents/create', {
            **override, 'name': 'Live simulation ' + run_id, 'tags': ['live_simulation', run_id]})
        if not isinstance(result.get('agent_id'), str) or not result['agent_id']:
            raise SimulationError('ambiguous agent creation: missing owned agent ID')
        return result['agent_id']

    def delete_agent(self, agent_id):
        return self.request('DELETE', '/v1/convai/agents/' + quote(agent_id, safe=''))

    def create(self, case, run_id, variables, environment):
        result = self.request('POST', '/v1/convai/agent-testing/create', {
            'type': 'simulation', 'name': f'live-simulation:{run_id}:{case["id"]}',
            'simulation_scenario': case['scenario'], 'simulation_max_turns': case['max_turns'],
            'success_conditions': case['success_conditions'], 'dynamic_variables': variables,
            'simulation_environment': environment,
            'tool_mock_config': {'mocking_strategy': 'none', 'fallback_strategy': 'call_real_tool',
                                 'mocked_tool_ids': []},
        })
        if not isinstance(result.get('id'), str) or not result['id']:
            raise SimulationError('ambiguous provider create: missing test ID')
        return result['id']

    def run(self, agent_id, test_id, override=None):
        payload = {'tests': [{'test_id': test_id}], 'repeat_count': 1}
        if override is not None:
            payload['agent_config_override'] = override
        return self.request('POST', f'/v1/convai/agents/{quote(agent_id, safe="")}/run-tests', payload)

    def get(self, invocation):
        return self.request('GET', '/v1/convai/test-invocations/' + quote(invocation, safe=''))

    def wait(self, invocation, timeout, observe=lambda: None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.get(invocation)
            runs = result.get('test_runs', [])
            statuses = [r.get('status') for r in runs]
            if not runs or any(s not in ('pending', 'passed', 'failed', 'cancelled') for s in statuses):
                raise SimulationError('Unknown provider run status')
            observe()
            if all(s != 'pending' for s in statuses):
                return result
            time.sleep(1)
        self.cancel(invocation)
        raise SimulationError('Provider timeout; cancellation requested for pending runs')

    def cancel(self, invocation):
        self.request('POST', '/v1/convai/test-invocations/' + quote(invocation, safe='') + '/cancel')

    def delete_test(self, test_id):
        return self.request('DELETE', '/v1/convai/agent-testing/' + quote(test_id, safe=''))

    @staticmethod
    def credits(result):
        runs = result.get('test_runs', [])
        if not runs or any(r.get('credits_used') is None for r in runs):
            return None
        return sum((number(r['credits_used']) for r in runs), Decimal(0))

    @staticmethod
    def override(agent, tunnel, token, webhook_id=None):
        """Inline copied tools avoid mutation of shared tools or any saved agent."""
        if not webhook_id:
            raise SimulationError('An explicit dedicated post-call webhook ID is required')
        config = copy.deepcopy(agent['conversation_config'])
        prompt = config.get('agent', {}).get('prompt', {})
        if not empty_workflow(agent.get('workflow')) or prompt.get('tool_ids'):
            raise SimulationError('Resolve shared tools first; nontrivial workflow routing requires a dedicated adapter')
        tools = prompt.get('tools', [])
        if not tools:
            raise SimulationError('Agent has no inspectable inline tools')
        for tool in tools:
            if tool.get('type') == 'webhook':
                name = tool['name']
                tool['api_schema']['url'] = tunnel.rstrip('/') + '/api/v1/voice/tools?name=' + quote(name, safe='')
                tool['api_schema']['request_headers'] = {
                    'X-Live-Simulation-Token': token, 'X-Caller-ID': '{{caller_phone}}'}
                # Do not resolve an inherited production auth connection/environment.
                tool['api_schema'].pop('auth_connection', None)
            elif tool.get('type') != 'system' or tool.get('name') != 'end_call':
                raise SimulationError('Non-webhook side-effect tool is not allowed in API simulations')
        prompt['tool_ids'] = []
        platform = copy.deepcopy(agent.get('platform_settings', {}))
        platform.setdefault('workspace_overrides', {})['webhooks'] = {
            'post_call_webhook_id': webhook_id, 'events': ['transcript'],
            'transcript_format': 'json', 'exclude_transcript': False}
        return {'conversation_config': config, 'platform_settings': platform}
