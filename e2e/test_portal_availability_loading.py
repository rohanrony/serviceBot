"""Reassignment opens immediately; verified availability precedes any save."""
import pytest
from playwright.sync_api import expect

from e2e.test_selective_service_boundaries import (
    grouped_visit as grouped_visit,  # noqa: PLC0414
)


def setup(page, live_server):
    held = []
    page.route('**/service-requests/*/available-agents', lambda route: held.append(route))
    page.goto(live_server + '/portal/')
    expect(page.locator('.agent-select-badge').first).to_be_visible()
    return held


def finish(route, status=200):
    route.fulfill(status=status, json={'agents': [
        {'id': 1, 'name': 'Tech One', 'is_available': False, 'reason': 'Calendar state unavailable'},
        {'id': 2, 'name': 'Tech Two', 'is_available': True},
    ]})


def test_one_click_opens_reassignment_dialog_before_calendar_response(page, live_server, grouped_visit):
    held = setup(page, live_server)
    assert not held
    trigger = page.locator(f'.agent-select-badge[data-id="{grouped_visit[0]}"]')
    with page.expect_request('**/available-agents'):
        trigger.click()
    dialog = page.get_by_role('dialog', name='Reassign Service Appointment')
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role('status')).to_have_text('Checking live availability…')
    expect(page.locator('#reassign-agent-select')).to_be_disabled()
    expect(page.locator('#reassign-submit-btn')).to_be_disabled()
    expect(page.locator('#reassign-escalation-badge')).not_to_be_visible()
    assert len(held) == 1
    finish(held[0])
    expect(page.locator('#reassign-agent-select option[value="2"]')).to_be_enabled()
    expect(page.locator('#reassign-agent-select')).to_be_enabled()
    expect(page.locator('#reassign-submit-btn')).to_be_enabled()
    expect(page.locator('#reassign-availability-retry')).not_to_be_visible()
