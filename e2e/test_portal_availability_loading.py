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


@pytest.mark.parametrize('empty', [False, True])
def test_failed_or_empty_lookup_has_retry_and_cannot_submit(page, live_server, grouped_visit, empty):
    held = setup(page, live_server)
    target = grouped_visit[0]
    with page.expect_request('**/available-agents'):
        page.locator(f'.agent-select-badge[data-id="{target}"]').click()
    held[0].fulfill(status=200 if empty else 503, json={'agents': []})
    status = page.locator('#reassign-availability-status')
    expect(status).to_have_text('No available replacement agents for this time.' if empty else 'Could not verify agent availability. Please retry.')
    expect(page.locator('#reassign-submit-btn')).to_be_disabled()
    with page.expect_request('**/available-agents'):
        page.locator('#reassign-availability-retry').click()
    expect(status).to_have_text('Checking live availability…')
    assert len(held) == 2
    finish(held[1])
    expect(page.locator('#reassign-agent-select option[value="2"]')).to_be_enabled()


def test_unknown_calendar_is_visible_as_unavailable_and_cannot_be_selected(page, live_server, grouped_visit):
    held = setup(page, live_server)
    with page.expect_request('**/available-agents'):
        page.locator(f'.agent-select-badge[data-id="{grouped_visit[1]}"]').click()
    finish(held[0])
    option = page.locator('#reassign-agent-select option[value="1"]')
    expect(option).to_be_disabled()
    expect(option).to_have_text('Tech One — Unavailable (Calendar state unavailable)')
    expect(page.locator('#reassign-submit-btn')).to_be_disabled()
    expect(page.locator('#reassign-availability-status')).to_have_text('No available replacement agents for this time.')


def test_keyboard_close_during_loading_does_not_reopen_and_can_retry(page, live_server, grouped_visit):
    held = setup(page, live_server)
    target = grouped_visit[0]
    trigger = page.locator(f'.agent-select-badge[data-id="{target}"]')
    trigger.focus()
    with page.expect_request('**/available-agents'):
        trigger.press('Enter')
    expect(page.get_by_role('dialog')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#reassign-modal')).not_to_be_visible()
    expect(trigger).to_be_focused()
    finish(held[0])
    with page.expect_request('**/available-agents'):
        trigger.click()
    assert len(held) == 2
    finish(held[1])
    expect(page.locator('#reassign-agent-select option[value="2"]')).to_be_enabled()


def test_closed_rows_do_not_open_or_fetch(page, api, live_server, grouped_visit):
    rows = api.get('/api/v1/portal/service-requests').json()
    for row in rows:
        row['status'] = 'completed'
    page.route('**/api/v1/portal/service-requests', lambda route: route.fulfill(json=rows))
    held = setup(page, live_server)
    expect(page.locator('.agent-select-badge:not([disabled])')).to_have_count(0)
    page.locator('.agent-select-badge').first.dispatch_event('click')
    expect(page.locator('#reassign-modal')).not_to_be_visible()
    assert not held


def test_modal_lookups_share_serial_queue_and_discard_stale_results(page, api, live_server, grouped_visit):
    held = setup(page, live_server)
    rows = {row['id']: row for row in api.get('/api/v1/portal/service-requests').json()}
    first, second = grouped_visit
    with page.expect_request('**/available-agents'):
        page.locator(f'.agent-select-badge[data-id="{first}"]').click()
    page.evaluate('(row) => { window.openReassignModal(row); }', rows[second])
    assert len(held) == 1
    with page.expect_request(f'**/{second}/available-agents'):
        finish(held[0])
    expect(page.locator('#reassign-availability-status')).to_have_text('Checking live availability…')
    assert len(held) == 2
    finish(held[1])
    expect(page.locator('#reassign-agent-select option[value="1"]')).to_be_disabled()
    expect(page.locator('#reassign-sr-id')).to_have_value(str(second))
