"""Comprehensive browser-based acceptance testing for 013-business-neutral-portal.

Exercises the 5 specified browser journeys:
1. Business Settings (canonical values, prompt regeneration cancel zero-writes, reload persistence, provider sync failure reporting)
2. Scheduling (date-first slot selection, select & clear slot -> unscheduled, clear replacement -> preserves schedule & reservation, consent enforcement, availability failure handling)
3. Intake configuration (repeatable serial-number fields, required/optional, value types, legacy asset editability & historical preservation, empty intake remains empty)
4. Staff (valid profile with o'connor@example.com, reject malformed/leading-trailing hyphen/missing contacts without DB mutation, legacy incomplete profile edits)
5. Portal simplification (catalogue asset summaries & removed seed button, SMS inbox layout without context sidebar, hidden connection help, hidden voice settings / ribbon & fallback, notifications duplicate whitelist removed, console error check)
"""

import json
from datetime import timedelta
from playwright.sync_api import expect


def filter_js_errors(errors):
    """Filter out expected offline transport aborts (net::ERR_FAILED) and simulated HTTP status notices from actual JS runtime errors."""
    return [
        err for err in errors
        if "net::ERR_FAILED" not in err
        and "Failed to load resource: the server responded with a status of 503" not in err
    ]


def test_journey_1_business_settings(page, live_server, api, db):
    """Journey 1: Canonical business settings, prompt regeneration modal, reload persistence, and provider sync reporting."""
    console_errors = []
    page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))
    page.on("console", lambda msg: console_errors.append(f"CONSOLE: {msg.text}") if msg.type == "error" else None)

    # 1. Load Business Settings
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    # Verify canonical inputs exist
    addr_input = page.locator("#business-address")
    maps_input = page.locator("#business-maps-url")
    tz_input = page.locator("#business-timezone")
    phone_input = page.locator("#business-support-phone")

    expect(addr_input).to_be_visible()
    expect(maps_input).to_be_visible()
    expect(tz_input).to_be_visible()
    expect(phone_input).to_be_visible()

    # Verify canonical inputs are absent from Notifications subtab
    page.goto(f"{live_server}/portal/#config/sms-config")
    expect(page.locator("#sms-config-view")).to_be_visible()
    expect(page.locator("#sms-config-shop-address")).not_to_be_attached()
    expect(page.locator("#sms-config-maps-url")).not_to_be_attached()
    expect(page.locator("#sms-config-timezone")).not_to_be_attached()
    expect(page.locator("#sms-config-support-phone")).not_to_be_attached()

    # 2. Return to Business Settings, fill new values
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    page.locator("#business-name").fill("Apex Innovation Labs")
    page.locator("#business-industry").fill("Technology Consulting")
    addr_input.fill("742 Evergreen Terrace, Springfield, OR 97477")
    maps_input.fill("https://maps.google.com/?q=742+Evergreen+Terrace")
    tz_input.select_option("America/Chicago")
    phone_input.fill("+18005550199")

    # 3. Test Cancel prompt regeneration modal -> zero writes
    write_requests = []
    page.on("request", lambda r: write_requests.append(r) if "/api/v1/portal/config" in r.url and r.method == "POST" else None)

    page.locator("#business-profile-form button[type=submit]").click()
    modal = page.locator("#business-save-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("AI greeting and instructions will be replaced")

    modal.locator("#business-save-cancel-btn").click()
    expect(modal).not_to_be_visible()
    assert len(write_requests) == 0, "Cancel must perform zero write requests"

    # 4. Test Confirm & Save -> persists and reloads
    page.locator("#business-profile-form button[type=submit]").click()
    expect(modal).to_be_visible()
    with page.expect_response(lambda r: "/api/v1/portal/config" in r.url and r.request.method == "POST") as resp:
        modal.locator("#business-save-confirm-btn").click()
    assert resp.value.status == 200

    # Verify persisted in database and API
    sms_cfg = db("SELECT support_phone_number FROM sms_config LIMIT 1")[0]
    assert sms_cfg["support_phone_number"] == "+18005550199"
    portal_cfg = api.get("/api/v1/portal/config").json()
    assert portal_cfg["business_address"] == "742 Evergreen Terrace, Springfield, OR 97477"
    assert portal_cfg["google_maps_url"] == "https://maps.google.com/?q=742+Evergreen+Terrace"
    assert portal_cfg["business_timezone"] == "America/Chicago"

    # Reload and verify UI values persist
    page.reload()
    expect(page.locator("#business-view")).to_be_visible()
    expect(page.locator("#business-name")).to_have_value("Apex Innovation Labs")
    expect(page.locator("#business-address")).to_have_value("742 Evergreen Terrace, Springfield, OR 97477")
    expect(page.locator("#business-maps-url")).to_have_value("https://maps.google.com/?q=742+Evergreen+Terrace")
    expect(page.locator("#business-timezone")).to_have_value("America/Chicago")
    expect(page.locator("#business-support-phone")).to_have_value("+18005550199")

    # 5. Simulate provider synchronization failure
    page.route("**/api/v1/portal/config", lambda route: (
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "saved": true, "provider_sync": {"status": "failed", "message": "Voice provider timed out"}}'
        ) if route.request.method == "POST" else route.continue_()
    ))
    page.locator("#business-profile-form button[type=submit]").click()
    expect(modal).to_be_visible()
    modal.locator("#business-save-confirm-btn").click()

    notice = page.locator("#business-sync-status-notice")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Voice provider timed out")
    expect(notice).not_to_contain_text("synchronized successfully")

    page.screenshot(path="scratch/acceptance_evidence/journey1_business_settings.png", full_page=True)
    actual_js_errors = filter_js_errors(console_errors)
    assert len(actual_js_errors) == 0, f"Unexpected JS console errors in Journey 1: {actual_js_errors}"


