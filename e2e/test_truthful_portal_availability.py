"""Live portal choices cannot survive unknown lookup or a stale form response."""
from datetime import timedelta

import pytest
from playwright.sync_api import expect

from e2e.scenarios import capacity_snapshot
from e2e.test_selective_service_boundaries import grouped_visit as grouped_visit  # noqa: PLC0414
from e2e.test_selective_service_browser import open_selected


def response(route, start, *, failure=False):
    if failure:
        route.fulfill(status=503, json={'detail': {'error_code': 'AVAILABILITY_UNKNOWN',
            'availability_status': 'unknown', 'retryable': True, 'message': 'Cannot verify availability'}})
    else:
        route.fulfill(json={'success': True, 'available_slots': [{'start_time': start.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': (start + timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S'), 'available_agents_count': 1}]})


def hold(page, live_server, target):
    held = []
    page.route('**/available-slots?**', lambda route: held.append(route))
    open_selected(page, live_server, target)
    return held


def check(page):
    with page.expect_request(lambda req: '/available-slots?' in req.url):
        page.locator('#sr-check-slots-btn').click()


@pytest.mark.parametrize('failure', ['unknown', 'network'])
def test_current_failure_clears_previous_slot_time_and_consent(page, db, scenario, grouped_visit, live_server, failure):
    target, _ = grouped_visit
    held = hold(page, live_server, target)
    before = capacity_snapshot(db)
    chosen = scenario['start'] + timedelta(hours=2)
    check(page)
    response(held[0], chosen)
    expect(page.locator('#sr-slots-dropdown option')).to_have_count(2)
    page.locator('#sr-slots-dropdown').select_option(chosen.strftime('%Y-%m-%d %H:%M:%S'))
    page.locator('#sr-customer-consent-check').check()
    check(page)
    if failure == 'unknown': response(held[1], chosen, failure=True)
    else: held[1].abort('failed')
    expect(page.locator('#sr-slots-dropdown')).to_contain_text('could not be verified')
    expect(page.locator('#sr-slots-dropdown option')).to_have_count(1)
    expect(page.locator('#sr-booking-time')).to_have_value('')
    expect(page.locator('#sr-customer-consent-check')).not_to_be_checked()
    expect(page.locator('#sr-check-slots-btn')).to_be_enabled()
    assert capacity_snapshot(db) == before


@pytest.mark.parametrize('failure', [False, True])
def test_old_date_response_cannot_change_new_pending_result_or_button(page, scenario, grouped_visit, live_server, failure):
    held = hold(page, live_server, grouped_visit[0])
    check(page)
    expect(page.locator('#sr-check-slots-btn')).to_be_disabled()
    newer_date = (scenario['start'] + timedelta(days=1)).date().isoformat()
    page.locator('#sr-check-date-picker').fill(newer_date)
    page.locator('#sr-check-date-picker').dispatch_event('change')
    # New intent queues behind old request; no concurrent provider availability.
    assert len(held) == 1
    with page.expect_request(lambda req: '/available-slots?' in req.url and newer_date in req.url):
        response(held[0], scenario['start'], failure=failure)
    expect(page.locator('#sr-check-slots-btn')).to_be_disabled()
    expect(page.locator('#sr-slots-dropdown')).not_to_contain_text('could not be verified')
    newer_start = scenario['start'] + timedelta(days=1, hours=1)
    response(held[1], newer_start)
    expect(page.locator('#sr-slots-dropdown option')).to_have_count(2)
    expect(page.locator('#sr-check-date-picker')).to_have_value(newer_date)
    expect(page.locator('#sr-slots-dropdown option').nth(1)).to_have_attribute('value', newer_start.strftime('%Y-%m-%d %H:%M:%S'))


