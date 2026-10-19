"""Portal availability is explicit, bounded and never an assignment by itself."""
import json

from playwright.sync_api import expect

from e2e.test_selective_service_boundaries import grouped_visit as grouped_visit  # noqa: PLC0414


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


def test_render_is_readonly_and_requests_are_lazy_deduplicated_serial(page, live_server, grouped_visit):
    held = setup(page, live_server)
    assert held == []
    selects = page.locator('.agent-select-badge:not([disabled])')
    first, second = selects.nth(0), selects.nth(1)
    first.dispatch_event('pointerdown')
    page.wait_for_timeout(50)
    assert len(held) == 1
    first.dispatch_event('pointerdown')
    first.focus()
    second.focus()
    page.wait_for_timeout(50)
    assert len(held) == 1
    finish(held[0])
    page.wait_for_timeout(100)
    assert len(held) == 2
    finish(held[1])
    expect(second.locator('option[value="2"]')).to_have_text('Tech Two - Technician')


def test_failure_preserves_assignment_retries_only_on_interaction_and_ignores_detached_row(page, live_server, grouped_visit):
    held = setup(page, live_server)
    assignments = []
    page.on('request', lambda request: assignments.append(request.url) if request.url.endswith('/assign-agent') else None)
    assert not held
    select = page.locator('.agent-select-badge:not([disabled])').first
    original = select.inner_html()
    select.dispatch_event('pointerdown')
    page.wait_for_timeout(50)
    finish(held[0], 503)
    page.wait_for_timeout(50)
    assert select.inner_html() == original
    assert len(held) == 1
    select.dispatch_event('pointerdown')
    page.wait_for_timeout(50)
    assert len(held) == 2
    page.evaluate("window.detachedAgent = document.querySelector('.agent-select-badge:not([disabled])'); window.detachedAgent.closest('tr').remove()")
    finish(held[1])
    page.wait_for_timeout(50)
    assert len(held) == 2
    assert page.evaluate('window.detachedAgent.innerHTML') == original
    assert not assignments


def test_closed_rows_and_rerenders_do_not_fetch_availability(page, api, live_server, grouped_visit):
    rows = api.get('/api/v1/portal/service-requests').json()
    for row in rows:
        row['status'] = 'completed'
    page.route('**/api/v1/portal/service-requests', lambda route: route.fulfill(json=rows))
    held = setup(page, live_server)
    expect(page.locator('.agent-select-badge:not([disabled])')).to_have_count(0)
    page.locator('.agent-select-badge').first.dispatch_event('pointerdown')
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
    current = select.locator('option[value="1"]')
    expect(current).to_be_enabled()
    expect(current).to_have_attribute('data-whatsapp-connected', 'false')
    expect(current).to_contain_text('Unavailable - Busy')
    assert not patches
    expect(select).to_have_value('1')
    # Native select_option exercises the browser selection/change boundary.
    select.select_option('2')
    page.wait_for_timeout(100)
    assert patches == [('PATCH', {'staff_agent_id': 2})]
    assert len(held) == 1  # Assignment rerender does not start another lookup.


def test_explicit_reassign_modal_shares_the_card_request_limit(page, api, live_server, grouped_visit):
    first, second = grouped_visit
    held = setup(page, live_server)
    page.locator(f'.agent-select-badge[data-id="{first}"]').dispatch_event('pointerdown')
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
    select.dispatch_event('pointerdown')
    page.wait_for_timeout(50)
    assert not held


def test_detached_queued_card_does_not_cancel_live_modal_for_same_request(page, api, live_server, grouped_visit):
    first, second = grouped_visit
    held = setup(page, live_server)
    page.locator(f'.agent-select-badge[data-id="{first}"]').dispatch_event('pointerdown')
    page.wait_for_timeout(50)
    card = page.locator(f'.agent-select-badge[data-id="{second}"]')
    card.dispatch_event('pointerdown')
    card.evaluate('(node) => node.closest("tr").remove()')
    row = next(row for row in api.get('/api/v1/portal/service-requests').json() if row['id'] == second)
    page.evaluate('(row) => { window.openReassignModal(row); }', row)
    assert len(held) == 1
    finish(held[0])
    page.wait_for_timeout(100)
    assert len(held) == 2
    finish(held[1])
    expect(page.locator('#reassign-agent-select')).to_contain_text('Tech One')