def test_journey_2_scheduling(page, live_server, api, db, scenario):
    """Journey 2: Date-first scheduling, slot clearing, replacement preservation, consent and availability errors."""
    console_errors = []
    page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))
    page.on("console", lambda msg: console_errors.append(f"CONSOLE: {msg.text}") if msg.type == "error" else None)

    chosen_slot = scenario["start"].strftime("%Y-%m-%d %H:%M:%S")

    # Ensure neutral profile without vehicle requirements
    api.post("/api/v1/portal/config", json={
        "business_name": "Apex Innovation Labs",
        "business_profile": {"industry": "Engineering", "collect_vehicle_details": False, "intake_fields": []}
    })

    # 1. Create a scheduled request through date -> availability -> returned slot
    page.goto(f"{live_server}/portal/#dashboard")
    expect(page.locator("#dashboard-view")).to_be_visible()
    page.locator("#btn-new-request").click()
    expect(page.locator("#sr-modal")).to_be_visible()

    # Assert datetime-local is gone, date picker and check availability exist
    expect(page.locator("#sr-booking-time")).not_to_be_attached()
    expect(page.locator("#sr-booking-date")).to_be_visible()
    expect(page.locator("#sr-check-slots-btn")).to_be_visible()

    page.locator("#sr-cust-name").fill("Jordan Scheduled")
    page.locator("#sr-cust-phone").fill("5550199001")
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-issue-desc").fill("Check fluid levels and filters")
    page.locator("#sr-booking-date").fill(scenario["date"])
    page.locator("#sr-booking-date").dispatch_event("change")

    page.locator("#sr-check-slots-btn").click()
    slots = page.locator("#sr-slots-dropdown")
    expect(slots.locator("option")).not_to_have_count(1)
    slots.select_option(chosen_slot)

    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/portal/service-requests")) as sr_resp:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert sr_resp.value.status == 201
    sr1_rows = db(
        """SELECT sr.id FROM service_requests sr
           JOIN customers c ON c.id = sr.customer_id
           WHERE c.name = %s AND c.phone = %s""",
        ("Jordan Scheduled", "+15550199001"),
    )
    assert len(sr1_rows) == 1, "Browser-created scheduled request must be persisted once"
    sr1_id = sr1_rows[0]["id"]

    # Verify database state
    sr1_row = db("SELECT booking_time, booking_type FROM service_requests WHERE id = %s", (sr1_id,))[0]
    assert sr1_row["booking_time"] is not None
    assert sr1_row["booking_type"] == "appointment"
    res1 = db("SELECT starts_at FROM appointment_reservations WHERE service_request_id = %s AND status = 'ACTIVE'", (sr1_id,))
    assert len(res1) > 0, "Scheduled request must create an active reservation"

    # 2. Select a slot, clear it, then save -> verify unscheduled request and no reservation
    page.locator("#btn-new-request").click()
    expect(page.locator("#sr-modal")).to_be_visible()
    page.locator("#sr-cust-name").fill("Morgan Unscheduled")
    page.locator("#sr-cust-phone").fill("5550199002")
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-issue-desc").fill("Save without scheduled slot")
    page.locator("#sr-booking-date").fill(scenario["date"])
    page.locator("#sr-booking-date").dispatch_event("change")

    page.locator("#sr-check-slots-btn").click()
    expect(slots.locator("option")).not_to_have_count(1)
    slots.select_option(chosen_slot)
    # Clear the slot selection
    slots.select_option("")
    expect(slots).to_have_value("")

    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/portal/service-requests")) as sr_resp2:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert sr_resp2.value.status == 201
    sr2_rows = db(
        """SELECT sr.id FROM service_requests sr
           JOIN customers c ON c.id = sr.customer_id
           WHERE c.name = %s AND c.phone = %s""",
        ("Morgan Unscheduled", "+15550199002"),
    )
    assert len(sr2_rows) == 1, "Browser-created unscheduled request must be persisted once"
    sr2_id = sr2_rows[0]["id"]

    # Verify DB: booking_time IS NULL and 0 reservations
    sr2_row = db("SELECT booking_time FROM service_requests WHERE id = %s", (sr2_id,))[0]
    assert sr2_row["booking_time"] is None, "Cleared slot must persist as unscheduled (NULL booking_time)"
    res2 = db("SELECT starts_at FROM appointment_reservations WHERE service_request_id = %s AND status = 'ACTIVE'", (sr2_id,))
    assert len(res2) == 0, "Unscheduled request must have no active reservation"

    # 3. Select and clear a replacement on an existing appointment: verify original schedule and reservation unchanged
    orig_time_str = str(sr1_row["booking_time"])
    row_el = page.locator(f"#service-requests-list tr:has-text('Jordan Scheduled')")
    expect(row_el).to_be_visible()
    row_el.locator(".edit-sr-btn").click()
    expect(page.locator("#sr-modal")).to_be_visible()

    page.locator("#sr-check-slots-btn").click()
    expect(slots.locator("option")).not_to_have_count(1)
    all_values = slots.locator("option").evaluate_all("opts => opts.map(o => o.value).filter(v => v)")
    replacement_slot = [v for v in all_values if v != chosen_slot][0]
    slots.select_option(replacement_slot)
    # Now clear replacement selection
    slots.select_option("")
    expect(slots).to_have_value("")

    page.locator("#sr-issue-desc").fill("Preserve original appointment schedule")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith(f"/service-requests/{sr1_id}")) as edit_resp:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert edit_resp.value.status == 200

    sr1_recheck = db("SELECT booking_time, issue_description FROM service_requests WHERE id = %s", (sr1_id,))[0]
    assert str(sr1_recheck["booking_time"])[:19] == orig_time_str[:19], "Original schedule must remain preserved"
    assert sr1_recheck["issue_description"] == "Preserve original appointment schedule"
    res1_recheck = db("SELECT starts_at FROM appointment_reservations WHERE service_request_id = %s AND status = 'ACTIVE'", (sr1_id,))
    assert len(res1_recheck) > 0, "Original reservation must remain active"

    # 4. Verify rescheduling requires consent
    row_el.locator(".edit-sr-btn").click()
    expect(page.locator("#sr-modal")).to_be_visible()
    page.locator("#sr-check-slots-btn").click()
    expect(slots.locator("option")).not_to_have_count(1)
    slots.select_option(replacement_slot)

    # Consent wrapper must be visible
    expect(page.locator("#sr-consent-wrapper")).to_be_visible()
    consent_cb = page.locator("#sr-customer-consent-check")
    expect(consent_cb).to_be_visible()
    expect(consent_cb).not_to_be_checked()

    # Try saving without consent -> client validation blocks submission
    page.locator("#sr-save-btn").click()
    expect(page.locator("#confirm-modal")).not_to_be_visible()

    # Now check consent and save
    consent_cb.check()
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith(f"/service-requests/{sr1_id}")) as reschedule_resp:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert reschedule_resp.value.status == 200
    assert str(db("SELECT booking_time FROM service_requests WHERE id = %s", (sr1_id,))[0]["booking_time"])[:19] == replacement_slot

    # 5. Conflicting bookings and failed/stale availability responses cannot save incorrect time
    page.route("**/api/v1/portal/available-slots?*", lambda route: route.fulfill(
        status=503,
        json={"detail": {"error_code": "AVAILABILITY_UNKNOWN", "availability_status": "unknown", "retryable": True, "message": "Cannot verify availability"}}
    ))
    row_el.locator(".edit-sr-btn").click()
    expect(page.locator("#sr-modal")).to_be_visible()
    page.locator("#sr-check-slots-btn").click()

    expect(slots).to_contain_text("could not be verified")
    expect(slots).to_have_value("")

    page.screenshot(path="scratch/acceptance_evidence/journey2_scheduling.png", full_page=True)
    actual_js_errors = filter_js_errors(console_errors)
    assert len(actual_js_errors) == 0, f"Unexpected JS console errors in Journey 2: {actual_js_errors}"


