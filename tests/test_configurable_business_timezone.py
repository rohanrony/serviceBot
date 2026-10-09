"""
Test Suite: Configurable Business Time Zone Settings & System-Wide Timezone Linking
Feature: 005-configurable-business-timezone
"""

import datetime as dt_mod
import json
import zoneinfo
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from serviceBot.services import timezone_service


# ==============================================================================
# Phase 1: Centralized Timezone Service Tests (T002)
# ==============================================================================

def test_get_business_timezone_str_default():
    """When config has no business_timezone or default, return America/New_York."""
    with patch("serviceBot.services.timezone_service.load_config", return_value={}):
        assert timezone_service.get_business_timezone_str() == "America/New_York"


def test_get_business_timezone_str_configured():
    """When config has business_timezone, return that configured timezone."""
    with patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Chicago"}):
        assert timezone_service.get_business_timezone_str() == "America/Chicago"


def test_validate_timezone():
    """Ensure valid IANA timezones return True, invalid return False."""
    assert timezone_service.validate_timezone("America/New_York") is True
    assert timezone_service.validate_timezone("America/Chicago") is True
    assert timezone_service.validate_timezone("America/Los_Angeles") is True
    assert timezone_service.validate_timezone("UTC") is True
    assert timezone_service.validate_timezone("Europe/London") is True

    assert timezone_service.validate_timezone("Invalid/Timezone") is False
    assert timezone_service.validate_timezone("ET") is False
    assert timezone_service.validate_timezone("") is False
    assert timezone_service.validate_timezone(None) is False


def test_get_business_zoneinfo():
    """Verify get_business_zoneinfo returns the corresponding zoneinfo.ZoneInfo object."""
    with patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Denver"}):
        tz = timezone_service.get_business_zoneinfo()
        assert isinstance(tz, zoneinfo.ZoneInfo)
        assert tz.key == "America/Denver"


def test_dst_offset_dynamic_handling():
    """Verify dynamic offset handling between Summer (EDT, UTC-4) and Winter (EST, UTC-5)."""
    with patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/New_York"}):
        summer_dt = dt_mod.datetime(2026, 7, 15, 12, 0, 0)
        winter_dt = dt_mod.datetime(2026, 1, 15, 12, 0, 0)

        summer_tz = timezone_service.to_business_tz(summer_dt)
        winter_tz = timezone_service.to_business_tz(winter_dt)

        assert summer_tz.utcoffset() == dt_mod.timedelta(hours=-4)
        assert winter_tz.utcoffset() == dt_mod.timedelta(hours=-5)


def test_to_business_tz_and_to_utc():
    """Verify bidirectional conversions between business timezone and UTC."""
    with patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Chicago"}):
        # 12:00 UTC on July 15 is 07:00 CDT (UTC-5)
        utc_dt = dt_mod.datetime(2026, 7, 15, 12, 0, 0, tzinfo=dt_mod.timezone.utc)
        chicago_dt = timezone_service.to_business_tz(utc_dt)
        assert chicago_dt.hour == 7
        assert chicago_dt.minute == 0

        # Back to UTC
        back_to_utc = timezone_service.to_utc(chicago_dt)
        assert back_to_utc.hour == 12
        assert back_to_utc.tzinfo == dt_mod.timezone.utc


# ==============================================================================
# Phase 2: Configuration API & Settings Tests (T004)
# ==============================================================================

def test_api_config_endpoints_timezone():
    """Verify GET and POST /api/v1/portal/config handle business_timezone with IANA validation."""
    from serviceBot.main import app
    client = TestClient(app)

    # 1. GET /api/v1/portal/config returns business_timezone
    res = client.get("/api/v1/portal/config")
    assert res.status_code == 200
    data = res.json()
    assert "business_timezone" in data
    assert data["business_timezone"] in ("America/New_York", "America/Chicago", "America/Los_Angeles")

    # 2. POST /api/v1/portal/config with valid timezone
    with patch("serviceBot.api.portal.save_config") as mock_save, \
         patch("serviceBot.api.portal.sync_prompt_to_elevenlabs") as mock_sync:
        post_res = client.post("/api/v1/portal/config", json={"business_timezone": "America/Chicago"})
        assert post_res.status_code == 200
        mock_save.assert_called_once()
        saved_data = mock_save.call_args[0][0]
        assert saved_data["business_timezone"] == "America/Chicago"

    # 3. POST /api/v1/portal/config with invalid timezone returns 400
    bad_res = client.post("/api/v1/portal/config", json={"business_timezone": "Not/A_Real_Timezone"})
    assert bad_res.status_code == 400
    assert "invalid" in bad_res.json()["detail"].lower()


# ==============================================================================
# Phase 3: Availability & Booking Tests (T008)
# ==============================================================================

