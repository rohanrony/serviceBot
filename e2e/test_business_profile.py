import re
from datetime import timedelta

from playwright.sync_api import expect


def test_services_use_agent_terminology(page, live_server):
    page.goto(f"{live_server}/portal/#services")
    expect(page.locator("#services-view")).to_be_visible()
    expect(page.locator("#services-view th").filter(has_text="Assigned Agents")).to_be_visible()
    expect(page.locator("#services-view")).not_to_contain_text(re.compile("technician", re.I))


def test_agent_scorecard_keeps_existing_analytics_contract(page, live_server):
    page.goto(f"{live_server}/portal/#config/analytics")
    page.locator('[data-analytics-subtab="technicians"]').click()
    expect(page.locator("#analytics-pane-technicians")).to_be_visible()
    expect(page.locator("#technician-scorecard-tbody")).to_contain_text("Taylor E2E")
    expect(page.locator("#analytics-pane-technicians")).not_to_contain_text(re.compile("technician", re.I))


def test_switch_business_create_edit_and_preserve_intake(page, live_server, api, db):
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()
    page.locator("#business-name").fill("Willow Studio")
    page.locator("#business-industry").fill("Salon")
    page.locator("#business-portal-url").fill("https://studio.example")
    if page.locator("#business-collect-vehicle").is_visible():
        page.locator("#business-collect-vehicle").uncheck()
    page.locator("#add-intake-field").click()
    row = page.locator(".business-intake-row").last
    row.locator(".intake-label").fill("Style preference")
    row.locator(".intake-required").check()
    page.locator("#business-profile-form button[type=submit]").click()
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/portal/config")) as saved:
        page.locator("#business-save-confirm-btn").click()
    assert saved.value.ok
    page.reload()
    expect(page.locator("#business-name")).to_have_value("Willow Studio")
    expect(page.locator("#business-portal-url")).to_have_value("https://studio.example")
    if page.locator("#business-collect-vehicle").is_visible():
        expect(page.locator("#business-collect-vehicle")).not_to_be_checked()
    expect(page.locator(".business-intake-row").last.locator(".intake-label")).to_have_value("Style preference")
    page.screenshot(path="scratch/business-profile.png", full_page=True, animations="disabled")

    result = api.post("/api/v1/portal/service-requests", json={
        "customer": {"name": "Salon Customer", "phone": "5550100099"},
        "intake_data": {"style_preference": "Short layers"},
        "service_request": {"service_type": "Consultation", "issue_description": "Discuss style", "booking_type": "appointment"},
    })
    assert result.status_code == 201, result.text
    request_id = result.json()["request_id"]
    record = db("SELECT vehicle_id, intake_data FROM service_requests WHERE id=%s", (request_id,))[0]
    assert record["vehicle_id"] is None
    assert record["intake_data"] == {"style_preference": "Short layers"}

    page.goto(f"{live_server}/portal/#dashboard")
    request_row = page.locator("#service-requests-list tr").filter(has_text="Salon Customer")
    expect(request_row).to_contain_text("Short layers")
    request_row.locator(".edit-sr-btn").click()
    expect(page.locator("#sr-vehicle-section")).not_to_be_visible()
    field = page.locator('[data-intake-key="style_preference"]')
    expect(field).to_have_value("Short layers")
    field.fill("Long layers")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith(f"/service-requests/{request_id}")) as edited:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert edited.value.ok
    page.reload()
    expect(page.locator("#service-requests-list")).to_contain_text("Long layers")
    cfg = api.get("/api/v1/portal/config").json()
    cfg["business_profile"]["intake_fields"] = []
    assert api.post("/api/v1/portal/config", json={"business_profile": cfg["business_profile"]}).status_code == 200
    assert api.put(f"/api/v1/portal/service-requests/{request_id}", json={"issue_description": "Updated after profile change", "intake_data": {}}).status_code == 200
    assert db("SELECT intake_data FROM service_requests WHERE id=%s", (request_id,))[0]["intake_data"] == {"style_preference": "Long layers"}


