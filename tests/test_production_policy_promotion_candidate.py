"""Offline regression gate for the local FR061/066 production prompt candidate."""

from pathlib import Path

import pytest

from live_simulations.agent_policy import _GROUPED_POLICY, _LINKED_START, _POLICY
from serviceBot.services.prompt_service import (
    update_prompt_business_hours,
    update_prompt_lead_time_buffers,
)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "serviceBot/system_prompt.txt"
NATIVE = (7, 18, [0, 1, 2, 3, 4], "America/New_York", 4, 2)


def transform(prompt, settings=NATIVE):
    start, end, days, timezone, appointment_buffer, callback_buffer = settings
    return update_prompt_business_hours(
        update_prompt_lead_time_buffers(prompt, appointment_buffer, callback_buffer),
        start, end, days, timezone,
    )


def assert_policies(prompt):
    for policy in (_POLICY, _GROUPED_POLICY):
        assert prompt.count(policy) == 1
        assert prompt.count(policy.splitlines()[0]) == 1
        assert prompt.count(policy.splitlines()[-1]) == 1
    assert prompt.index(_POLICY) < prompt.index(_GROUPED_POLICY)
    assert _LINKED_START not in prompt


def test_candidate_contains_exact_canonical_and_revised_policies_once():
    assert_policies(PROMPT_PATH.read_text(encoding="utf-8"))


def test_candidate_is_native_settings_fixed_point():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert transform(prompt) == prompt
    assert "4-Hour Minimum Planning Horizon Restriction" in prompt
    assert "advisor callbacks require at least 2 hours advance notice" in prompt
    assert "Monday–Friday, 7:00 AM - 6:00 PM ET" in prompt.replace(" – ", " - ")


def test_candidate_preserves_recording_disclosure_and_callback_lead_time():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert "Please note that this conversation will be recorded." in prompt
    assert "Callbacks require at least 2 hours advance notice during business hours" in prompt
    assert "ensure it meets the configured callback lead time before booking" in prompt


@pytest.mark.parametrize("settings", [NATIVE, (9, 19, [1, 2, 3, 4, 5], "America/Chicago", 6, 3)])
def test_settings_preserve_quote_link_and_service_free_callback_rules(settings):
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    updated = transform(prompt, settings)
    assert_policies(updated)
    assert transform(updated, settings) == updated
    assert transform(updated, NATIVE) == prompt
    # The existing quote, consent, callback and notification rules survive the
    # formatter's replacement of the preceding closing-boundary section.
    for instruction in (
        "Quote both estimated rate (cost) and the appointment window clearly",
        "Ask for their explicit confirmation to proceed at those rates and time window.",
        'Only call `check_availability` with `booking_type="callback"`',
        "**Uncataloged / Custom Issues & Dual-Intake:**",
        "**Notification receipt accuracy:**",
        "**Mandatory Existing Request/Booking Check:**",
    ):
        assert instruction in updated
    assert f"{settings[4]}-Hour Minimum Planning Horizon Restriction" in updated
    assert f"advisor callbacks require at least {settings[5]} hours advance notice" in updated
    assert f"Callbacks require at least {settings[5]} hours advance notice during business hours" in updated
    assert "ensure it meets the configured callback lead time before booking" in updated
    if settings != NATIVE:
        assert "Tuesday–Saturday, 9:00 AM - 7:00 PM CT" in updated.replace(" – ", " - ")
        assert "90-minute (1.5-hour) service: Latest possible start is 5:30 PM" in updated
