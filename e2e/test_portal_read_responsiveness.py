"""Native portal listing keeps the loop responsive during calendar reads."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from e2e.test_workflows import PORTAL


def test_past_candidates_skip_google_but_future_and_unknown_keep_behavior(api, db, scenario, freeze_business_clock, monkeypatch):
    from serviceBot.db import queries
    freeze_business_clock(scenario['start'])
    db("UPDATE service_requests SET escalation_status='escalated', booking_time=%s WHERE id=1", [(scenario['start']-timedelta(minutes=1)).isoformat(' ')])
    future = db("INSERT INTO service_requests(customer_id,vehicle_id,service_type,status,escalation_status,booking_type,booking_time) VALUES(1,1,'Future request','pending','escalated','appointment',%s) RETURNING id", [(scenario['start']+timedelta(days=1)).isoformat(' ')])[0]['id']
    unknown = db("INSERT INTO service_requests(customer_id,vehicle_id,service_type,status,escalation_status,booking_type,booking_time) VALUES(1,1,'Unknown request','pending','escalated','appointment','not parseable') RETURNING id")[0]['id']
    seen = []
    monkeypatch.setattr(queries,'get_available_agents_for_request',lambda request_id: seen.append(request_id) or [{'id':2,'name':'Morgan E2E'}])
    response = api.get(PORTAL+'/service-requests',params={'escalated':'true'})
    assert response.status_code == 200
    rows = {row['id']:row for row in response.json()}
    assert rows[1]['candidate_agents'] == []
    assert set(seen) == {future,unknown}
    assert rows[future]['candidate_agents'] == [{'id':2,'name':'Morgan E2E'}]
    assert rows[unknown]['candidate_agents'] == [{'id':2,'name':'Morgan E2E'}]


def test_held_future_candidate_read_keeps_health_responsive_and_completes(api, db, scenario, freeze_business_clock, monkeypatch):
    from serviceBot.db import queries
    freeze_business_clock(scenario['start']-timedelta(days=1))
    db("UPDATE service_requests SET escalation_status='escalated',booking_time=%s WHERE id=1",[scenario['start'].isoformat(' ')])
    entered, release = Event(), Event()
    def held(request_id):
        entered.set()
        assert release.wait(5),'test failed to release calendar boundary'
        return [{'id':2,'name':'Morgan E2E'}]
    monkeypatch.setattr(queries,'get_available_agents_for_request',held)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(api.get,PORTAL+'/service-requests',params={'escalated':'true'})
        assert entered.wait(2)
        try:
            assert api.get('/health',timeout=1).json() == {'status':'healthy'}
            assert not pending.done()
        finally:
            release.set()
        response = pending.result(timeout=2)
    assert response.status_code == 200
    assert response.json()[0]['candidate_agents'] == [{'id':2,'name':'Morgan E2E'}]
    assert db('SELECT escalation_status FROM service_requests WHERE id=1') == [{'escalation_status':'escalated'}]


@pytest.mark.browser
def test_browser_retains_persisted_rows_after_held_candidate_lookup(page, api, db, scenario, freeze_business_clock, monkeypatch):
    from serviceBot.db import queries
    freeze_business_clock(scenario['start']-timedelta(days=1))
    db("UPDATE service_requests SET escalation_status='escalated',booking_time=%s WHERE id=1",[scenario['start'].isoformat(' ')])
    entered, release = Event(), Event()
    def held(request_id):
        entered.set()
        assert release.wait(5)
        return [{'id':2,'name':'Morgan E2E'}]
    monkeypatch.setattr(queries,'get_available_agents_for_request',held)
    with page.expect_request('**/api/v1/portal/service-requests'):
        page.goto(str(api.base_url).rstrip('/')+'/portal/',wait_until='domcontentloaded')
    try:
        assert page.request.get(str(api.base_url).rstrip('/')+'/health',timeout=1000).json() == {'status':'healthy'}
        assert entered.wait(1)
        assert not release.is_set()
    finally:
        release.set()
    page.locator('.edit-sr-btn[data-id="1"]').wait_for(state='attached')
    assert 'Routine oil change' in page.locator('#service-requests-list').inner_text()
    page.locator('.reassign-sr-btn[data-id="1"]').click()
    option = page.locator('#reassign-agent-select option[value="2"]')
    option.wait_for(state='attached')
    assert 'Morgan E2E' in option.inner_text()
    rows = api.get(PORTAL+'/service-requests',params={'escalated':'true'}).json()
    assert rows[0]['id'] == 1 and rows[0]['candidate_agents'] == [{'id':2,'name':'Morgan E2E'}]


def test_listing_memoizes_whatsapp_status_per_exact_staff_phone_only(api, db, monkeypatch):
    from serviceBot.db import queries
    db('UPDATE service_requests SET staff_agent_id=1 WHERE id=1')
    second = db("INSERT INTO service_requests(customer_id,service_type,staff_agent_id) VALUES(1,'Second same-phone request',1) RETURNING id")[0]['id']
    third = db("INSERT INTO service_requests(customer_id,service_type,staff_agent_id) VALUES(1,'Other technician request',2) RETURNING id")[0]['id']
    seen = []
    def status(phone):
        seen.append(phone)
        return phone == '+15550100003'
    monkeypatch.setattr(queries,'is_agent_whatsapp_connected',status)
    response = api.get(PORTAL+'/service-requests')
    assert response.status_code == 200
    rows = {row['id']:row for row in response.json()}
    assert rows[1]['staff_agent_whatsapp_connected'] is True
    assert rows[second]['staff_agent_whatsapp_connected'] is True
    assert rows[third]['staff_agent_whatsapp_connected'] is False
    assert sorted(seen) == ['+15550100003','+15550100004']
    # A later request reads fresh status instead of retaining a process cache.
    seen.clear()
    api.get(PORTAL+'/service-requests')
    assert sorted(seen) == ['+15550100003','+15550100004']


def test_captured_collection_delete_by_exact_ids_preserves_new_and_unrelated_chunks():
    from e2e.conftest import MemoryCollection
    collection = MemoryCollection()
    collection.add(['old','new','other'], [{'filename':'catalog.txt'},{'filename':'catalog.txt'},{'filename':'other.txt'}], ['old-id','new-id','other-id'])
    assert collection.get(where={'filename':'catalog.txt'},include=[]) == {'ids':['old-id','new-id']}
    collection.delete(ids=['old-id'])
    assert set(collection.entries) == {'new-id','other-id'}
    collection.delete(where={'filename':'catalog.txt'})
    assert collection.entries == {'other-id':('other',{'filename':'other.txt'})}


@pytest.fixture
def captured_upload_index(monkeypatch):
    from e2e.conftest import MemoryCollection
    from serviceBot.services.rag import FAQService
    collection = MemoryCollection()
    monkeypatch.setattr(FAQService,'__init__',lambda self: setattr(self,'collection',collection))
    return collection


def test_held_kb_upload_index_does_not_block_health(api,captured_upload_index):
    entered, release = Event(), Event()
    original = captured_upload_index.add
    def held(**kwargs):
        entered.set()
        assert release.wait(5)
        original(**kwargs)
    captured_upload_index.add = held
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(api.post,PORTAL+'/kb/upload',files={'file':('responsive.txt',b'owned upload knowledge','text/plain')})
        assert entered.wait(2)
        try:
            assert api.get('/health',timeout=1).json() == {'status':'healthy'}
            assert not pending.done()
        finally:
            release.set()
        response = pending.result(timeout=2)
    assert response.status_code == 200
    assert response.json() == {'file_id':'kb_doc_responsive.txt','filename':'responsive.txt','chunk_count':1,'success':True}
    assert api.get(PORTAL+'/kb/download/responsive.txt').content == b'owned upload knowledge'


def test_late_upload_embedding_failure_preserves_exact_previous_bytes_chunks_and_unrelated(api,captured_upload_index):
    previous = b'previous exact bytes\r\nUTF-8: \xc3\xa9\n'
    assert api.post(PORTAL+'/kb/upload',files={'file':('preserved.txt',previous,'text/plain')}).status_code == 200
    assert api.post(PORTAL+'/kb/upload',files={'file':('unrelated.txt',b'other original document','text/plain')}).status_code == 200
    before = dict(captured_upload_index.entries)
    original = captured_upload_index.add
    calls = 0
    def failing(**kwargs):
        nonlocal calls
        calls += 1
        original(**kwargs)
        if calls == 2: raise RuntimeError('captured persisted second batch failure')
    captured_upload_index.add = failing
    response = api.post(PORTAL+'/kb/upload',files={'file':('preserved.txt',b'large replacement '*600,'text/plain')})
    assert response.status_code == 500
    assert captured_upload_index.entries == before
    assert api.get(PORTAL+'/kb/download/preserved.txt').content == previous
    assert api.get(PORTAL+'/kb/download/unrelated.txt').content == b'other original document'


@pytest.mark.browser
def test_browser_kb_upload_download_retains_native_file_bytes(page,api,captured_upload_index):
    content = b'Browser-owned exact UTF-8 knowledge: \xc3\xa9\r\n'
    page.goto(str(api.base_url).rstrip('/')+'/portal/',wait_until='domcontentloaded')
    page.locator('.nav-item[data-tab="knowledge"]').click()
    with page.expect_response(lambda response: response.url.endswith('/kb/upload') and response.request.method=='POST') as uploaded:
        page.locator('#kb-file-input').set_input_files({'name':'browser-owned.txt','mimeType':'text/plain','buffer':content})
    assert uploaded.value.status == 200
    assert uploaded.value.json()['success'] is True
    item = page.locator('#kb-files-list').get_by_text('browser-owned.txt',exact=True)
    item.wait_for(state='visible')
    assert api.get(PORTAL+'/kb/download/browser-owned.txt').content == content
    assert any(doc=='Browser-owned exact UTF-8 knowledge: é' and meta['filename']=='browser-owned.txt' for doc,meta in captured_upload_index.entries.values())