def test_journey_3_intake_configuration(page, live_server, api, db):
    """Journey 3: Repeatable serial-number fields, required/optional settings, value types, legacy preservation, empty intake."""
    console_errors = []
    page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))
    page.on("console", lambda msg: console_errors.append(f"CONSOLE: {msg.text}") if msg.type == "error" else None)

    # Reset to neutral profile with no default fields
    api.post("/api/v1/portal/config", json={
        "business_name": "Apex Innovation Labs",
        "business_profile": {"industry": "Engineering", "collect_vehicle_details": False, "intake_fields": []}
    })

    # 1. Configure repeatable serial-number fields, types, and requirements
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    # Add 2 serial-number fields with independent labels and required settings
    page.locator("#add-intake-field").click()
    row1 = page.locator(".business-intake-row").last
    row1.locator(".intake-detail-type").select_option("serial_number")
    row1.locator(".intake-label").fill("Primary Serial Number")
    row1.locator(".intake-required").check()

    page.locator("#add-intake-field").click()
    row2 = page.locator(".business-intake-row").last
    row2.locator(".intake-detail-type").select_option("serial_number")
    row2.locator(".intake-label").fill("Secondary Serial Number")
    row2.locator(".intake-required").uncheck()

    # Add brand and model fields
    page.locator("#add-intake-field").click()
    row3 = page.locator(".business-intake-row").last
    row3.locator(".intake-detail-type").select_option("brand")
    row3.locator(".intake-label").fill("Device Brand")

    page.locator("#add-intake-field").click()
    row4 = page.locator(".business-intake-row").last
    row4.locator(".intake-detail-type").select_option("general")
    row4.locator(".intake-type").select_option("number")
    row4.locator(".intake-label").fill("Hours Operated")

    page.locator("#business-profile-form button[type=submit]").click()
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/portal/config")) as save_resp:
        page.locator("#business-save-confirm-btn").click()
    assert save_resp.value.status == 200

    # Reload and verify all fields survived reload
    page.reload()
    expect(page.locator("#business-view")).to_be_visible()
    intake_rows = page.locator(".business-intake-row")
    expect(intake_rows).to_have_count(4)

    # 2. Create service request with custom generic intake data from browser
    page.goto(f"{live_server}/portal/#dashboard")
    page.locator("#btn-new-request").click()
    expect(page.locator("#sr-modal")).to_be_visible()
    expect(page.locator("#sr-vehicle-section")).not_to_be_visible()

    page.locator("#sr-cust-name").fill("Industrial Client")
    page.locator("#sr-cust-phone").fill("5550188999")
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-issue-desc").fill("Turbine overhaul")

    page.locator('[data-intake-key="primary_serial_number"]').fill("SN-TURB-001")
    page.locator('[data-intake-key="secondary_serial_number"]').fill("SN-GEN-002")
    page.locator('[data-intake-key="device_brand"]').fill("Siemens Energy")
    page.locator('[data-intake-key="hours_operated"]').fill("4500")

    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/portal/service-requests")) as sr_resp:
        page.locator("#sr-save-btn").click()
        page.locator("#confirm-modal-yes").click()
    assert sr_resp.value.status == 201
    sr_rows = db(
        """SELECT sr.id FROM service_requests sr
           JOIN customers c ON c.id = sr.customer_id
           WHERE c.name = %s AND c.phone = %s""",
        ("Industrial Client", "+15550188999"),
    )
    assert len(sr_rows) == 1, "Browser-created intake request must be persisted once"
    sr_id = sr_rows[0]["id"]

    # Verify database: intake values in JSONB, vehicle_id is NULL
    record = db("SELECT vehicle_id, intake_data FROM service_requests WHERE id = %s", (sr_id,))[0]
    assert record["vehicle_id"] is None, "Generic request must NOT fabricate a vehicle record"
    assert record["intake_data"] == {
        "primary_serial_number": "SN-TURB-001",
        "secondary_serial_number": "SN-GEN-002",
        "device_brand": "Siemens Energy",
        "hours_operated": 4500
    }

    # 3. Verify legacy asset values remain editable and historical values survive
    # Changing business intake configuration does not wipe historical service request intake data
    api.post("/api/v1/portal/config", json={
        "business_profile": {
            "industry": "Renewable Power",
            "collect_vehicle_details": False,
            "intake_fields": [{"key": "grid_zone", "label": "Grid Zone", "type": "text", "required": True}]
        }
    })
    # Read service request again
    after_cfg_change = db("SELECT intake_data FROM service_requests WHERE id = %s", (sr_id,))[0]
    assert after_cfg_change["intake_data"]["primary_serial_number"] == "SN-TURB-001"

    # 4. Verify explicitly empty generic intake stays empty
    api.post("/api/v1/portal/config", json={
        "business_name": "Blank Intake Co",
        "business_profile": {"industry": "Advisory", "collect_vehicle_details": False, "intake_fields": []}
    })
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()
    expect(page.locator(".business-intake-row")).to_have_count(0)

    page.screenshot(path="scratch/acceptance_evidence/journey3_intake.png", full_page=True)
    actual_js_errors = filter_js_errors(console_errors)
    assert len(actual_js_errors) == 0, f"Unexpected JS console errors in Journey 3: {actual_js_errors}"


