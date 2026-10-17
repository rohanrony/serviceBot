"""Synthetic arrangements shared by recent-feature acceptance journeys."""

from e2e.test_voice_and_reporting import voice
from e2e.test_workflows import PORTAL


def service(api, name, agents, duration=30):
    response = api.post(
        f"{PORTAL}/services",
        json={
            "name": name,
            "description": "Synthetic acceptance service",
            "price_range": "$50",
            "duration_minutes": duration,
            "agent_ids": agents,
            "req_customer_name": True,
            "req_phone_number": True,
            "req_vehicle_details": True,
            "req_issue_description": False,
            "req_location": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def multi_services(api, mode="split"):
    tags = ([1], [1]) if mode == "single" else ([1], [2])
    service(api, "Brake Inspection", tags[0], 30)
    service(api, "Transmission Flush", tags[1], 45)
    return ["Brake Inspection", "Transmission Flush"]


def multi_booking(api, scenario, services, **changes):
    return voice(
        api,
        "book_appointment",
        {
            "phone": "+15550100001",
            "customer_name": "Alex E2E",
            "name": "Alex E2E",
            "make": "Toyota",
            "model": "Camry",
            "year": 2020,
            "appointment_datetime": scenario["start"].isoformat(),
            "service_type": ", ".join(services),
            "services": services,
            "issue_description": ", ".join(services),
            **changes,
        },
    )


def visit_rows(db, group):
    return db(
        "SELECT id, staff_agent_id, service_type, booking_time, duration_minutes, visit_group_id, linked_appointment_id, status FROM service_requests WHERE visit_group_id=%s ORDER BY booking_time, id",
        (group,),
    )


def capacity_snapshot(db):
    return {
        table: db(
            f"SELECT * FROM {table} ORDER BY "
            + (
                "reservation_id, staff_agent_id, segment_start"
                if table == "appointment_reservation_segments"
                else "id"
            )
        )
        for table in (
            "service_requests",
            "appointment_reservations",
            "appointment_reservation_segments",
            "outbox_notifications",
        )
    }
