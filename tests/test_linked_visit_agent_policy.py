"""Pure candidate policy contracts; no saved agent or provider is changed."""
import hashlib
from copy import deepcopy

import pytest

from live_simulations import agent_policy
from live_simulations.core import SimulationError
from tests.test_deployed_agent_policy import override


def candidate():
    return agent_policy.apply_linked_visit_policy(agent_policy.apply_service_policy(override()))


def test_linked_candidate_changes_only_prompt_and_is_independently_idempotent():
    original = agent_policy.apply_service_policy(override())
    before = deepcopy(original)
    revised = agent_policy.apply_linked_visit_policy(original)
    assert original == before
    assert agent_policy.SERVICE_POLICY_VERSION == 'canonical-prequote-v1'
    assert agent_policy.LINKED_VISIT_POLICY_VERSION != agent_policy.SERVICE_POLICY_VERSION
    assert revised['conversation_config']['agent']['prompt']['prompt'].startswith(
        before['conversation_config']['agent']['prompt']['prompt'] + '\n\n')
    restored = deepcopy(revised)
    restored['conversation_config']['agent']['prompt']['prompt'] = before['conversation_config']['agent']['prompt']['prompt']
    assert restored == before
    assert agent_policy.apply_linked_visit_policy(revised) == revised
    revised['conversation_config']['agent']['prompt']['tools'][0]['name'] = 'mutated copy'
    assert original == before


def test_historical_service_policy_bytes_remain_unchanged():
    text = agent_policy.apply_service_policy(override())['conversation_config']['agent']['prompt']['prompt']
    assert hashlib.sha256(text.encode()).hexdigest() == '2eefb05e083b567adfc9524a890e61974000547c536939941bd8ea3c958cd450'


@pytest.mark.parametrize('required', [
    'get_customer_appointments', 'visit_group_id', 'visit_anchor_id', 'visit_start',
    'visit_member_ids', 'authoritative', 'Never infer', 'earliest', 'once',
    'appointment_id=visit_anchor_id', 'new_appointment_datetime=',
    'requested VISIT start', 'Never parallel', 'Await', 'read back',
    'every member', 'duration', 'contiguous', 'explicit consent',
    'cancel', 'separate', 'unlinked', 'callback', 'clarify',
])
def test_linked_policy_requires_authoritative_membership_and_one_anchor(required):
    original = agent_policy.apply_service_policy(override())['conversation_config']['agent']['prompt']['prompt']
    text = candidate()['conversation_config']['agent']['prompt']['prompt'][len(original):]
    assert required in text


def test_policy_does_not_forge_membership_or_change_legacy_arguments():
    text = candidate()['conversation_config']['agent']['prompt']['prompt']
    assert 'same date' in text and 'adjacent times' in text
    assert 'do not invent membership' in text
    assert 'Do not add visit_group_id or visit_member_ids to mutation arguments' in text
    assert 'Do not create replacement bookings' in text
    assert 'separate or unlinked appointments' in text


@pytest.mark.parametrize('bad', [{}, {'conversation_config': {}},
    {'conversation_config': {'agent': {'prompt': {'prompt': None}}}},
    {'conversation_config': {'agent': {'prompt': {'prompt': '  '}}}},
])
def test_invalid_prompt_rejected_without_mutation(bad):
    before = deepcopy(bad)
    with pytest.raises(SimulationError):
        agent_policy.apply_linked_visit_policy(bad)
    assert bad == before


def test_partial_or_changed_linked_marker_is_rejected():
    revised = candidate()
    revised['conversation_config']['agent']['prompt']['prompt'] += '\nchanged block'
    with pytest.raises(SimulationError):
        agent_policy.apply_linked_visit_policy(revised)
