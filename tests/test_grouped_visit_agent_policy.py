"""Versioned instructions for approved grouped visits and selected service removal."""
from copy import deepcopy

import pytest

from live_simulations import agent_policy as policy
from live_simulations.core import SimulationError


def source():
    return {'conversation_config': {'agent': {'first_message': 'AI and recording disclosure',
            'prompt': {'prompt': 'Protected safety rules\n\n' + policy._POLICY + '\n\n' + policy._LINKED_POLICY,
                       'tools': [{'name': 'cancel_appointment', 'type': 'webhook'}]}}},
            'platform_settings': {'workspace_overrides': {'webhooks': {'post_call_webhook_id': 'owned-hook'}}}}


def test_grouped_revision_changes_only_prompt_and_retains_historical_policy():
    original = source(); before = deepcopy(original)
    revised = policy.apply_grouped_visit_policy(original)
    assert original == before
    assert revised['conversation_config']['agent']['prompt']['prompt'] != original['conversation_config']['agent']['prompt']['prompt']
    revised['conversation_config']['agent']['prompt']['prompt'] = original['conversation_config']['agent']['prompt']['prompt']
    assert revised == original
    assert policy._LINKED_POLICY.endswith('[End owned simulation linked visit policy]')
    assert policy.LINKED_VISIT_POLICY_VERSION == 'linked-visit-anchor-v1'


def test_grouped_revision_is_idempotent_and_preserves_quote_and_disclosure():
    revised = policy.apply_grouped_visit_policy(source())
    text = revised['conversation_config']['agent']['prompt']['prompt']
    assert policy.apply_grouped_visit_policy(revised) == revised
    assert text.count(policy._POLICY) == 1
    assert policy._LINKED_START not in text
    assert policy.GROUPED_VISIT_POLICY_VERSION != policy.LINKED_VISIT_POLICY_VERSION
    assert text.startswith('Protected safety rules\n\n')
    assert revised['conversation_config']['agent']['first_message'] == 'AI and recording disclosure'


def test_grouped_removal_keeps_start_shortens_end_and_preserves_companions():
    text = policy.apply_grouped_visit_policy(source())['conversation_config']['agent']['prompt']['prompt']
    for required in ('service_components', 'service_name', 'cancel_appointment',
                     'same appointment start', 'shorten its end', 'snapshotted duration',
                     'other technicians', 'explicit consent', 'exact canonical',
                     'entire linked visit', 'relative appointment offsets', 'one appointment and calendar entry per technician'):
        assert required in text
    assert 'wants only one component, clarify the server' not in text
    assert 'visit remains contiguous' not in text
    assert 'exactly one reschedule_appointment' in text
    assert 'Do not create replacement bookings' in text


def test_omitted_service_name_requires_entire_linked_visit_or_unlinked_scope():
    text = policy.apply_grouped_visit_policy(source())['conversation_config']['agent']['prompt']['prompt']
    assert 'whole visit\nor complete appointment cancellation' not in text
    assert 'entire linked visit' in text
    assert 'unlinked appointment' in text
    assert 'A selected technician appointment alone does not authorize whole-group cancellation' in text


@pytest.mark.parametrize('defect', ['missing', 'not_text', 'empty', 'missing_quote', 'duplicate', 'edited', 'edited_current'])
def test_grouped_revision_rejects_unproven_policy_sources(defect):
    value = source()
    prompt = value['conversation_config']['agent']['prompt']
    if defect == 'missing': value = {}
    elif defect == 'not_text': prompt['prompt'] = {}
    elif defect == 'empty': prompt['prompt'] = ''
    elif defect == 'missing_quote': prompt['prompt'] = policy._LINKED_POLICY
    elif defect == 'duplicate': prompt['prompt'] += '\n\n' + policy._LINKED_POLICY
    elif defect == 'edited': prompt['prompt'] = prompt['prompt'].replace('Never infer a group', 'Maybe infer a group')
    else:
        value = policy.apply_grouped_visit_policy(value)
        value['conversation_config']['agent']['prompt']['prompt'] += '\n' + policy._GROUPED_START
    with pytest.raises(SimulationError):
        policy.apply_grouped_visit_policy(value)
