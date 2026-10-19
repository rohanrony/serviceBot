"""Selective component removal through the actual portal and PostgreSQL authority."""
from copy import deepcopy
from datetime import timedelta

import pytest
from playwright.sync_api import expect

from e2e.test_selective_service_boundaries import grouped_visit as grouped_visit  # noqa: PLC0414 - pytest fixture re-export
from e2e.test_voice_mutation_ownership import snapshot
from e2e.test_workflows import request_by_id


def open_selected(page,live_server,request_id):
    page.goto(live_server+'/portal/')
    page.locator(f'.edit-sr-btn[data-id="{request_id}"]').click()
    expect(page.locator('#sr-modal')).to_be_visible()


def preserved_companion(api,request_id,before):
    after=request_by_id(api,request_id)
    for field in ('booking_start_time','booking_end_time','duration_minutes','service_components','status'):
        assert after[field]==before[field]


def test_exact_component_controls_require_a_structured_snapshot(page,api,grouped_visit,live_server):
    target,_=grouped_visit
    open_selected(page,live_server,target)
    expect(page.get_by_label('Service to remove')).to_be_visible()
    expect(page.get_by_label('Service to remove').locator('option')).to_have_text(['Oil Change — 60 minutes','Tire Rotation — 30 minutes'])
    page.get_by_role('button',name='Remove selected service',exact=True).click()
    expect(page.locator('#confirm-modal-msg')).to_contain_text('Customer consent')
    expect(page.locator('#confirm-modal-msg')).to_contain_text('start stays')
    expect(page.locator('#confirm-modal-msg')).to_contain_text('Other appointments stay unchanged')
    page.locator('#confirm-modal-no').click()
    unsupported=deepcopy(request_by_id(api,target));unsupported['service_components']=None
    page.evaluate('(request) => window.openSREditModal(request)',unsupported)
    expect(page.get_by_label('Service to remove')).to_have_count(0)


@pytest.mark.parametrize('service,remaining',[('Oil Change',30),('Tire Rotation',60)])
def test_removal_keeps_start_shortens_end_releases_trailing_capacity_and_reloads(page,api,db,scenario,grouped_visit,live_server,service,remaining):
    target,companion=grouped_visit
    before=request_by_id(api,target);other=request_by_id(api,companion)
    open_selected(page,live_server,target)
    page.get_by_label('Service to remove').select_option(service)
    page.get_by_role('button',name='Remove selected service',exact=True).click()
    expected_end=(scenario['start']+timedelta(minutes=remaining)).strftime('%Y-%m-%d %H:%M:%S')
    expect(page.locator('#confirm-modal-msg')).to_contain_text(expected_end)
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith(f'/{target}/remove-service')) as response:
        page.locator('#confirm-modal-yes').click()
    assert response.value.status==200
    expect(page.locator('#sr-remove-service-feedback')).to_contain_text('Service removed; other appointments unchanged.')
    readback=page.locator('#sr-component-readback')
    expect(readback).to_contain_text(f'Duration: {remaining} minutes')
    expect(readback).to_contain_text('End: '+expected_end)
    expect(readback).to_contain_text('Notification queue: PENDING; delivery unverified')
    expect(readback).to_contain_text('Calendar: PENDING_CALENDAR')
    after=request_by_id(api,target)
    assert after['booking_start_time']==before['booking_start_time']
    assert after['booking_end_time']==expected_end
    assert service not in {c['name'] for c in after['service_components']}
    preserved_companion(api,companion,other)
    segments=db('SELECT seg.segment_start FROM appointment_reservation_segments seg JOIN appointment_reservations r ON r.id=seg.reservation_id WHERE r.service_request_id=%s ORDER BY seg.segment_start',(target,))
    assert [r['segment_start'] for r in segments]==[scenario['start']+timedelta(minutes=i) for i in range(0,remaining,15)]
    released=db('SELECT is_booked,reservation_status,service_request_id FROM mock_calendar_slots WHERE staff_agent_id=1 AND slot_datetime>=%s AND slot_datetime<%s ORDER BY slot_datetime',
                (scenario['start']+timedelta(minutes=remaining),scenario['start']+timedelta(minutes=90)))
    assert released and all(not r['is_booked'] and r['reservation_status']=='AVAILABLE' and r['service_request_id'] is None for r in released)
    # A fresh document must use persisted API state, including the new queue state.
    open_selected(page,live_server,target)
    expect(page.locator('#sr-component-readback')).to_contain_text(f'Duration: {remaining} minutes')
    expect(page.locator('#sr-component-readback')).to_contain_text('Notification queue: PENDING; delivery unverified')


