import pytest
import asyncio
from unittest.mock import patch, MagicMock

from serviceBot.db.queries import check_availability
from serviceBot.services.calendar_sync import get_configured_business_hours, _generate_slot_strings
from serviceBot.api.telephony import voice_tools, inbound_call

def test_check_availability_evening_slots():
    """Verify check_availability respects business_hours_end from config for evening slots."""
    fake_config = {
        "business_hours_start": 7,
        "business_hours_end": 21,
        "business_hours": list(range(7, 21))
    }
    
    with patch("serviceBot.api.portal.load_config", return_value=fake_config):
        from serviceBot.db.queries import _generate_dynamic_slots
        slots = _generate_dynamic_slots("2026-08-10 evening", 60)
        # 19:00:00 should be generated because business_hours_end is 21
        assert any("19:00:00" in slot for slot in slots)

def test_calendar_sync_generates_evening_hours():
    """Verify calendar_sync generates slots up to 20:00 when business_hours_end is 21."""
    fake_config = {
        "business_hours_start": 7,
        "business_hours_end": 21
    }
    with patch("serviceBot.api.portal.load_config", return_value=fake_config):
        hours = get_configured_business_hours()
        assert 18 in hours
        assert 19 in hours
        assert 20 in hours
        assert 21 not in hours
        
        slots = _generate_slot_strings(days=1, hours=hours)
        assert any(" 18:00:00" in s for s in slots)
        assert any(" 19:00:00" in s for s in slots)
        assert any(" 19:30:00" in s for s in slots)

def test_book_appointment_vehicle_override_prevention():
    """Verify book_appointment does not overwrite explicit vehicle make with old DB values."""
    async def run_test():
        c_data = {
            "customer_id": 1,
            "name": "Jane Doe",
            "make": "Kia",
            "model": "Forte",
            "year": 2018,
            "open_sr_id": None
        }
        
        payload = {
            "tool_call_id": "call_123",
            "name": "book_appointment",
            "arguments": {
                "phone": "5551234567",
                "appointment_datetime": "2026-08-10 10:00:00",
                "service_type": "Repair",
                "make": "BMW",
                "model": "M3"
            }
        }
        
        with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value=c_data), \
             patch("serviceBot.api.telephony.clean_and_validate_phone", return_value="+15551234567"), \
             patch("serviceBot.api.telephony.update_customer_name"), \
             patch("serviceBot.api.telephony.book_appointment") as mock_book, \
             patch("serviceBot.api.telephony.get_service_required_fields", return_value={"price_range": "$100"}), \
             patch("serviceBot.api.telephony.get_booking_details", return_value={}):
            
            mock_book.return_value = 42
            
            await voice_tools(payload)
            
            mock_book.assert_called_once()
            _, kwargs = mock_book.call_args
            assert kwargs["vehicle_details"]["make"] == "BMW"
            assert kwargs["vehicle_details"]["model"] == "M3"

    asyncio.run(run_test())

def test_create_service_request_vehicle_preservation():
    """Verify create_service_request preserves explicit make (BMW) when model is not specified."""
    async def run_test():
        c_data = {
            "customer_id": 1,
            "name": "Jane Doe",
            "make": "Kia",
            "model": "Forte",
            "year": 2018,
            "open_sr_id": None
        }
        
        payload = {
            "tool_call_id": "call_456",
            "name": "create_service_request",
            "arguments": {
                "phone": "5551234567",
                "make": "BMW",
                "issue_description": "Engine Check Light"
            }
        }
        
        with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value=c_data), \
             patch("serviceBot.api.telephony.clean_and_validate_phone", return_value="+15551234567"), \
             patch("serviceBot.api.telephony.update_customer_name"), \
             patch("serviceBot.api.telephony.create_service_request") as mock_create_sr, \
             patch("serviceBot.api.telephony.get_service_required_fields", return_value={"price_range": "$100"}), \
             patch("serviceBot.api.telephony.get_booking_details", return_value={}):
            
            mock_create_sr.return_value = 99
            
            await voice_tools(payload)
            
            mock_create_sr.assert_called_once()
            _, kwargs = mock_create_sr.call_args
            assert kwargs["vehicle_details"]["make"] == "BMW"
            assert kwargs["vehicle_details"]["model"] == "Standard"

    asyncio.run(run_test())

def test_inbound_call_passes_recent_booking_context():
    """Verify inbound_call passes recent_booking_context in TWiML parameters when customer exists."""
    async def run_test():
        c_data = {
            "customer_id": 1,
            "name": "Jane Doe",
            "phone": "+15551234567",
            "open_sr_type": "Oil Change"
        }
        
        appts = [
            {
                "id": 10,
                "service_type": "Oil Change",
                "appointment_datetime": "2026-07-01 10:00:00",
                "make": "Kia",
                "model": "Forte",
                "year": 2018
            }
        ]
        
        fake_form_data = {"From": "+15551234567"}
        fake_request = MagicMock()
        
        async def mock_form():
            return fake_form_data
        
        fake_request.form = mock_form
        
        with patch("serviceBot.db.queries.lookup_customer_by_phone", return_value=c_data), \
             patch("serviceBot.db.queries.get_customer_appointments", return_value=appts):
            
            response = await inbound_call(fake_request)
            content = response.body.decode("utf-8")
            assert "recent_booking_context" in content
            assert "Kia" in content or "Oil Change" in content

    asyncio.run(run_test())
