"""Pure proposals preserve native authentication and unrelated agent tools."""
from copy import deepcopy

import pytest

from live_simulations import tool_policy
from live_simulations.core import SimulationError

URL = 'https://deployed.example.test'


def source():
    return {'type': 'webhook', 'name': 'cancel_appointment', 'description': 'Original scope',
            'response_timeout_secs': 35, 'api_schema': {'url': URL + '/api/v1/voice/tools?name=cancel_appointment',
            'method': 'POST', 'request_headers': {'X-Native': {'secret_id': 'native-reference'}},
            'auth_connection': {'id': 'native-auth'}, 'request_body_schema': {'type': 'object',
            'required': ['phone'], 'properties': {'phone': {'type': 'string'}, 'appointment_id': {'type': 'integer'}}}}}


def template():
    value = source(); value['description'] = 'Selective exact service after consent; omission is whole visit.'
    value['api_schema']['request_body_schema']['properties']['service_name'] = {'type': 'string', 'description': 'Exact canonical component'}
    return value


def test_tool_candidate_changes_only_reviewed_description_and_optional_property():
    original = source(); before = deepcopy(original)
    revised = tool_policy.selective_cancel_tool(original, template(), URL)
    assert original == before
    assert revised['api_schema']['request_body_schema']['properties']['service_name'] == template()['api_schema']['request_body_schema']['properties']['service_name']
    assert tool_policy.selective_cancel_tool(revised, template(), URL) == revised
    revised['description'] = original['description']
    del revised['api_schema']['request_body_schema']['properties']['service_name']
    assert revised == original


@pytest.mark.parametrize('defect', ['wrong_name','foreign_url','unsafe_url','wrong_route','method','required_field','changed_existing','missing_phone'])
def test_unknown_tool_scope_is_rejected_without_mutation(defect):
    original = source(); desired = template()
    if defect == 'wrong_name': original['name'] = 'book_appointment'
    elif defect == 'foreign_url': original['api_schema']['url'] = 'https://other.example.test/api/v1/voice/tools'
    elif defect == 'unsafe_url': original['api_schema']['url'] = URL.replace('https://','https://secret@') + '/api/v1/voice/tools'
    elif defect == 'wrong_route': original['api_schema']['url'] = URL + '/api/v1/portal/config'
    elif defect == 'method': original['api_schema']['method'] = 'GET'
    elif defect == 'required_field': desired['api_schema']['request_body_schema']['required'].append('service_name')
    elif defect == 'changed_existing': original['api_schema']['request_body_schema']['properties']['service_name'] = {'type':'integer'}
    else: del original['api_schema']['request_body_schema']['properties']['phone']
    before = deepcopy(original)
    with pytest.raises(SimulationError): tool_policy.selective_cancel_tool(original, desired, URL)
    assert original == before


def test_agent_reference_patch_is_minimal_and_does_not_inline_or_clear_native_tools():
    agent = {'conversation_config': {'agent': {'prompt': {'prompt':'unchanged',
             'tools':[{'name':'cancel_appointment'}], 'tool_ids':['tool-a','tool-cancel','tool-z']}}},
             'platform_settings': {'unchanged':True}}
    before = deepcopy(agent)
    assert tool_policy.cancel_reference_patch(agent, 'tool-cancel', 'tool-owned') == {
        'conversation_config': {'agent': {'prompt': {'tool_ids':['tool-a','tool-owned','tool-z']}}}}
    assert agent == before


@pytest.mark.parametrize('ids,new_id', [(['tool-cancel','tool-cancel'],'owned'), (['other'],'owned'),
                                     (['tool-cancel','owned'],'owned'), (['tool-cancel'],''),
                                     (['tool-cancel'],'tool-cancel'), ('tool-cancel','owned')])
def test_ambiguous_reference_replacement_is_rejected(ids,new_id):
    agent = {'conversation_config': {'agent': {'prompt': {'tool_ids':ids}}}}
    with pytest.raises(SimulationError): tool_policy.cancel_reference_patch(agent,'tool-cancel',new_id)
