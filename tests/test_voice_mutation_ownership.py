"""Voice mutation selection must finish ownership checks before domain effects."""
import asyncio
from unittest.mock import Mock

import pytest

from serviceBot.api import telephony


@pytest.fixture(scope='session', autouse=True)
def setup_and_cleanup_test_db():
    yield


@pytest.mark.parametrize('tool', ['cancel_appointment', 'reschedule_appointment', 'consolidate_appointment_service'])
@pytest.mark.parametrize('target', [99, '99', 'garbage', '', 0, True, 1.2, None, '1,2'])
def test_explicit_foreign_or_invalid_target_has_no_effect(monkeypatch, tool, target):
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 1}])
    effects = {name: Mock(return_value={'success': True}) for name in
               ['cancel_appointment', 'reschedule_appointment', 'consolidate_appointment_service', 'verify_contiguous_slot_capacity']}
    for name, effect in effects.items():
        monkeypatch.setattr(telephony, name, effect)
    monkeypatch.setattr(telephony, 'get_db_connection', Mock(side_effect=AssertionError('must not read target before ownership')))
    result = asyncio.run(telephony.voice_tools({'name': tool, 'arguments': {
        'phone': '+14242704893', 'appointment_id': target,
        'new_appointment_datetime': '2026-11-20T10:00:00', 'additional_duration_minutes': 30,
    }}))['result']
    assert result['success'] is False
    assert result.get('error_code') == 'APPOINTMENT_OWNERSHIP_REQUIRED'
    for effect in effects.values():
        effect.assert_not_called()


@pytest.mark.parametrize('tool', ['cancel_appointment', 'reschedule_appointment'])
@pytest.mark.parametrize('target', [1, '1'])
def test_owned_target_and_caller_fallback_reach_domain(monkeypatch, tool, target):
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 1}])
    effect = Mock(return_value={'success': True})
    monkeypatch.setattr(telephony, tool, effect)
    result = asyncio.run(telephony.voice_tools({'name': tool, 'arguments': {
        'caller_phone': '+1 (424) 270-4893', 'appointment_id': target,
        'new_appointment_datetime': '2026-11-20T10:00:00',
    }}))['result']
    assert result['success'] is True
    assert effect.call_args.kwargs['appointment_id'] == 1


@pytest.mark.parametrize('source', [[99], ['bad'], [], [True], '1,99'])
def test_consolidation_checks_every_explicit_source_before_capacity(monkeypatch, source):
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 1}, {'id': 2}])
    capacity = Mock()
    monkeypatch.setattr(telephony, 'verify_contiguous_slot_capacity', capacity)
    monkeypatch.setattr(telephony, 'get_db_connection', Mock(side_effect=AssertionError('unowned source read')))
    result = asyncio.run(telephony.voice_tools({'name': 'consolidate_appointment_service', 'arguments': {
        'phone': '+14242704893', 'appointment_id': 1, 'source_appointment_ids': source,
    }}))['result']
    assert result.get('error_code') == 'APPOINTMENT_OWNERSHIP_REQUIRED'
    capacity.assert_not_called()


def test_omitted_target_rejects_ambiguous_owned_bookings(monkeypatch):
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 1}, {'id': 2}])
    effect = Mock()
    monkeypatch.setattr(telephony, 'cancel_appointment', effect)
    result = asyncio.run(telephony.voice_tools({'name': 'cancel_appointment', 'arguments': {'phone': '+14242704893'}}))['result']
    assert result.get('error_code') == 'APPOINTMENT_OWNERSHIP_REQUIRED'
    effect.assert_not_called()


@pytest.mark.parametrize('tool', ['cancel_appointment', 'reschedule_appointment', 'consolidate_appointment_service'])
def test_no_complete_phone_match_never_uses_suffix_lookup(monkeypatch, tool):
    lookup = Mock(return_value=[])
    monkeypatch.setattr(telephony, 'get_customer_appointments', lookup)
    database = Mock(side_effect=AssertionError('suffix lookup forbidden'))
    monkeypatch.setattr(telephony, 'get_db_connection', database)
    result = asyncio.run(telephony.voice_tools({'name': tool, 'arguments': {
        'phone': '+16660100002', 'appointment_id': '99',
    }}))['result']
    assert result.get('error_code') == 'APPOINTMENT_OWNERSHIP_REQUIRED'
    lookup.assert_called_once_with('6660100002')
    database.assert_not_called()


