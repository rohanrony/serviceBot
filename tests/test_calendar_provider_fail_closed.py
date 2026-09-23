"""Provider-failure contract for local calendar population."""

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.services.calendar_availability import CalendarAvailabilityService


def test_provider_failure_blocks_populated_slots_instead_of_marking_them_available():
    service = CalendarAvailabilityService(fetch_events=lambda *_args: None)

    result = service.populate_agent(1, days=7, hours=[10])

    assert result["provider_available"] is False
    assert result["free_estimate"] == 0

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT reservation_status, is_booked, calendar_integration_status
                FROM mock_calendar_slots
                WHERE staff_agent_id = 1
                  AND calendar_integration_status = 'FAILED';
                """
            )
            failed_slots = cursor.fetchall()
            cursor.execute(
                """
                DELETE FROM mock_calendar_slots
                WHERE staff_agent_id = 1
                  AND calendar_integration_status = 'FAILED';
                """
            )

    assert failed_slots
    assert all(slot["reservation_status"] == "BLOCKED" for slot in failed_slots)
    assert all(slot["is_booked"] is True for slot in failed_slots)