@pytest.mark.parametrize('failure', [False, True])
def test_old_closed_modal_response_cannot_overwrite_reopened_appointment(page, scenario, grouped_visit, live_server, failure):
    first, second = grouped_visit
    held = hold(page, live_server, first)
    check(page)
    page.locator('#close-sr-modal-btn').click()
    page.locator(f'.edit-sr-btn[data-id="{second}"]').click()
    original = page.locator('#sr-booking-time').input_value()
    page.locator('#sr-issue-desc').fill('Newer appointment edit')
    response(held[0], scenario['start'], failure=failure)
    page.wait_for_timeout(30)
    expect(page.locator('#sr-form-id')).to_have_value(str(second))
    expect(page.locator('#sr-booking-time')).to_have_value(original)
    expect(page.locator('#sr-issue-desc')).to_have_value('Newer appointment edit')
    expect(page.locator('#sr-available-slots-container')).not_to_be_visible()
    expect(page.locator('#sr-check-slots-btn')).to_be_enabled()


def test_changed_booking_time_invalidates_old_lookup(page, scenario, grouped_visit, live_server):
    held = hold(page, live_server, grouped_visit[0])
    check(page)
    newer = (scenario['start'] + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M')
    page.locator('#sr-booking-time').fill(newer)
    page.locator('#sr-booking-time').dispatch_event('change')
    response(held[0], scenario['start'])
    page.wait_for_timeout(30)
    expect(page.locator('#sr-slots-dropdown option')).to_have_count(1)
    expect(page.locator('#sr-slots-dropdown')).to_contain_text('Check availability')
    expect(page.locator('#sr-booking-time')).to_have_value(newer)
    expect(page.locator('#sr-check-slots-btn')).to_be_enabled()


@pytest.mark.parametrize('kind,duration,booking_type', [('grouped', 90, 'appointment'), ('callback', 15, 'callback')])
def test_missing_optional_controls_preserve_record_metadata_in_lookup_and_save(page, api, db, scenario, grouped_visit, live_server, kind, duration, booking_type):
    from serviceBot.services.booking import BookingService
    if kind == 'callback':
        target = BookingService().reserve_multi_service_appointment(customer_id=1, services=['Oil Change'],
            appointment_datetime=scenario['start'] + timedelta(hours=3), booking_type='callback',
            vehicle_details={'make': 'Toyota', 'model': 'Camry', 'year': 2020})[0]['service_request_id']
    else:
        target = grouped_visit[0]
    before = db('SELECT * FROM service_requests WHERE id=%s', (target,))[0]
    reservations = db('SELECT * FROM appointment_reservations ORDER BY id')
    held = hold(page, live_server, target)
    assert page.locator('#sr-booking-type').count() == page.locator('#sr-duration-minutes').count() == 0
    check(page)
    assert f'duration_minutes={duration}' in held[0].request.url
    assert f'staff_agent_id={before["staff_agent_id"]}' in held[0].request.url
    response(held[0], scenario['start'] + timedelta(hours=4))
    expect(page.locator('#sr-check-slots-btn')).to_be_enabled()
    page.locator('#sr-issue-desc').fill('Record metadata preserved')
    page.locator('#sr-save-btn').click()
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(f'/service-requests/{target}')) as saved:
        page.locator('#confirm-modal-yes').click()
    assert saved.value.status == 200, saved.value.text()
    payload = saved.value.request.post_data_json
    assert payload['booking_type'] == booking_type and payload['duration_minutes'] == duration
    after = db('SELECT * FROM service_requests WHERE id=%s', (target,))[0]
    for key in ('booking_type', 'duration_minutes', 'staff_agent_id', 'booking_time', 'service_components'):
        assert after[key] == before[key]
    assert db('SELECT * FROM appointment_reservations ORDER BY id') == reservations


def test_new_form_does_not_inherit_previous_grouped_metadata(page, scenario, grouped_visit, live_server):
    held = hold(page, live_server, grouped_visit[0])
    page.locator('#close-sr-modal-btn').click()
    page.locator('#btn-new-request').click()
    check(page)
    assert 'duration_minutes=60' in held[0].request.url
    assert 'staff_agent_id=' not in held[0].request.url
    response(held[0], scenario['start'])
    expect(page.locator('#sr-check-slots-btn')).to_be_enabled()
