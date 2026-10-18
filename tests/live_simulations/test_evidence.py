import pytest
from live_simulations.evidence import compare, verify_tools, browser_readback, require_delivery
from live_simulations.core import SimulationError


def test_missing_or_wrong_observed_values_never_pass():
    assert compare(1, 1, 'eq')
    assert not compare(None, 0, 'eq')
    assert not compare(1, 2, 'eq')
    with pytest.raises(SimulationError):
        compare(1, 1, 'invented')


def test_failed_tool_is_not_success_and_forbidden_mutation_is_detected():
    case = {'expected_tools': ['cancel_appointment'], 'forbidden_tools': []}
    trace = [{'name': 'cancel_appointment', 'response': {'result': {'success': False}}}]
    assert not all(c['passed'] for c in verify_tools(case, trace))
    case = {'expected_tools': [], 'forbidden_tools': ['create_service_request']}
    assert not all(c['passed'] for c in verify_tools(case, [{'name': 'create_service_request', 'response': {}}]))


def test_outbox_delivered_or_provider_acceptance_are_not_receiver_proof():
    sid = 'SM' + 'a' * 32
    assert not require_delivery({'status': 'sent', 'sid': sid}, callback=False)
    assert not require_delivery({'status': 'delivered', 'sid': sid}, callback=False)
    assert require_delivery({'status': 'delivered', 'sid': sid}, callback=True)
    assert not require_delivery({'status': 'delivered', 'sid': 'mock-id'}, callback=True)


def test_browser_readback_reloads_and_asserts_actual_row():
    calls = []
    class Row:
        def locator(self, selector): return self
        def count(self): return 1
        def inner_text(self): return 'Fixture Oil Change pending'
        def input_value(self): return 'pending'
    class Reply:
        def json(self): return [{'id': 7, 'service_type': 'Oil Change', 'status': 'pending'}]
    class Page:
        @property
        def request(self): return self
        def get(self, url): calls.append(('read', url)); return Reply()
        def goto(self, url): calls.append(('goto', url))
        def reload(self): calls.append(('reload',))
        def wait_for_selector(self, selector, **kw): calls.append(('wait', selector))
        def locator(self, selector): calls.append(('locator', selector)); return Row()
    result = browser_readback(Page(), 'http://127.0.0.1:8011', [{'id': 7, 'service_type': 'Oil Change', 'status': 'pending'}])
    assert all(c['passed'] for c in result)
    assert ('reload',) in calls
    assert any('data-id="7"' in str(c) for c in calls)


def test_whatsapp_message_body_and_receiver_are_checked():
    import httpx
    from live_simulations.evidence import whatsapp_checks
    sid = 'SM' + 'b' * 32
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'sid': sid, 'to': 'whatsapp:+12125551234', 'status': 'delivered', 'body': 'Wrong vehicle'})))
    checks = whatsapp_checks(client, None, [{'twilio_message_sid': sid, 'status': 'DELIVERED'}],
                             [{'MessageSid': sid, 'MessageStatus': 'delivered'}], ('account', 'token'),
                             {'+12125551234'}, fragments=['Toyota', 'Camry'])
    assert any(c['name'] == 'WhatsApp content matches fixture' and not c['passed'] for c in checks)
