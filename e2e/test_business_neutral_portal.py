import re
import pytest
from playwright.sync_api import expect


def test_business_settings_inputs_and_notifications_removal(page, live_server):
    """US1/AC1: Business Address, Maps Link, Time Zone, and Support Helpline in Business Settings, removed from Notifications."""
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    # Verify canonical inputs exist in Business Settings form
    expect(page.locator("#business-address")).to_be_visible()
    expect(page.locator("#business-maps-url")).to_be_visible()
    expect(page.locator("#business-timezone")).to_be_visible()
    expect(page.locator("#business-support-phone")).to_be_visible()

    # Navigate to Notifications Config
    page.goto(f"{live_server}/portal/#config/sms-config")
    expect(page.locator("#sms-config-view")).to_be_visible()

    # Verify these inputs are REMOVED from Notifications form
    expect(page.locator("#sms-config-shop-address")).not_to_be_attached()
    expect(page.locator("#sms-config-maps-url")).not_to_be_attached()
    expect(page.locator("#sms-config-timezone")).not_to_be_attached()
    expect(page.locator("#sms-config-support-phone")).not_to_be_attached()


def test_save_confirmation_cancel_and_confirm_flow(page, live_server):
    """US1/AC2: Save confirmation modal explains prompt replacement; Cancel makes 0 writes, Confirm proceeds."""
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    # Verify removed checkboxes
    expect(page.locator("#business-collect-vehicle")).not_to_be_attached()
    expect(page.locator("#business-regenerate-prompt")).not_to_be_attached()

    # Click Save Business Settings
    page.locator("#business-profile-form button[type=submit]").click()

    # Verify confirmation dialog opens explaining prompt replacement
    modal = page.locator("#business-save-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("AI greeting and instructions will be replaced")

    # Click Cancel: modal closes, no write occurs
    requests = []
    page.on("request", lambda r: requests.append(r) if "/api/v1/portal/config" in r.url and r.method == "POST" else None)
    modal.locator("#business-save-cancel-btn").click()
    expect(modal).not_to_be_visible()
    assert len(requests) == 0, "Cancel must make zero write requests"

    # Click Save again and Confirm
    page.locator("#business-profile-form button[type=submit]").click()
    expect(modal).to_be_visible()
    with page.expect_response(lambda r: "/api/v1/portal/config" in r.url and r.request.method == "POST") as resp:
        modal.locator("#business-save-confirm-btn").click()
    assert resp.value.ok


def test_provider_sync_failure_displays_separate_notice(page, live_server):
    """US1/AC3: Report saved settings separately from voice-provider synchronization status."""
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    # Mock the config endpoint to return saved: true but provider_sync failed
    page.route("**/api/v1/portal/config", lambda route: (
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "saved": true, "provider_sync": {"status": "failed", "message": "ElevenLabs service unavailable"}}'
        ) if route.request.method == "POST" else route.continue_()
    ))

    page.locator("#business-profile-form button[type=submit]").click()
    modal = page.locator("#business-save-modal")
    expect(modal).to_be_visible()
    modal.locator("#business-save-confirm-btn").click()

    # Verify UI displays clear notice without claiming live agent was updated
    notice = page.locator("#business-sync-status-notice")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("ElevenLabs service unavailable")
    expect(notice).not_to_contain_text("Live voice agent updated successfully")


def test_legacy_automotive_fields_exposed_in_form(page, live_server, api):
    """US2/AC3: Expose legacy automotive fields as editable generic equivalents."""
    # Reset business profile to empty intake fields
    api.post("/api/v1/portal/config", json={"business_profile": {"industry": "Auto Service", "intake_fields": []}})

    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    # Expose legacy automotive fields as generic equivalents: Make (brand), Model (model), Year (general, number)
    labels = page.locator(".business-intake-row .intake-label")
    expect(labels.nth(0)).to_have_value("Make")
    expect(labels.nth(1)).to_have_value("Model")
    expect(labels.nth(2)).to_have_value("Year")

    detail_types = page.locator(".business-intake-row .intake-detail-type")
    expect(detail_types.nth(0)).to_have_value("brand")
    expect(detail_types.nth(1)).to_have_value("model")
    expect(detail_types.nth(2)).to_have_value("general")


def test_service_request_date_first_slot_selection(page, live_server):
    """US3/AC1: Service requests use date-first scheduling with date picker, availability check, and returned-slot selector."""
    page.goto(f"{live_server}/portal/#dashboard")
    page.locator("#btn-new-request, #new-sr-btn").click()
    expect(page.locator("#sr-modal")).to_be_visible()

    # Manual datetime-local input is replaced
    expect(page.locator("#sr-booking-time")).not_to_be_attached()

    # Date picker, check availability button, and slots dropdown are present
    expect(page.locator("#sr-booking-date")).to_be_visible()
    expect(page.locator("#sr-check-slots-btn")).to_be_visible()
    expect(page.locator("#sr-slots-dropdown")).to_be_attached()


