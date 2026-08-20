import pytest
from playwright.sync_api import sync_playwright
import threading
import time
import uvicorn
from serviceBot.main import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="critical")

@pytest.fixture(scope="module", autouse=True)
def start_server():
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)  # Wait for server to start

def test_save_new_service_request_with_booking_time_dom():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://127.0.0.1:8003/portal/")
        
        # Click the "+ New Request" button on the dashboard
        page.wait_for_selector("#btn-new-request", state="visible")
        page.click("#btn-new-request")
        
        # Wait for Service Request form modal to appear
        page.wait_for_selector("#sr-form", state="visible")

        # Fill Customer & Vehicle Form details
        page.fill("#sr-cust-name", "Jane Smith")
        page.fill("#sr-cust-phone", "+19876543210")
        page.fill("#sr-veh-make", "Ford")
        page.fill("#sr-veh-model", "Mustang")
        page.fill("#sr-veh-year", "2022")
        page.fill("#sr-veh-vin", "1FA6P8CF0R5100000")
        page.select_option("#sr-service-type", "Oil Change")
        page.fill("#sr-issue-desc", "Regular oil change and tire inspection")
        
        # Fill Booking Time slot
        page.fill("#sr-booking-time", "2026-08-10T10:00")
        
        # Click Save Request button
        page.click("#sr-save-btn")
        
        # Wait for confirmation modal
        page.wait_for_selector("#confirm-modal", state="visible")
        
        # Confirm submission
        page.click("#confirm-modal-yes")
        
        # Wait for response processing
        time.sleep(1)
        
        # Verify success toast appears
        toast = page.locator("#app-toast")
        toast_text = toast.inner_text()
        print("TOAST TEXT:", toast_text)
        assert "successfully" in toast_text.lower()

        browser.close()
