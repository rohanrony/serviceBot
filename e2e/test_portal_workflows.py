"""Browser actions must produce observable results after backend read-back."""

import re

import pytest
from playwright.sync_api import expect

PORTAL = "/api/v1/portal"


def open_config(page, live_server, subtab):
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="config"]').click()
    page.locator(f'.config-ribbon-item[data-subtab="{subtab}"]').click()


def test_edit_request_saves_issue_and_vehicle_after_reload(page, live_server, api):
    page.goto(f"{live_server}/portal/")
    page.locator('.edit-sr-btn[data-id="1"]').click()
    page.locator("#sr-issue-desc").fill("Brake inspection requested")
    page.locator("#sr-veh-model").fill("Corolla")
    page.locator('#sr-form button[type="submit"]').click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    with page.expect_response(
        lambda r: r.request.method == "PUT" and r.url.endswith("/service-requests/1")
    ) as saved:
        page.locator("#confirm-modal-yes").click()
    assert saved.value.status == 200, saved.value.text()
    row = next(r for r in api.get(f"{PORTAL}/service-requests").json() if r["id"] == 1)
    assert row["issue_description"].lower() == "brake inspection requested"
    assert row["model"] == "Corolla"
    page.reload()
    expect(page.locator("#service-requests-list")).to_contain_text("Corolla")
    expect(page.locator("#service-requests-list")).to_contain_text(
        re.compile("brake inspection", re.IGNORECASE)
    )


def test_dismissed_status_confirmation_does_not_change_backend(page, live_server, api):
    page.goto(f"{live_server}/portal/")
    page.on("dialog", lambda dialog: dialog.dismiss())
    status = (
        page.locator("#service-requests-list tr")
        .filter(has_text="Alex E2E")
        .locator(".status-select-badge")
    )
    expect(status).to_have_value("pending")
    status.select_option("confirmed")
    expect(status).to_have_value("pending")
    assert api.get(f"{PORTAL}/service-requests").json()[0]["status"] == "pending"


def test_failed_status_save_restores_backend_value(page, live_server, api):
    page.goto(f"{live_server}/portal/")
    page.on("dialog", lambda dialog: dialog.accept())
    page.route(
        "**/service-requests/1/status",
        lambda route: route.fulfill(
            status=409, json={"detail": "Cannot change this request"}
        ),
    )
    status = page.locator("#service-requests-list .status-select-badge").first
    expect(status).to_have_value("pending")
    status.select_option("confirmed")
    expect(status).to_have_value("pending")
    assert api.get(f"{PORTAL}/service-requests").json()[0]["status"] == "pending"


def test_service_edit_delete_round_trip(page, live_server, api):
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="services"]').click()
    page.locator('.edit-service-btn[data-id="1"]').click()
    page.locator("#edit-service-name").fill("Premium Oil Change")
    page.locator("#edit-service-duration").fill("90")
    page.locator("#edit-service-req-location").uncheck()
    with page.expect_response(
        lambda r: r.request.method == "PUT" and r.url.endswith("/services/1")
    ) as saved:
        page.locator('#edit-service-form button[type="submit"]').click()
    assert saved.value.status == 200
    row = api.get(f"{PORTAL}/services").json()[0]
    assert row["name"] == "Premium Oil Change"
    assert row["duration_minutes"] == 90
    assert row["req_location"] is False
    page.reload()
    page.locator('.nav-item[data-tab="services"]').click()
    expect(page.locator("#services-list-body")).to_contain_text("Premium Oil Change")
    page.on("dialog", lambda dialog: dialog.accept())
    with page.expect_response(
        lambda r: r.request.method == "DELETE" and r.url.endswith("/services/1")
    ) as removed:
        page.locator('.delete-service-btn[data-id="1"]').click()
    assert removed.value.status == 200
    expect(page.locator('.delete-service-btn[data-id="1"]')).to_have_count(0)
    # The legacy GET automatically seeds defaults when the catalog is empty.
    assert all(
        s["id"] != 1 and s["name"] != "Premium Oil Change"
        for s in api.get(f"{PORTAL}/services").json()
    )