def test_reschedule_consent_validation(page, live_server, db):
    """US3/AC2: Changing appointment time requires customer consent checkbox."""
    # Insert existing service request
    sr_rows = db("""
        INSERT INTO service_requests (
            customer_id, service_type, issue_description, status,
            booking_type, booking_time, duration_minutes, staff_agent_id
        ) VALUES (1, 'Brake Inspection', 'Squeaking brakes', 'confirmed', 'appointment', '2026-11-15 10:00:00', 60, 1)
        RETURNING id;
    """)
    sr_id = sr_rows[0]["id"]

    page.goto(f"{live_server}/portal/#dashboard")
    row = page.locator(f"#service-requests-list tr:has-text('Squeaking brakes')")
    expect(row).to_be_visible()
    row.locator(".edit-sr-btn").click()

    expect(page.locator("#sr-modal")).to_be_visible()
    expect(page.locator("#sr-consent-wrapper")).to_be_visible()
    consent_checkbox = page.locator("#sr-customer-consent-check")
    expect(consent_checkbox).to_be_visible()
    expect(consent_checkbox).not_to_be_checked()


def test_service_catalogue_redesign_and_asset_details(page, live_server):
    """US4/AC1: Remove seed button, redesign forms, replace automotive checkbox with Asset Details summary."""
    page.goto(f"{live_server}/portal/#services")
    expect(page.locator("#services-view")).to_be_visible()

    # Seed default services button removed
    expect(page.locator("#seed-default-services-btn")).not_to_be_attached()

    # Automotive details checkbox replaced with Asset Details summary
    expect(page.locator("#new-service-req-vehicle-details")).not_to_be_attached()
    expect(page.locator("#edit-service-req-vehicle-details")).not_to_be_attached()

    # Asset Details summary with link to business settings is visible
    expect(page.locator("#add-service-asset-details-summary")).to_be_visible()
    expect(page.locator("#add-service-asset-details-summary a[href='#config/business']")).to_be_visible()


def test_sms_inbox_expanded_without_context_sidebar(page, live_server):
    """US5/AC1: SMS Inbox Appointment Context sidebar removed and conversation area expanded."""
    page.goto(f"{live_server}/portal/#sms-inbox")
    expect(page.locator("#sms-inbox-view")).to_be_visible()

    # Appointment Context sidebar is removed
    expect(page.locator(".sms-context-col")).not_to_be_attached()
    expect(page.locator("#sms-context-details")).not_to_be_attached()


def test_admin_connection_help_hidden(page, live_server):
    """US5/AC2: Admin Configuration hides Connection Help card."""
    page.goto(f"{live_server}/portal/#config/gmail")
    expect(page.locator("#gmail-view")).to_be_visible()

    # Connection help card is hidden or not attached
    help_card = page.locator("#gmail-view .content-card").filter(has_text="Connection Help")
    expect(help_card).not_to_be_visible()


def test_voice_settings_hidden_and_routing_fallback(page, live_server):
    """US5/AC3: API Keys & Voice settings tab and pane are hidden; falls back to Business settings."""
    page.goto(f"{live_server}/portal/#config/business")
    expect(page.locator("#business-view")).to_be_visible()

    # Nav ribbon button is hidden / not attached
    expect(page.locator(".config-ribbon-item[data-subtab='keys']")).not_to_be_visible()
    expect(page.locator(".config-ribbon-item[data-subtab='voice-settings']")).not_to_be_visible()

    # Direct navigation to #config/voice-settings or #config/keys falls back to Business Settings
    page.goto(f"{live_server}/portal/#config/voice-settings")
    expect(page.locator("#business-view")).to_be_visible()

    page.goto(f"{live_server}/portal/#config/keys")
    expect(page.locator("#business-view")).to_be_visible()


def test_duplicate_whitelist_removed_from_notifications(page, live_server):
    """US5/AC4: Duplicate test phone whitelist section removed from Notifications subtab."""
    page.goto(f"{live_server}/portal/#config/sms-config")
    expect(page.locator("#sms-config-view")).to_be_visible()

    # Duplicate whitelist is removed
    expect(page.locator("#sms-whitelist-tbody")).not_to_be_attached()
    expect(page.locator("#add-whitelist-form")).not_to_be_attached()


def test_staff_add_form_validation(page, live_server):
    """US6/AC1: Add Staff Member form validates required email and phone in browser."""
    page.goto(f"{live_server}/portal/#config/staff")
    expect(page.locator("#staff-view")).to_be_visible()

    name_input = page.locator("#new-agent-name")
    email_input = page.locator("#new-agent-email")
    phone_input = page.locator("#new-agent-phone")

    expect(email_input).to_have_attribute("required", "")
    expect(phone_input).to_have_attribute("required", "")
