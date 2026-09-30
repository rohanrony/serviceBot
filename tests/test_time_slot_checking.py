import unittest
import datetime
from unittest.mock import patch, MagicMock
from serviceBot.db.queries import (
    parse_preferred_date_and_time,
    parse_specific_time,
    check_availability,
    _generate_dynamic_slots,
    is_phone_whitelisted,
    is_agent_whatsapp_connected
)

class TestTimeSlotChecking(unittest.TestCase):

    def test_parse_specific_time_formats(self):
        self.assertEqual(parse_specific_time("2026-08-06 10:00 AM"), datetime.time(10, 0))
        self.assertEqual(parse_specific_time("August 6 at 2:30 PM"), datetime.time(14, 30))
        self.assertEqual(parse_specific_time("at 10"), datetime.time(10, 0))
        self.assertEqual(parse_specific_time("at 2"), datetime.time(14, 0))
        self.assertEqual(parse_specific_time("noon"), datetime.time(12, 0))
        self.assertEqual(parse_specific_time("14:00"), datetime.time(14, 0))
        self.assertIsNone(parse_specific_time("2026-08-06 afternoon"))
        self.assertIsNone(parse_specific_time("morning"))
        self.assertIsNone(parse_specific_time(None))

    def test_parse_preferred_date_and_time_iso(self):
        iso_date, window, start_ts = parse_preferred_date_and_time("2026-08-06")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertIsNone(window)
        self.assertEqual(start_ts, "2026-08-06 00:00:00")

    def test_parse_preferred_date_and_time_specific_time(self):
        iso_date, window, start_ts = parse_preferred_date_and_time("2026-08-06 10:00 AM")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertEqual(window, "morning")
        self.assertEqual(start_ts, "2026-08-06 10:00:00")

        iso_date, window, start_ts = parse_preferred_date_and_time("2026-08-06 2:30 PM")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertEqual(window, "afternoon")
        self.assertEqual(start_ts, "2026-08-06 14:30:00")

        iso_date, window, start_ts = parse_preferred_date_and_time("2026-08-06 6:00 PM")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertEqual(window, "evening")
        self.assertEqual(start_ts, "2026-08-06 18:00:00")

    def test_parse_preferred_date_and_time_afternoon_text(self):
        iso_date, window, start_ts = parse_preferred_date_and_time("August 6 afternoon")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertEqual(window, "afternoon")
        self.assertEqual(start_ts, "2026-08-06 12:00:00")

    def test_parse_preferred_date_and_time_iso_afternoon(self):
        iso_date, window, start_ts = parse_preferred_date_and_time("2026-08-06 afternoon")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertEqual(window, "afternoon")
        self.assertEqual(start_ts, "2026-08-06 12:00:00")

    def test_parse_preferred_date_and_time_morning(self):
        iso_date, window, start_ts = parse_preferred_date_and_time("August 6th morning")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertEqual(window, "morning")
        self.assertEqual(start_ts, "2026-08-06 07:00:00")

    def test_parse_preferred_date_and_time_pm(self):
        iso_date, window, start_ts = parse_preferred_date_and_time("2026-08-06 PM")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertEqual(window, "afternoon")
        self.assertEqual(start_ts, "2026-08-06 12:00:00")

    def test_parse_preferred_date_and_time_none(self):
        iso_date, window, start_ts = parse_preferred_date_and_time(None)
        self.assertIsNone(iso_date)
        self.assertIsNone(window)
        self.assertEqual(start_ts, "1970-01-01 00:00:00")

    def test_generate_dynamic_slots_afternoon_filtering(self):
        slots = _generate_dynamic_slots(preferred_date_str="2026-08-06 afternoon", duration_minutes=60)
        self.assertTrue(len(slots) > 0)
        # All slots generated for the afternoon target date should be in afternoon
        first_date_slots = [s for s in slots if s.startswith("2026-08-06")]
        for s in first_date_slots:
            dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            self.assertGreaterEqual(dt.hour, 12)

    def test_check_availability_afternoon_returns_afternoon_slots(self):
        target_date = datetime.date.today() + datetime.timedelta(days=7)
        while target_date.weekday() > 4:
            target_date += datetime.timedelta(days=1)
        target_date_str = target_date.isoformat()

        with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_cursor.fetchall.return_value = [{"id": 1}]

            with patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
                mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
                with patch(
                    "serviceBot.services.google_calendar.fetch_agent_events",
                    return_value=[],
                ):
                    slots = check_availability(
                        preferred_date=f"{target_date_str} afternoon"
                    )

        self.assertGreater(len(slots), 0)
        for slot in slots:
            slot_dt = datetime.datetime.strptime(slot, "%Y-%m-%d %H:%M:%S")
            self.assertEqual(slot_dt.strftime("%Y-%m-%d"), target_date_str)
            self.assertGreaterEqual(slot_dt.hour, 12)
            self.assertLess(slot_dt.hour, 18)

    def test_check_availability_ranks_by_proximity_to_target_time(self):
        target_date = datetime.date.today() + datetime.timedelta(days=7)
        while target_date.weekday() > 4:
            target_date += datetime.timedelta(days=1)
        target_date_str = target_date.isoformat()

        with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_cursor.fetchall.return_value = [{"id": 1}]

            with patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
                mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
                with patch(
                    "serviceBot.services.google_calendar.fetch_agent_events",
                    return_value=[],
                ):
                    # Requesting 10:00 AM should return slots centered around 10:00 AM, NOT 7:00 AM
                    slots = check_availability(
                        preferred_date=f"{target_date_str} 10:00 AM"
                    )

        self.assertEqual(len(slots), 3)
        hours = [datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").hour for s in slots]
        # None of the slots should be 7:00 AM when 10:00 AM is requested
        self.assertNotIn(7, hours)
        # 10:00 AM should be included
        self.assertIn(10, hours)

    def test_is_phone_whitelisted_digit_normalization(self):
        # Whitelist has E.164 with country code: +14242704893
        mock_records = [{"phone_number": "+14242704893"}]
        with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_cursor.fetchall.return_value = mock_records

            with patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
                mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
                # 10-digit customer phone
                self.assertTrue(is_phone_whitelisted("4242704893"))
                # 11-digit phone
                self.assertTrue(is_phone_whitelisted("14242704893"))
                # E.164 format
                self.assertTrue(is_phone_whitelisted("+14242704893"))
                # WhatsApp URI prefix
                self.assertTrue(is_phone_whitelisted("whatsapp:+14242704893"))
                # Different number
                self.assertFalse(is_phone_whitelisted("4242704890"))

        # Whitelist has 10-digit number without country code: 4242704893
        mock_records_10 = [{"phone_number": "4242704893"}]
        with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_cursor.fetchall.return_value = mock_records_10

            with patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
                mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
                self.assertTrue(is_phone_whitelisted("+14242704893"))
                self.assertTrue(is_phone_whitelisted("4242704893"))
                self.assertFalse(is_phone_whitelisted("5551234567"))

    def test_is_agent_whatsapp_connected_normalization(self):
        mock_records = [{"phone_number": "+14242704893"}]
        with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_cursor.fetchall.return_value = mock_records

            with patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
                mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
                self.assertTrue(is_agent_whatsapp_connected("4242704893"))
                self.assertTrue(is_agent_whatsapp_connected("+14242704893"))
                self.assertFalse(is_agent_whatsapp_connected("4242704890"))

    @patch("serviceBot.api.telephony.check_availability")
    def test_telephony_tool_check_availability_message(self, mock_check):
        import asyncio
        from serviceBot.api.telephony import voice_tools
        mock_check.return_value = ["2026-08-06 09:30:00", "2026-08-06 10:00:00", "2026-08-06 10:30:00"]
        payload = {
            "name": "check_availability",
            "arguments": {"preferred_date": "2026-08-06 10:00 AM"}
        }
        res = asyncio.run(voice_tools(payload))
        self.assertTrue(res["result"]["success"])
        self.assertIn("Recommended available slots", res["result"]["message"])
        self.assertIn("NOTE TO AGENT", res["result"]["message"])
        self.assertIn("Never tell or imply to the caller that these are the only available slots", res["result"]["message"])

    def test_check_availability_with_separate_preferred_time_parameter(self):
        target_date = datetime.date.today() + datetime.timedelta(days=7)
        while target_date.weekday() > 4:
            target_date += datetime.timedelta(days=1)
        target_date_str = target_date.isoformat()

        with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_cursor.fetchall.return_value = [{"id": 1}]

            with patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
                mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
                with patch("serviceBot.services.google_calendar.fetch_agent_events", return_value=[]):
                    slots = check_availability(
                        preferred_date=target_date_str,
                        preferred_time="9:00 AM"
                    )

        self.assertEqual(len(slots), 3)
        hours = [datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").hour for s in slots]
        self.assertIn(9, hours)

    @patch("serviceBot.api.telephony.check_availability")
    def test_telephony_tool_check_availability_with_preferred_time(self, mock_check):
        import asyncio
        from serviceBot.api.telephony import voice_tools

        mock_check.return_value = ["2026-08-06 08:30:00", "2026-08-06 09:00:00", "2026-08-06 09:30:00"]
        payload = {
            "name": "check_availability",
            "arguments": {
                "preferred_date": "2026-08-06",
                "preferred_time": "9:00 AM"
            }
        }
        res = asyncio.run(voice_tools(payload))
        mock_check.assert_called_once_with(
            service_type=None,
            preferred_date="2026-08-06",
            booking_type="appointment",
            preferred_time="9:00 AM"
        )
        self.assertTrue(res["result"]["success"])
        self.assertIn("IS AVAILABLE", res["result"]["message"])
        self.assertIn("2026-08-06 09:00:00", res["result"]["available_slots"])

if __name__ == "__main__":
    unittest.main()