@pytest.mark.parametrize(
    "state,name,absent",
    [
        ("HANDOFF_REQUIRED", "Alex E2E", "Blair E2E"),
        ("IN_PROGRESS", "Blair E2E", "Alex E2E"),
        ("all", "Alex E2E", None),
    ],
)
def test_inbox_filter_changes_actual_threads(page, live_server, state, name, absent):
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="sms-inbox"]').click()
    with page.expect_response(
        lambda r: "/sms/conversations" in r.url and r.request.method == "GET"
    ):
        page.locator("#sms-thread-filter").select_option(state)
    expect(page.locator("#sms-threads-list")).to_contain_text(name)
    if absent:
        expect(page.locator("#sms-threads-list")).not_to_contain_text(absent)


def test_inbox_search_reply_and_resolve_persist(page, live_server, api):
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="sms-inbox"]').click()
    page.locator(".thread-item").filter(has_text="Alex E2E").click()
    expect(page.locator("#chat-messages-container")).to_contain_text(
        "Please help with my oil change"
    )
    page.locator(".quick-chip").first.click()
    expect(page.locator("#sms-reply-input")).not_to_have_value("")
    page.locator("#sms-reply-input").fill("Your technician will call shortly.")
    with page.expect_response(
        lambda r: r.url.endswith("/sms/reply") and r.request.method == "POST"
    ) as saved:
        page.locator("#send-sms-reply-btn").click()
    assert saved.value.status == 200
    assert saved.value.json()["dispatch"]["success"] is True
    messages = api.get(f"{PORTAL}/sms/conversations/1/messages").json()
    assert messages[-1]["body"] == "Your technician will call shortly."
    page.locator("#sms-thread-filter").select_option("IN_PROGRESS")
    page.locator(".thread-item").filter(has_text="Alex E2E").click()
    with page.expect_response(
        lambda r: r.url.endswith("/sms/resolve") and r.request.method == "POST"
    ) as resolved:
        page.locator("#mark-resolved-btn").click()
    assert resolved.value.json()["state"] == "AUTOMATED"
    page.reload()
    page.locator('.nav-item[data-tab="sms-inbox"]').click()
    page.locator("#sms-thread-filter").select_option("AUTOMATED")
    page.locator("#sms-thread-search-input").fill("Alex")
    expect(page.locator("#sms-threads-list .thread-item")).to_have_count(1)
    page.locator(".thread-item").filter(has_text="Alex E2E").click()
    expect(page.locator("#chat-messages-container")).to_contain_text(
        "Your technician will call shortly."
    )


def test_sms_global_configuration_survives_reload(page, live_server, api):
    open_config(page, live_server, "sms-config")
    expect(page.locator("#sms-config-support-phone")).to_have_value("+15550100005")
    page.locator("#sms-config-support-phone").fill("+15550100008")
    page.locator("#sms-config-auto-responder").fill("E2E team received your message.")
    with page.expect_response(
        lambda r: r.url.endswith("/sms/config") and r.request.method == "PUT"
    ) as saved:
        page.locator('#sms-global-config-form button[type="submit"]').click()
    assert saved.value.status == 200
    assert (
        api.get(f"{PORTAL}/sms/config").json()["support_phone_number"] == "+15550100008"
    )
    page.reload()
    page.locator('.nav-item[data-tab="config"]').click()
    page.locator('.config-ribbon-item[data-subtab="sms-config"]').click()
    expect(page.locator("#sms-config-support-phone")).to_have_value("+15550100008")
    expect(page.locator("#sms-config-auto-responder")).to_have_value(
        "E2E team received your message."
    )