@pytest.mark.parametrize('alias', ['source_appointment_ids', 'source_appointment_id', 'cancelled_appointment_ids'])
def test_owned_source_ids_are_normalized_and_other_aliases_cannot_hide_foreign_ids(monkeypatch, alias):
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 1}, {'id': 2}])
    args = {'phone': '+14242704893', 'appointment_id': '1', alias: '2'}
    resolved = telephony._owned_mutation_arguments(args)
    assert resolved[alias] == [2]
    args[alias] = '99'
    with pytest.raises(ValueError, match='Every source'):
        telephony._owned_mutation_arguments(args)


@pytest.mark.parametrize('tool', ['cancel_appointment', 'reschedule_appointment', 'consolidate_appointment_service'])
def test_lookup_outage_returns_safe_unverified_envelope_without_effects(monkeypatch, tool):
    monkeypatch.setattr(telephony, 'get_customer_appointments', Mock(side_effect=RuntimeError('private database password')))
    effects = {name: Mock() for name in ('cancel_appointment', 'reschedule_appointment',
                                        'consolidate_appointment_service', 'verify_contiguous_slot_capacity')}
    for name, effect in effects.items():
        monkeypatch.setattr(telephony, name, effect)
    response = asyncio.run(telephony.voice_tools({'name': tool, 'arguments': {
        'phone': '4242704893', 'appointment_id': 1,
    }}))
    assert response['result']['success'] is False
    assert response['result']['error_code'] == 'APPOINTMENT_OWNERSHIP_UNVERIFIED'
    assert 'private database password' not in str(response)
    for effect in effects.values():
        effect.assert_not_called()


@pytest.mark.parametrize('invalid_alias', ['source_appointment_ids', 'source_appointment_id', 'cancelled_appointment_ids'])
def test_multiple_source_aliases_cannot_hide_a_foreign_id(monkeypatch, invalid_alias):
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 1}, {'id': 2}])
    effects = {name: Mock() for name in ('consolidate_appointment_service', 'verify_contiguous_slot_capacity')}
    for name, effect in effects.items():
        monkeypatch.setattr(telephony, name, effect)
    arguments = {'phone': '4242704893', 'appointment_id': '1',
                 'source_appointment_ids': ['2'], 'source_appointment_id': '2',
                 'cancelled_appointment_ids': ['2']}
    arguments[invalid_alias] = '99'
    response = asyncio.run(telephony.voice_tools({'name': 'consolidate_appointment_service', 'arguments': arguments}))
    assert response['result']['error_code'] == 'APPOINTMENT_OWNERSHIP_REQUIRED'
    for effect in effects.values():
        effect.assert_not_called()


def test_complete_caller_phone_fallback_is_still_owned_and_never_suffix_based(monkeypatch):
    lookup = Mock(side_effect=lambda phone: [{'id': 2}] if phone == '4242704893' else [])
    monkeypatch.setattr(telephony, 'get_customer_appointments', lookup)
    resolved = telephony._owned_mutation_arguments({
        'phone': '4442704893', 'caller_phone': '+1 (424) 270-4893', 'appointment_id': '2',
    })
    assert resolved['phone'] == '4242704893'
    assert resolved['appointment_id'] == 2
    assert [call.args[0] for call in lookup.call_args_list] == ['4442704893', '4242704893']
    with pytest.raises(ValueError, match='does not belong'):
        telephony._owned_mutation_arguments({
            'phone': '4442704893', 'caller_phone': '4242704893', 'appointment_id': 99,
        })


@pytest.mark.parametrize('alias', ['source_appointment_ids', 'source_appointment_id', 'cancelled_appointment_ids'])
def test_legacy_comma_sources_validate_each_full_owned_id(monkeypatch, alias):
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda phone: [{'id': 1}, {'id': 2}, {'id': 3}])
    args = {'phone': '4242704893', 'appointment_id': '1', alias: '2, 3'}
    assert telephony._owned_mutation_arguments(args)[alias] == [2, 3]
    args[alias] = '2, 99'
    with pytest.raises(ValueError, match='Every source'):
        telephony._owned_mutation_arguments(args)
    args[alias] = '2,,3'
    with pytest.raises(ValueError, match='positive integers'):
        telephony._owned_mutation_arguments(args)