def test_availability_and_booking_timezone_linking():
    """Verify availability and booking logic respect the configured business timezone."""
    from serviceBot.services import calendar_availability, booking

    # When business timezone is America/Chicago
    with patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Chicago"}):
        # Parse slot in calendar availability
        parsed_slot = calendar_availability.parse_slot_datetime("2026-10-15 10:00:00")
        assert parsed_slot.hour == 10
        assert parsed_slot.minute == 0

        # Parse booking time in booking service
        parsed_booking = booking.parse_reservation_start("2026-10-15 14:30:00")
        assert parsed_booking.hour == 14
        assert parsed_booking.minute == 30


def test_lead_time_restriction_in_business_timezone():
    """Verify booking lead time checks use the current wall clock of the configured business timezone."""
    from serviceBot.services import booking

    # Mock time in business timezone as 9:00 AM Central
    mock_now = dt_mod.datetime(2026, 10, 15, 9, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Chicago"))
    with patch("serviceBot.services.timezone_service.now_in_business_tz", return_value=mock_now), \
         patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Chicago"}):
        
        # 11:00 AM Central on same day is only 2 hours ahead (< 4 hours buffer) -> should be invalid
        too_soon_slot = dt_mod.datetime(2026, 10, 15, 11, 0, 0)
        is_valid, earliest_allowed, _ = booking.validate_appointment_lead_time(too_soon_slot, min_buffer_hours=4.0)
        assert is_valid is False
        assert earliest_allowed == dt_mod.datetime(2026, 10, 15, 13, 0, 0)

        # 2:00 PM Central on same day is 5 hours ahead (> 4 hours buffer) -> should be valid
        valid_slot = dt_mod.datetime(2026, 10, 15, 14, 0, 0)
        is_valid_ok, _, _ = booking.validate_appointment_lead_time(valid_slot, min_buffer_hours=4.0)
        assert is_valid_ok is True


# ==============================================================================
# Phase 4: Quiet Hours & SMS Reminders Tests (T012)
# ==============================================================================

def test_quiet_hours_in_configured_timezone():
    """Verify quiet hours evaluates correctly against configured business timezone."""
    from serviceBot.services import quiet_hours

    # 10:30 PM (22:30) in Pacific Time
    # 22:30 is quiet hours (21:00 - 08:00)
    mock_now_pacific = dt_mod.datetime(2026, 10, 15, 22, 30, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"))

    with patch("serviceBot.services.timezone_service.now_in_business_tz", return_value=mock_now_pacific), \
         patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Los_Angeles"}):
        assert quiet_hours.is_in_quiet_hours(config={"quiet_hours_enabled": True, "quiet_start_time": "21:00", "quiet_end_time": "08:00"}) is True


def test_sms_reminders_current_business_time_uses_business_timezone():
    """Verify get_current_business_time returns current naive datetime in configured business timezone."""
    from serviceBot.services import sms_reminders

    mock_now = dt_mod.datetime(2026, 10, 15, 14, 15, 0, tzinfo=zoneinfo.ZoneInfo("America/Denver"))
    with patch("serviceBot.services.timezone_service.now_in_business_tz", return_value=mock_now), \
         patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Denver"}):
        now_naive = sms_reminders.get_current_business_time()
        assert now_naive.year == 2026
        assert now_naive.month == 10
        assert now_naive.day == 15
        assert now_naive.hour == 14
        assert now_naive.minute == 15
        assert now_naive.tzinfo is None


# ==============================================================================
# Phase 5: Additional Integration Tests (T011, T007, T016)
# ==============================================================================

def test_sms_config_put_updates_timezone():
    """Verify PUT /api/v1/portal/sms/config validates and persists business_timezone."""
    from serviceBot.main import app
    client = TestClient(app)

    with patch("serviceBot.api.portal.save_config") as mock_save, \
         patch("serviceBot.db.queries.update_sms_config", return_value={"business_timezone": "America/Phoenix"}), \
         patch("serviceBot.api.portal.sync_prompt_to_elevenlabs"):
        res = client.put("/api/v1/portal/sms/config", json={
            "business_timezone": "America/Phoenix",
            "support_phone_number": "555-0199"
        })
        assert res.status_code == 200
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["business_timezone"] == "America/Phoenix"

    # Invalid timezone rejected
    bad_res = client.put("/api/v1/portal/sms/config", json={
        "business_timezone": "Bad/Timezone"
    })
    assert bad_res.status_code == 400


def test_calendar_sync_tz_dynamic():
    """Verify calendar_sync.TZ dynamically delegates to timezone_service."""
    from serviceBot.services import calendar_sync

    with patch("serviceBot.services.timezone_service.load_config", return_value={"business_timezone": "America/Los_Angeles"}):
        dt = dt_mod.datetime(2026, 7, 15, 12, 0, 0, tzinfo=calendar_sync.TZ)
        assert dt.utcoffset() == dt_mod.timedelta(hours=-7)


def test_index_html_has_timezone_controls_and_badge():
    """Verify static index.html contains business timezone selector and header badge."""
    import pathlib
    html_path = pathlib.Path(__file__).parent.parent / "serviceBot" / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    assert 'id="sms-config-timezone"' in content
    assert 'id="business-tz-badge"' in content
    assert 'id="business-tz-badge-text"' in content