def test_final_component_cancels_only_selected_appointment_with_history_readback(page,api,db,grouped_visit,live_server):
    target,selected=grouped_visit;other=request_by_id(api,target)
    open_selected(page,live_server,selected)
    page.get_by_label('Service to remove').select_option('Brake Inspection')
    page.get_by_role('button',name='Remove selected service',exact=True).click()
    expect(page.locator('#confirm-modal-msg')).to_contain_text('Only this appointment will be cancelled')
    page.locator('#confirm-modal-yes').click()
    expect(page.locator('#sr-remove-service-feedback')).to_contain_text('Selected appointment cancelled; other appointments unchanged.')
    expect(page.locator('#sr-component-readback')).to_contain_text('Status: cancelled')
    expect(page.locator('#sr-component-readback')).to_contain_text('Notification queue: PENDING; delivery unverified')
    expect(page.get_by_label('Service to remove')).to_have_count(0)
    assert not db("SELECT id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'",(selected,))
    preserved_companion(api,target,other)
    open_selected(page,live_server,selected)
    expect(page.locator('#sr-component-readback')).to_contain_text('Status: cancelled')


def test_declined_consent_never_sends_removal_or_changes_state(page,api,db,grouped_visit,live_server):
    target,_=grouped_visit;before=snapshot(db);requests=[]
    page.on('request',lambda r:requests.append(r.url) if r.url.endswith('/remove-service') else None)
    open_selected(page,live_server,target)
    page.get_by_role('button',name='Remove selected service',exact=True).click()
    page.locator('#confirm-modal-no').click()
    assert not requests
    assert snapshot(db)==before


def test_stale_snapshot_rejection_is_honest_and_has_no_new_effects(page,api,db,grouped_visit,live_server):
    target,_=grouped_visit;open_selected(page,live_server,target)
    changed=api.post(f'/api/v1/portal/service-requests/{target}/remove-service',json={'service_name':'Oil Change','customer_consent_obtained':True})
    assert changed.status_code==200
    before=snapshot(db)
    page.get_by_label('Service to remove').select_option('Oil Change')
    page.get_by_role('button',name='Remove selected service',exact=True).click()
    page.locator('#confirm-modal-yes').click()
    expect(page.locator('#sr-remove-service-feedback')).to_contain_text('canonical service')
    expect(page.get_by_role('button',name='Remove selected service',exact=True)).to_be_disabled()
    assert snapshot(db)==before
    expect(page.locator('#sr-save-btn')).to_be_disabled()
    # Reopening a cached edit row must not enable a blind mutation retry.
    page.locator('#close-sr-modal-btn').click()
    page.locator(f'.edit-sr-btn[data-id="{target}"]').click()
    expect(page.get_by_role('button',name='Remove selected service',exact=True)).to_be_disabled()
    expect(page.locator('#sr-save-btn')).to_be_disabled()
    page.get_by_role('button',name='Reload appointment',exact=True).click()
    expect(page.locator('#sr-component-readback')).to_contain_text('Duration: 30 minutes')
    expect(page.get_by_label('Service to remove').locator('option')).to_have_text(['Tire Rotation — 30 minutes'])


def test_lost_response_shows_unknown_without_retry_then_readonly_reload(page,api,grouped_visit,live_server):
    target,companion=grouped_visit;other=request_by_id(api,companion);attempts=[]
    def lose_response(route):
        attempts.append(route.request.post_data_json)
        response=route.fetch()
        assert response.status==200
        route.abort('failed')
    page.route(f'**/service-requests/{target}/remove-service',lose_response)
    open_selected(page,live_server,target)
    page.get_by_role('button',name='Remove selected service',exact=True).click()
    page.locator('#confirm-modal-yes').click()
    expect(page.locator('#sr-remove-service-feedback')).to_contain_text('Removal outcome is unknown')
    expect(page.get_by_role('button',name='Remove selected service',exact=True)).to_be_disabled()
    expect(page.locator('#sr-save-btn')).to_be_disabled()
    assert attempts==[{'service_name':'Oil Change','customer_consent_obtained':True}]
    assert request_by_id(api,target)['duration_minutes']==30
    preserved_companion(api,companion,other)
    page.get_by_role('button',name='Reload appointment',exact=True).click()
    expect(page.locator('#sr-component-readback')).to_contain_text('Duration: 30 minutes')
    assert len(attempts)==1