def test_generic_voice_booking_persists_intake_and_neutral_notification(api, db, scenario, freeze_business_clock):
    profile = {"industry": "Consulting", "collect_vehicle_details": False, "intake_fields": [
        {"key": "topic", "label": "Meeting topic", "type": "text", "required": True},
    ]}
    assert api.post("/api/v1/portal/config", json={"business_profile": profile}).status_code == 200
    payload = {
        "customer_name": "Consulting Customer", "phone": "5550100099", "service_type": "Oil Change",
        "issue_description": "Discuss project", "booking_type": "appointment",
        "booking_time": scenario["start"].strftime("%Y-%m-%d %H:%M:%S"),
        "intake_data_json": '{"topic":"Project scope"}', "call_sid": "generic-voice-test",
    }
    response = api.post("/api/v1/voice/tools?name=create_service_request", json=payload)
    result = response.json()["result"]
    assert result["success"] is True, result
    record = db("SELECT id, vehicle_id, intake_data FROM service_requests WHERE id=%s", (result["service_request_id"],))[0]
    assert record["vehicle_id"] is None
    assert record["intake_data"] == {"topic": "Project scope"}
    notifications = db("SELECT payload FROM outbox_notifications WHERE request_id=%s", (record["id"],))
    assert notifications
    assert any("Meeting topic: Project scope" in str(row["payload"]) for row in notifications)
    from serviceBot.services.sms_reminders import fetch_appointment_customer_details
    assert "Meeting topic: Project scope" in fetch_appointment_customer_details(record["id"])["vehicle"]
    payload["booking_time"] = (scenario["start"] + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    updated = api.post("/api/v1/voice/tools?name=create_service_request", json=payload).json()["result"]
    assert updated["success"] is True, updated
    assert updated["service_request_id"] == record["id"]
    assert len(db("SELECT id FROM service_requests WHERE customer_id=(SELECT customer_id FROM service_requests WHERE id=%s)", (record["id"],))) == 1



def test_generic_request_creation_from_browser(page, live_server, api, db):
    profile = {"industry": "Consulting", "collect_vehicle_details": False, "intake_fields": [
        {"key": "topic", "label": "Meeting topic", "type": "text", "required": True},
        {"key": "attendees", "label": "Extra attendees", "type": "number", "required": False},
    ]}
    assert api.post("/api/v1/portal/config", json={"business_profile": profile}).status_code == 200
    response = api.post("/api/v1/portal/services", json={"name": "Consultation", "duration_minutes": 30})
    assert response.status_code == 201
    page.goto(f"{live_server}/portal/#dashboard")
    page.locator("#btn-new-request").click()
    expect(page.locator("#sr-modal")).to_be_visible()
    expect(page.locator("#sr-vehicle-section")).not_to_be_visible()
    page.locator("#sr-cust-name").fill("Consulting Browser")
    page.locator("#sr-cust-phone").fill("5550100088")
    page.locator("#sr-service-type").select_option(label="Consultation")
    page.locator("#sr-issue-desc").fill("Plan workshop")
    page.locator('[data-intake-key="topic"]').fill("Strategy")
    page.locator('[data-intake-key="attendees"]').fill("0")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/portal/service-requests")) as saved:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert saved.value.status == 201
    request_id = saved.value.json()["request_id"]
    record = db("SELECT vehicle_id, intake_data FROM service_requests WHERE id=%s", (request_id,))[0]
    assert record == {"vehicle_id": None, "intake_data": {"topic": "Strategy", "attendees": 0}}
    page.reload()
    expect(page.locator("#service-requests-list")).to_contain_text("Strategy")
    page.locator("#service-requests-list tr").filter(has_text="Consulting Browser").locator(".edit-sr-btn").click()
    expect(page.locator('[data-intake-key="attendees"]')).to_have_value("0")
    page.locator('[data-intake-key="attendees"]').fill("")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith(f"/service-requests/{request_id}")) as cleared:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert cleared.value.ok
    assert db("SELECT intake_data FROM service_requests WHERE id=%s", (request_id,))[0]["intake_data"] == {"topic": "Strategy"}



def test_invalid_intake_and_conflicting_edit_preserve_durable_state(api, db, scenario, freeze_business_clock):
    profile = {"industry": "Consulting", "collect_vehicle_details": False, "intake_fields": [
        {"key": "topic", "label": "Meeting topic", "type": "text", "required": True},
    ]}
    api.post("/api/v1/portal/config", json={"business_profile": profile})
    payload = {"customer": {"name": "Atomic intake", "phone": "5550100088"}, "service_request": {
        "service_type": "Oil Change", "issue_description": "Original issue", "booking_type": "appointment",
        "booking_time": scenario["start"].strftime("%Y-%m-%d %H:%M:%S"), "duration_minutes": 30,
        "staff_agent_id": 1,
    }}
    def snapshot():
        return {table: db(f"SELECT * FROM {table} ORDER BY id") for table in ("customers", "vehicles", "service_requests", "appointment_reservations", "outbox_notifications")}
    before = snapshot()
    rejected = api.post("/api/v1/portal/service-requests", json=payload)
    assert rejected.status_code == 400
    assert snapshot() == before
    payload["intake_data"] = {"topic": "Original topic"}
    created = api.post("/api/v1/portal/service-requests", json=payload)
    assert created.status_code == 201, created.text
    request_id = created.json()["request_id"]
    new_time = scenario["start"] + timedelta(hours=1)
    db("UPDATE mock_calendar_slots SET is_booked=TRUE, reservation_status='BLOCKED' WHERE slot_datetime >= %s", (new_time,))
    before = snapshot()
    rejected = api.put(f"/api/v1/portal/service-requests/{request_id}", json={
        "issue_description": "Changed issue", "intake_data": {"topic": "Changed topic"},
        "booking_time": new_time.strftime("%Y-%m-%d %H:%M:%S"), "duration_minutes": 30,
        "customer_consent_obtained": True,
    })
    assert rejected.status_code == 409, rejected.text
    assert snapshot() == before


def test_generic_multiservice_intake_reaches_every_notification(api, db, scenario):
    from e2e.scenarios import multi_booking, multi_services
    profile = {"industry": "Service business", "collect_vehicle_details": False, "intake_fields": [
        {"key": "location", "label": "Service address", "type": "text", "required": True},
    ]}
    api.post("/api/v1/portal/config", json={"business_profile": profile})
    services = multi_services(api, "split")
    result = multi_booking(api, scenario, services, intake_data_json='{"location":"12 Example Street"}')
    assert result["success"] is True, result
    rows = db("SELECT id, vehicle_id, intake_data FROM service_requests WHERE visit_group_id=%s", (result["visit_group_id"],))
    assert len(rows) == 2
    for row in rows:
        assert row["vehicle_id"] is None
        assert row["intake_data"] == {"location": "12 Example Street"}
        events = db("SELECT payload FROM outbox_notifications WHERE request_id=%s", (row["id"],))
        assert events
        assert all("Service address: 12 Example Street" in str(event["payload"]) for event in events)
