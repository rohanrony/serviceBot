"""Portal availability is explicit, bounded and never an assignment by itself."""
import json

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
    route.fulfill(status=status, content_type='application/json', body=json.dumps({'agents': [
        {'id': 1, 'name': 'Tech One', 'role': 'Technician', 'is_available': False, 'reason': 'Busy', 'whatsapp_connected': False},
        {'id': 2, 'name': 'Tech Two', 'role': 'Technician', 'is_available': True, 'whatsapp_connected': True},
    ]}))


def test_one_click_opens_loading_then_all_agents_without_another_click(page, live_server, grouped_visit):
    held = setup(page, live_server)
    assignments = []
    page.on('request', lambda request: assignments.append(request.url) if request.url.endswith('/assign-agent') else None)
    trigger = page.locator('.agent-select-badge:not([disabled])').first
    trigger.click()
    menu = page.get_by_role('menu', name='Assign agent')
    expect(menu).to_be_visible()
    expect(menu.get_by_role('status')).to_have_text('Checking availability…')
    page.wait_for_function('() => !!document.querySelector(".agent-select-badge[aria-busy=true]")')
    assert len(held) == 1
    finish(held[0])
    expect(menu.get_by_role('menuitemradio', name='Tech Two - Technician', exact=True)).to_be_visible()
    expect(menu.get_by_role('menuitemradio', name='Tech One', exact=False)).to_be_visible()
    expect(menu.get_by_role('menuitemradio', name='Tech One', exact=False)).to_be_disabled()
    assert not assignments
    page.keyboard.press('Escape')
    expect(menu).not_to_be_visible()
    expect(trigger).to_be_focused()


def test_dismissed_loading_menu_stays_closed_when_results_arrive(page, live_server, grouped_visit):
    held = setup(page, live_server)
    trigger = page.locator('.agent-select-badge:not([disabled])').first
    trigger.click()
    menu = page.get_by_role('menu', name='Assign agent')
    expect(menu.get_by_role('status')).to_have_text('Checking availability…')
    page.locator('#filter-sr-search').click()
    expect(menu).not_to_be_visible()
    finish(held[0])
    expect(trigger).not_to_have_attribute('aria-busy', 'true')
    expect(menu).not_to_be_visible()
    expect(page.locator('#filter-sr-search')).to_be_focused()
    trigger.click()
    expect(menu.get_by_role('menuitemradio', name='Tech Two - Technician', exact=True)).to_be_visible()
    assert len(held) == 1


def test_narrow_menu_shows_full_unavailability_reason_without_horizontal_overflow(page, live_server, grouped_visit):
    page.set_viewport_size({'width': 480, 'height': 800})
    held = setup(page, live_server)
    page.locator('.agent-select-badge:not([disabled])').first.click()
    menu = page.get_by_role('menu', name='Assign agent')
    expect(menu.get_by_role('status')).to_have_text('Checking availability…')
    finish(held[0])
    expect(menu.get_by_role('menuitemradio', name='Tech One', exact=False)).to_be_visible()
    assert menu.evaluate('(node) => node.scrollWidth <= node.clientWidth')
    box = menu.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 480
    assert box['y'] >= 0 and box['y'] + box['height'] <= 800


@pytest.mark.parametrize('empty', [False, True])
def test_failed_or_empty_lookup_shows_retry_without_losing_current_agent(page, live_server, grouped_visit, empty):
    held = setup(page, live_server)
    trigger = page.locator('.agent-select-badge:not([disabled])').first
    row = trigger.locator('xpath=ancestor::tr')
    original = row.locator('.agent-name-line').inner_text()
    trigger.click()
    menu = page.get_by_role('menu', name='Assign agent')
    expect(menu).to_be_visible()
    assert len(held) == 1
    held[0].fulfill(status=200 if empty else 503, json={'agents': []})
    expect(menu.get_by_role('status')).to_have_text(
        'No agents found for this appointment.' if empty else 'Could not load availability. Please retry.'
    )
    expect(row.locator('.agent-name-line')).to_have_text(original)
    menu.get_by_role('menuitem', name='Retry').click()
    expect(menu.get_by_role('status')).to_have_text('Checking availability…')
    assert len(held) == 2
    finish(held[1])
    expect(menu.get_by_role('menuitemradio', name='Tech Two - Technician', exact=True)).to_be_visible()


def test_render_is_readonly_and_requests_are_lazy_deduplicated_serial(page, live_server, grouped_visit):
    held = setup(page, live_server)
    assert held == []
    selects = page.locator('.agent-select-badge:not([disabled])')
    first, second = selects.nth(0), selects.nth(1)
    first.click()
    page.wait_for_timeout(50)
    assert len(held) == 1
    first.click()
    first.click()
    second.click()
    page.wait_for_timeout(50)
    assert len(held) == 1
    finish(held[0])
    page.wait_for_timeout(100)
    assert len(held) == 2
    finish(held[1])
    expect(second.locator('xpath=..').get_by_role('menuitemradio', name='Tech Two - Technician', exact=True)).to_be_visible()


