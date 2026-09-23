import unittest
import datetime
from unittest.mock import patch, MagicMock
from serviceBot.db.queries import (
    parse_preferred_date_and_time,
    check_availability,
    _generate_dynamic_slots
)

class TestTimeSlotChecking(unittest.TestCase):

    def test_parse_preferred_date_and_time_iso(self):
        iso_date, window, start_ts = parse_preferred_date_and_time("2026-08-06")
        self.assertEqual(iso_date, "2026-08-06")
        self.assertIsNone(window)
        self.assertEqual(start_ts, "2026-08-06 00:00:00")

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

if __name__ == "__main__":
    unittest.main()