def test_journey_4_staff(page, live_server, api, db):
    """Journey 4: Staff profiles, o'connor@example.com, reject malformed/hyphens/missing, DB safety, legacy edits."""
    console_errors = []
    page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))
    page.on("console", lambda msg: console_errors.append(f"CONSOLE: {msg.text}") if msg.type == "error" else None)

    # 1. Create valid staff profile with o'connor@example.com
    page.goto(f"{live_server}/portal/#config/staff")
    expect(page.locator("#staff-view")).to_be_visible()

    page.locator("#new-agent-name").fill("Eileen O'Connor")
    page.locator("#new-agent-role").fill("Lead Advisor")
    page.locator("#new-agent-email").fill("o'connor@example.com")
    page.locator("#new-agent-phone").fill("+15559876543")

    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/portal/agents")) as add_resp:
        page.locator("#add-agent-form button[type=submit]").click()
    assert add_resp.value.status == 201
    agent_rows = db(
        """SELECT id FROM staff_agents
           WHERE name = %s AND email = %s AND phone_number = %s""",
        ("Eileen O'Connor", "o'connor@example.com", "+15559876543"),
    )
    assert len(agent_rows) == 1, "Browser-created staff profile must be persisted once"
    agent_id = agent_rows[0]["id"]

    # Verify persisted in database
    staff_row = db("SELECT name, email, phone_number FROM staff_agents WHERE id = %s", (agent_id,))[0]
    assert staff_row["name"] == "Eileen O'Connor"
    assert staff_row["email"] == "o'connor@example.com"
    assert staff_row["phone_number"] == "+15559876543"

    # 2. Reject malformed emails, leading/trailing domain hyphens, and missing required contacts
    # Verify rejected submissions leave persisted database state completely unchanged
    invalid_cases = [
        {"name": "Hyphen Left", "email": "staff@-example.com", "phone_number": "+15550100011"},
        {"name": "Hyphen Right", "email": "staff@example-.com", "phone_number": "+15550100012"},
        {"name": "Malformed At", "email": "invalid@@example.com", "phone_number": "+15550100013"},
        {"name": "No Domain Dot", "email": "user@example", "phone_number": "+15550100014"},
        {"name": "Empty Phone", "email": "user@example.com", "phone_number": ""},
        {"name": "Empty Email", "email": "", "phone_number": "+15550100015"},
    ]
    for case in invalid_cases:
        res = api.post("/api/v1/portal/agents", json={
            "name": case["name"], "role": "Advisor", "email": case["email"], "phone_number": case["phone_number"]
        })
        assert res.status_code in (400, 422), f"Expected rejection for {case}: got {res.status_code}"
        assert db("SELECT id FROM staff_agents WHERE name = %s", (case["name"],)) == [], "Rejected submission must not write to DB"

    # 3. Attempting to clear existing email or phone with empty string is rejected with 400
    res_clear_email = api.put(f"/api/v1/portal/agents/{agent_id}", json={"email": ""})
    assert res_clear_email.status_code == 400
    res_clear_phone = api.put(f"/api/v1/portal/agents/{agent_id}", json={"phone_number": ""})
    assert res_clear_phone.status_code == 400

    # Persisted record remains untouched
    eileen = db("SELECT email, phone_number FROM staff_agents WHERE id = %s", (agent_id,))[0]
    assert eileen["email"] == "o'connor@example.com"
    assert eileen["phone_number"] == "+15559876543"

    # 4. Verify unrelated edits still work on legacy incomplete profiles
    legacy_rows = db("""
        INSERT INTO staff_agents (name, role, email, phone_number, is_active)
        VALUES ('Legacy Incomplete Specialist', 'Specialist', NULL, NULL, TRUE)
        RETURNING id;
    """)
    legacy_id = legacy_rows[0]["id"]

    res_legacy_edit = api.put(f"/api/v1/portal/agents/{legacy_id}", json={"name": "Renamed Legacy Specialist"})
    assert res_legacy_edit.status_code == 200
    assert res_legacy_edit.json()["agent"]["name"] == "Renamed Legacy Specialist"
    assert db("SELECT name FROM staff_agents WHERE id = %s", (legacy_id,))[0]["name"] == "Renamed Legacy Specialist"

    page.screenshot(path="scratch/acceptance_evidence/journey4_staff.png", full_page=True)
    actual_js_errors = filter_js_errors(console_errors)
    assert len(actual_js_errors) == 0, f"Unexpected JS console errors in Journey 4: {actual_js_errors}"