def test_failure_preserves_assignment_retries_only_on_interaction_and_ignores_detached_row(page, live_server, grouped_visit):
    held = setup(page, live_server)
    assignments = []
    page.on('request', lambda request: assignments.append(request.url) if request.url.endswith('/assign-agent') else None)
    assert not held
    select = page.locator('.agent-select-badge:not([disabled])').first
    original = select.locator('xpath=..').locator('.agent-name-line').inner_text()
    select.click()
    page.wait_for_timeout(50)
    finish(held[0], 503)
    page.wait_for_timeout(50)
    expect(select.locator('xpath=..').locator('.agent-name-line')).to_have_text(original)
    assert len(held) == 1
    page.get_by_role('menuitem', name='Retry').click()
    page.wait_for_timeout(50)
    assert len(held) == 2
    page.evaluate("window.detachedAgent = document.querySelector('.agent-select-badge:not([disabled])'); window.detachedAgent.closest('tr').remove()")
    finish(held[1])
    page.wait_for_timeout(50)
    assert len(held) == 2
    assert page.evaluate('window.detachedAgent.closest(".agent-badge-wrapper").querySelector(".agent-name-line").textContent') == original
    assert not assignments


def test_closed_rows_and_rerenders_do_not_fetch_availability(page, api, live_server, grouped_visit):
    rows = api.get('/api/v1/portal/service-requests').json()
    for row in rows:
        row['status'] = 'completed'
    page.route('**/api/v1/portal/service-requests', lambda route: route.fulfill(json=rows))
    held = setup(page, live_server)
    expect(page.locator('.agent-select-badge:not([disabled])')).to_have_count(0)
    page.locator('.agent-select-badge').first.dispatch_event('click')
    page.locator('#sr-page-size').select_option('25')
    page.wait_for_timeout(50)
    assert not held


def test_keyboard_options_preserve_current_unavailable_and_assignment_is_one_explicit_patch(page, live_server, grouped_visit):
    target, _ = grouped_visit
    patches = []
    def assign(route):
        patches.append((route.request.method, route.request.post_data_json))
        route.fulfill(json={'success': True, 'data': {'status': 'pending'}})
    page.route(f'**/service-requests/{target}/assign-agent', assign)
    held = setup(page, live_server)
    select = page.locator(f'.agent-select-badge[data-id="{target}"]')
    select.focus()
    select.press('ArrowDown')
    page.wait_for_timeout(50)
    assert len(held) == 1
    finish(held[0])
    menu = page.get_by_role('menu', name='Assign agent')
    current = menu.locator('[data-agent-id="1"]')
    expect(current).to_be_enabled()
    expect(current).to_have_attribute('data-whatsapp-connected', 'false')
    expect(current).to_contain_text('Unavailable - Busy')
    assert not patches
    expect(current).to_have_attribute('aria-checked', 'true')
    current.press('ArrowDown')
    expect(menu.locator('[data-agent-id="2"]')).to_be_focused()
    assert not patches
    page.keyboard.press('Enter')
    page.wait_for_timeout(100)
    assert patches == [('PATCH', {'staff_agent_id': 2})]
    assert len(held) == 1  # Assignment rerender does not start another lookup.


def test_explicit_reassign_modal_shares_the_card_request_limit(page, api, live_server, grouped_visit):
    first, second = grouped_visit
    held = setup(page, live_server)
    page.locator(f'.agent-select-badge[data-id="{first}"]').click()
    page.wait_for_timeout(50)
    row = next(row for row in api.get('/api/v1/portal/service-requests').json() if row['id'] == second)
    page.evaluate('(row) => { window.openReassignModal(row); }', row)
    page.wait_for_timeout(50)
    assert len(held) == 1
    finish(held[0])
    page.wait_for_timeout(100)
    assert len(held) == 2
    assert held[1].request.url.endswith(f'/{second}/available-agents')
    finish(held[1])
    expect(page.locator('#reassign-agent-select')).to_contain_text('Tech One')


def test_disabled_current_control_does_not_request_even_if_original_row_was_active(page, live_server, grouped_visit):
    held = setup(page, live_server)
    target = page.locator('.agent-select-badge:not([disabled])').first.get_attribute('data-id')
    select = page.locator(f'.agent-select-badge[data-id="{target}"]')
    select.evaluate('(node) => { node.disabled = true; }')
    select.dispatch_event('click')
    page.wait_for_timeout(50)
    assert not held


def test_detached_queued_card_does_not_cancel_live_modal_for_same_request(page, api, live_server, grouped_visit):
    first, second = grouped_visit
    held = setup(page, live_server)
    page.locator(f'.agent-select-badge[data-id="{first}"]').click()
    page.wait_for_timeout(50)
    card = page.locator(f'.agent-select-badge[data-id="{second}"]')
    card.click()
    card.evaluate('(node) => node.closest("tr").remove()')
    row = next(row for row in api.get('/api/v1/portal/service-requests').json() if row['id'] == second)
    page.evaluate('(row) => { window.openReassignModal(row); }', row)
    assert len(held) == 1
    finish(held[0])
    page.wait_for_timeout(100)
    assert len(held) == 2
    finish(held[1])
    expect(page.locator('#reassign-agent-select')).to_contain_text('Tech One')
