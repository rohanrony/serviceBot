"""Owned-clone policy revisions preserve every non-prompt setting."""
from copy import deepcopy

import pytest

from live_simulations.agent_policy import SERVICE_POLICY_VERSION, apply_service_policy
from live_simulations.core import SimulationError


def override():
    return {'conversation_config': {'agent': {'first_message': 'Welcome', 'prompt': {
        'prompt': 'Existing cancellation, callback and rescheduling instructions.',
        'tools': [{'name': 'create_service_request', 'api_schema': {
            'url': 'https://app.example.test/api/v1/voice/tools',
            'request_body_schema': {'properties': {'issue_description': {'type': 'string'}}}}}],
        'llm': 'retained', 'max_tokens': 256}}, 'tts': {'voice_id': 'retained'}},
        'platform_settings': {'evaluation': {'criteria': ['retained']}}}


def test_revision_is_idempotent_and_only_changes_prompt():
    original = override()
    before = deepcopy(original)
    revised = apply_service_policy(original)
    assert original == before
    assert SERVICE_POLICY_VERSION == 'canonical-prequote-v1'
    assert revised['conversation_config']['agent']['prompt']['prompt'].startswith(
        before['conversation_config']['agent']['prompt']['prompt'])
    restored = deepcopy(revised)
    restored['conversation_config']['agent']['prompt']['prompt'] = before['conversation_config']['agent']['prompt']['prompt']
    assert restored == before
    assert apply_service_policy(revised) == revised
    revised['conversation_config']['agent']['prompt']['tools'][0]['name'] = 'changed'
    assert original == before


def test_legacy_tool_arguments_and_prebooking_order_are_explicit():
    text = apply_service_policy(override())['conversation_config']['agent']['prompt']['prompt']
    for required in (
        'get_service_fields(service_name=', 'check_availability(service_type=',
        'book_appointment(service_type=', 'create_service_request(issue_description=',
        'exact full canonical', 'Never strip', 'price', 'duration',
        'BEFORE', 'consent', 'Do not invent', 'callback', 'cancel', 'reschedule',
        'Do not add service_type or services', 'placeholder Repair',
    ):
        assert required in text
    assert ' and ' in text


@pytest.mark.parametrize('bad', [{}, {'conversation_config': {}},
    {'conversation_config': {'agent': {'prompt': {'prompt': None}}}}])
def test_missing_prompt_is_rejected_without_replacing_configuration(bad):
    before = deepcopy(bad)
    with pytest.raises(SimulationError):
        apply_service_policy(bad)
    assert bad == before
