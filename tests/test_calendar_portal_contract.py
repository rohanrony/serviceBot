"""Contract coverage for the staff calendar endpoints documented for the portal."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from serviceBot.main import app
from serviceBot.services.calendar_availability import CalendarConflictError


client = TestClient(app)


def test_calendar_routes_match_the_documented_contract():
    slot = {
        "id": 7,
        "slot_datetime": "2026-10-15 09:30:00",
        "is_booked": False,
        "staff_agent_id": 1,
        "reservation_status": "AVAILABLE",
        "calendar_integration_status": "NOT_REQUIRED",
    }

    with patch("serviceBot.api.portal.CalendarAvailabilityService") as service_class:
        service = service_class.return_value
        service.list_slots.return_value = [slot]
        service.create_slot.return_value = slot
        service.update_slot.return_value = {**slot, "is_booked": True}
        service.populate_agent.return_value = {
            "agent_id": 1,
            "slots_created": 4,
            "slots_blocked_by_calendar": 1,
            "total_candidates": 5,
            "free_estimate": 4,
        }
        service.sync_all.return_value = {
            "agents_synced": ["Test Agent"],
            "total_new_slots": 4,
            "details": {"Test Agent": service.populate_agent.return_value},
        }

        assert client.get("/api/v1/portal/agents/1/calendar").json() == [slot]

        created = client.post(
            "/api/v1/portal/agents/1/calendar",
            json={"slot_datetime": "2026-10-15T09:30:00", "is_booked": False},
        )
        assert created.status_code == 201
        assert created.json()["success"] is True

        updated = client.patch("/api/v1/portal/calendar/7", json={"is_booked": True})
        assert updated.status_code == 200
        assert updated.json()["is_booked"] is True

        populated = client.post("/api/v1/portal/agents/1/calendar/populate", json={"days": 1, "hours": [9]})
        assert populated.status_code == 200
        assert populated.json()["success"] is True

        synced = client.post("/api/v1/portal/calendar/sync-all?days=1")
        assert synced.status_code == 200
        assert synced.json()["agents_synced"] == ["Test Agent"]


def test_reserved_calendar_slot_cannot_be_reopened_or_deleted():
    with patch("serviceBot.api.portal.CalendarAvailabilityService") as service_class:
        service = service_class.return_value
        service.update_slot.side_effect = CalendarConflictError("A reserved slot cannot be moved, reopened, or deleted.")
        service.delete_slot.side_effect = CalendarConflictError("A reserved slot cannot be deleted.")

        update = client.patch("/api/v1/portal/calendar/7", json={"is_booked": False})
        delete = client.delete("/api/v1/portal/calendar/7")

    assert update.status_code == 409
    assert delete.status_code == 409