@pytest.mark.parametrize('kind',['legacy','callback','malformed','completed'])
def test_unsupported_records_never_offer_component_removal(page,api,db,grouped_visit,live_server,kind):
    target,_=grouped_visit
    if kind=='legacy':db('UPDATE service_requests SET service_components=NULL WHERE id=%s',(target,))
    elif kind=='callback':db("UPDATE service_requests SET booking_type='callback' WHERE id=%s",(target,))
    elif kind=='completed':db("UPDATE service_requests SET status='completed' WHERE id=%s",(target,))
    else:db('UPDATE service_requests SET service_components=%s WHERE id=%s',('[{"name":"Oil Change","duration_minutes":60},{"name":"Oil Change","duration_minutes":30}]',target))
    open_selected(page,live_server,target)
    expect(page.get_by_label('Service to remove')).to_have_count(0)
    expect(page.get_by_role('button',name='Remove selected service',exact=True)).to_have_count(0)


def test_success_response_without_matching_native_readback_is_not_success(page,db,grouped_visit,live_server):
    target,_=grouped_visit;before=snapshot(db)
    page.route(f'**/service-requests/{target}/remove-service',lambda route:route.fulfill(status=200,json={'success':True}))
    open_selected(page,live_server,target)
    page.get_by_role('button',name='Remove selected service',exact=True).click()
    page.locator('#confirm-modal-yes').click()
    expect(page.locator('#sr-remove-service-feedback')).to_contain_text('saved outcome could not be verified')
    expect(page.locator('#sr-save-btn')).to_be_disabled()
    expect(page.get_by_role('button',name='Remove selected service',exact=True)).to_be_disabled()
    assert snapshot(db)==before


@pytest.mark.parametrize('operation',['remove','reload'])
def test_late_selected_appointment_response_preserves_another_open_edit(page,api,grouped_visit,live_server,operation):
    selected,companion=grouped_visit;held=[]
    open_selected(page,live_server,selected)
    if operation=='remove':
        def hold(route):
            response=route.fetch()
            held.append((route,response))
        page.route(f'**/service-requests/{selected}/remove-service',hold)
        page.get_by_role('button',name='Remove selected service',exact=True).click()
        with page.expect_request(f'**/service-requests/{selected}/remove-service'):
            page.locator('#confirm-modal-yes').click()
    else:
        def hold(route):
            response=route.fetch()
            held.append((route,response))
        page.route('**/api/v1/portal/service-requests',hold)
        with page.expect_request('**/api/v1/portal/service-requests'):
            page.get_by_role('button',name='Reload appointment',exact=True).click()
    page.locator('#close-sr-modal-btn').click()
    page.locator(f'.edit-sr-btn[data-id="{companion}"]').click()
    page.locator('#sr-issue-desc').fill('Keep this unsaved companion edit')
    assert held
    for route,response in held:
        route.fulfill(response=response)
    # Read-back after removal fetches the list too; only the explicit reload was held.
    if operation=='reload':page.unroute('**/api/v1/portal/service-requests')
    # Await the original operation's asynchronous read-back without trusting a sleep.
    if operation=='remove':
        expect(page.locator('#sr-form-id')).to_have_value(str(companion))
        page.wait_for_function(f"() => !document.querySelector('.edit-sr-btn[data-id=\"{selected}\"]')?.closest('tr')?.textContent.includes('Oil Change')")
    else:
        page.wait_for_function("() => document.getElementById('sr-form-id').value !== ''")
    expect(page.locator('#sr-form-id')).to_have_value(str(companion))
    expect(page.locator('#sr-issue-desc')).to_have_value('Keep this unsaved companion edit')
    expect(page.locator('#sr-save-btn')).to_be_enabled()
