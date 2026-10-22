# Quickstart & Verification Guide

## Testing

### Fast Unit & Integration Tests
Run unit tests for business profile, portal APIs, staff validation, and SMS acknowledgment:
```bash
pytest tests/test_business_profile.py tests/test_portal_config.py tests/test_staff_agent_validation.py tests/test_sms_acknowledgment.py -v
```

### Browser E2E Tests
Run browser tests using Chromium and disposable test database:
```bash
pytest e2e/test_business_neutral_portal.py e2e/test_business_profile.py -v
```

### Full Verification
Run the complete offline test suite:
```bash
./run_tests.sh --verify
```

## Manual Verification Workflow
1. Navigate to `#config/business` in the portal.
2. Edit Business Address, Google Maps URL, Timezone, and Support Helpline.
3. Add repeatable intake fields (e.g., Asset type, Serial number, Model).
4. Click Save Business Settings -> Verify confirmation dialog opens.
5. Click Cancel -> Verify no changes saved.
6. Click Save Business Settings -> Confirm -> Verify save message and separate voice provider status.
7. Open Service Requests modal -> Verify date picker, availability check, and returned slots dropdown.
8. Check Services Catalogue -> Verify seed button is gone, redesigned add/edit forms, and Asset Details summary.
9. Open SMS Inbox -> Verify Appointment Context sidebar is removed and chat area is expanded.
10. Check Admin Config -> Verify Connection Help is hidden.
11. Navigate to `#config/voice-settings` -> Verify fallback to Business Settings.