def test_failed_matrix_save_must_not_announce_success(page, live_server, api):
    """Reimplementation gate: failed writes must be visible to the operator."""
    open_config(page, live_server, "sms-config")
    page.route(
        "**/sms/matrix-rules",
        lambda route: (
            route.fulfill(status=503, json={"detail": "Storage unavailable"})
            if route.request.method == "PUT"
            else route.continue_()
        ),
    )
    cb = page.locator(
        'input.sms-matrix-cb[data-event="BOOKING"][data-role="admin"]'
    ).first
    expect(cb).not_to_be_checked()
    with page.expect_response(
        lambda r: r.url.endswith("/sms/matrix-rules") and r.request.method == "PUT"
    ):
        cb.check()
    # Wait for the save handler's observable completion (success or failure toast).
    toast = page.locator(".toast").last
    expect(toast).to_be_visible()
    expect(toast).not_to_contain_text("Notification rule updated")
    rules = api.get(f"{PORTAL}/sms/matrix-rules").json()
    assert (
        next(
            r
            for r in rules
            if r["event_type"] == "BOOKING"
            and r["recipient_role"] == "admin"
            and r["channel"] == "SMS"
        )["enabled"]
        is False
    )


@pytest.mark.parametrize(
    "subtab",
    [
        "staff",
        "gmail",
        "sms-config",
        "customer-onboarding",
        "intents",
        "keys",
        "analytics",
    ],
)
def test_every_config_subtab_opens_its_own_pane(page, live_server, subtab):
    open_config(page, live_server, subtab)
    expect(page.locator(f'[data-subtab-pane="{subtab}"]')).to_be_visible()
    expect(page.locator(".config-subtab-pane.active")).to_have_count(1)


def test_knowledge_upload_preview_and_delete_through_browser(page, live_server, api):
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="knowledge"]').click()
    content = (
        "E2E warranty is twelve months. <script>window.e2eInjected = true</script>"
    )
    with page.expect_response(
        lambda r: r.url.endswith("/kb/upload") and r.request.method == "POST"
    ) as uploaded:
        page.locator("#kb-file-input").set_input_files(
            {
                "name": "browser-policy.txt",
                "mimeType": "text/plain",
                "buffer": content.encode(),
            }
        )
    assert uploaded.value.status == 200
    item = page.locator(".kb-file-item").filter(has_text="browser-policy.txt")
    expect(item).to_be_visible()
    item.locator(".view-kb-btn").click()
    expect(page.locator("#document-drawer-body")).to_have_text(content)
    assert page.evaluate("window.e2eInjected === undefined")
    page.reload()
    page.locator('.nav-item[data-tab="knowledge"]').click()
    page.on("dialog", lambda dialog: dialog.accept())
    with page.expect_response(
        lambda r: (
            r.url.endswith("/kb/browser-policy.txt") and r.request.method == "DELETE"
        )
    ) as deleted:
        item.locator(".delete-kb-btn").click()
    assert deleted.value.status == 200
    expect(item).to_have_count(0)
    assert api.get(f"{PORTAL}/kb/view/browser-policy.txt").status_code == 404


def test_new_request_form_creates_booking_after_confirmation(
    page, live_server, api, scenario
):
    page.goto(f"{live_server}/portal/")
    page.locator("#btn-new-request").click()
    page.locator("#sr-cust-name").fill("Portal E2E")
    page.locator("#sr-cust-phone").fill("+15550100010")
    page.locator("#sr-veh-make").fill("Honda")
    page.locator("#sr-veh-model").fill("Civic")
    page.locator("#sr-veh-year").fill("2021")
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-issue-desc").fill("Routine oil change")
    page.locator("#sr-booking-time").fill(scenario["start"].strftime("%Y-%m-%dT%H:%M"))
    page.locator("#sr-save-btn").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    with page.expect_response(
        lambda r: (
            r.url.endswith("/portal/service-requests") and r.request.method == "POST"
        )
    ) as saved:
        page.locator("#confirm-modal-yes").click()
    assert saved.value.status == 201, saved.value.text()
    request_id = saved.value.json()["request_id"]
    row = next(
        row
        for row in api.get(f"{PORTAL}/service-requests").json()
        if row["id"] == request_id
    )
    assert row["customer_name"] == "Portal E2E"
    assert row["booking_type"] == "appointment"
    assert row["booking_start_time"] == scenario["start"].strftime("%Y-%m-%d %H:%M:%S")
    page.reload()
    expect(page.locator("#service-requests-list")).to_contain_text("Portal E2E")
