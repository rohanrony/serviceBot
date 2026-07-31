import os
import pytest


def test_html_dom_structure_for_sms_components():
    html_path = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "index.html")
    assert os.path.exists(html_path)

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 1. Nav items presence
    assert 'data-tab="sms-inbox"' in html_content
    assert 'data-tab="sms-config"' in html_content

    # 2. View sections presence
    assert 'id="sms-inbox-view"' in html_content
    assert 'id="sms-config-view"' in html_content

    # 3. Live Inbox DOM elements
    assert 'id="sms-thread-filter"' in html_content
    assert 'id="sms-threads-list"' in html_content
    assert 'id="chat-messages-container"' in html_content
    assert 'id="sms-reply-input"' in html_content
    assert 'id="send-sms-reply-btn"' in html_content
    assert 'id="mark-resolved-btn"' in html_content
    assert 'id="sms-context-details"' in html_content

    # 4. SMS Configuration DOM elements
    assert 'id="sms-global-config-form"' in html_content
    assert 'id="sms-config-support-phone"' in html_content
    assert 'id="sms-config-environment"' in html_content
    assert 'id="sms-config-quiet-start"' in html_content
    assert 'id="sms-config-quiet-end"' in html_content
    assert 'id="sms-config-auto-responder"' in html_content
    assert 'id="sms-matrix-rules-tbody"' in html_content
    assert 'id="sms-whitelist-tbody"' in html_content
    assert 'id="sms-add-whitelist-form"' in html_content

    # 5. SMS Log Drawer DOM elements
    assert 'id="sms-log-drawer"' in html_content
    assert 'id="sms-log-items-container"' in html_content

    # 6. Bug fixes DOM elements (Bugs 01-06)
    assert 'id="new-agent-phone"' in html_content
    assert 'id="verify-agent-twilio-btn"' in html_content
    assert 'value="confirmed"' in html_content
    assert 'value="cancelled_by_customer"' in html_content
    assert 'value="AUTOMATED"' in html_content


def test_js_app_functions_registered():
    js_path = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "app.js")
    assert os.path.exists(js_path)

    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "loadSMSConfig" in js_content
    assert "loadSMSMatrixRules" in js_content
    assert "loadSMSWhitelist" in js_content
    assert "loadSMSConversations" in js_content
    assert "loadSMSMessages" in js_content
    assert "openSMSLogDrawer" in js_content
    assert "details-sms-log-btn" in js_content
    assert "sidebar-reschedule-btn" in js_content
    assert "sidebar-cancel-btn" in js_content


def test_api_bug_fixes_verification():
    from fastapi.testclient import TestClient
    from serviceBot.main import app
    from serviceBot.db.seed import seed_db

    seed_db(force=True)
    client = TestClient(app)

    # Verify Service Requests endpoint includes has_failed_sms
    res = client.get("/api/v1/portal/service-requests")
    assert res.status_code == 200
    reqs = res.json()
    assert len(reqs) > 0
    assert "has_failed_sms" in reqs[0]

    # Verify status update for confirmed and cancelled_by_customer
    req_id = reqs[0]["id"]
    res_status = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "confirmed"})
    assert res_status.status_code == 200
    assert res_status.json()["data"]["status"] == "confirmed"

    res_status = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "cancelled_by_customer"})
    assert res_status.status_code == 200
    assert res_status.json()["data"]["status"] == "cancelled_by_customer"

    # Verify staff agent creation with phone_number
    res_agent = client.post("/api/v1/portal/agents", json={
        "name": "Test Agent Bug2",
        "role": "Technician",
        "email": "agent_bug2@example.com",
        "phone_number": "+15559990000"
    })
    assert res_agent.status_code in (200, 201)
    assert res_agent.json()["name"] == "Test Agent Bug2"

    # Verify AUTOMATED thread filtering
    res_convs = client.get("/api/v1/portal/sms/conversations?state=AUTOMATED")
    assert res_convs.status_code == 200
    assert isinstance(res_convs.json(), list)


def test_comprehensive_sms_log_drawer_details():
    from fastapi.testclient import TestClient
    from serviceBot.main import app
    from serviceBot.db.seed import seed_db

    seed_db(force=True)
    client = TestClient(app)

    # 1. Fetch appointment SMS log endpoint
    res = client.get("/api/v1/portal/sms/logs/appointment/1")
    assert res.status_code == 200
    data = res.json()

    assert "appointment" in data
    assert "logs" in data
    assert isinstance(data["logs"], list)

    app_details = data["appointment"]
    if app_details:
        assert "customer_name" in app_details
        assert "customer_phone" in app_details
        assert "service_type" in app_details
        assert "status" in app_details

    # 2. Check JS content for comprehensive log drawer features
    js_path = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "Appointment Details" in js_content
    assert "Booking Confirmation" in js_content
    assert "getStatusBadgeHtml" in js_content
    assert "Skip Reason" in js_content
    assert "Error Details" in js_content
    assert "function formatLocalTimestamp" in js_content
    assert "formatLocalTimestamp(l.created_at)" in js_content