def test_journey_5_portal_simplification(page, live_server, api):
    """Journey 5: Catalogue asset summaries, SMS inbox full-width layout, hidden controls & routing fallbacks."""
    console_errors = []
    page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))
    page.on("console", lambda msg: console_errors.append(f"CONSOLE: {msg.text}") if msg.type == "error" else None)

    # 1. Services Catalogue
    page.goto(f"{live_server}/portal/#services")
    expect(page.locator("#services-view")).to_be_visible()

    # Seed button removed
    expect(page.locator("#seed-default-services-btn")).not_to_be_attached()

    # Asset Details summary visible with link to Business Settings
    expect(page.locator("#add-service-asset-details-summary")).to_be_visible()
    expect(page.locator("#add-service-asset-details-summary a[href='#config/business']")).to_be_visible()

    # Automotive checkboxes absent
    expect(page.locator("#new-service-req-vehicle-details")).not_to_be_attached()
    expect(page.locator("#edit-service-req-vehicle-details")).not_to_be_attached()

    # 2. SMS Inbox layout
    page.goto(f"{live_server}/portal/#sms-inbox")
    expect(page.locator("#sms-inbox-view")).to_be_visible()

    # Context sidebar removed
    expect(page.locator(".sms-context-col")).not_to_be_attached()
    expect(page.locator("#sms-context-details")).not_to_be_attached()

    # 3. Admin Configuration: Connection Help hidden
    page.goto(f"{live_server}/portal/#config/gmail")
    expect(page.locator("#gmail-view")).to_be_visible()
    help_card = page.locator("#gmail-view .content-card").filter(has_text="Connection Help")
    expect(help_card).not_to_be_visible()

    # 4. Navigation ribbon: API Keys & Voice hidden, fallback routing to Business
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()
    expect(page.locator(".config-ribbon-item[data-subtab='keys']")).not_to_be_visible()
    expect(page.locator(".config-ribbon-item[data-subtab='voice-settings']")).not_to_be_visible()

    page.goto(f"{live_server}/portal/#config/voice-settings")
    expect(page.locator("#business-view")).to_be_visible()

    page.goto(f"{live_server}/portal/#config/keys")
    expect(page.locator("#business-view")).to_be_visible()

    # 5. Notifications subtab: duplicate whitelist table removed
    page.goto(f"{live_server}/portal/#config/sms-config")
    expect(page.locator("#sms-config-view")).to_be_visible()
    expect(page.locator("#sms-whitelist-tbody")).not_to_be_attached()
    expect(page.locator("#add-whitelist-form")).not_to_be_attached()

    page.screenshot(path="scratch/acceptance_evidence/journey5_portal_simplification.png", full_page=True)
    actual_js_errors = filter_js_errors(console_errors)
    assert len(actual_js_errors) == 0, f"Unexpected JS console errors in Journey 5: {actual_js_errors}"
