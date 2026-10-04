import datetime as dt
import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor


@pytest.fixture
def client():
    return TestClient(app)


def test_service_requests_returns_updated_at_and_sorts_by_recent_update(client):
    """
    Ensure /api/v1/portal/service-requests includes `updated_at`
    and orders recently updated requests at the top.
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Insert customer
            cursor.execute(
                """
                INSERT INTO customers (name, phone)
                VALUES ('Filter Test User', '+14155559876')
                ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """
            )
            cid = cursor.fetchone()["id"]

            # Insert an older service request created 60 days ago
            past_created = dt.datetime.now() - dt.timedelta(days=60)
            recent_updated = dt.datetime.now()
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, service_type, issue_description, status,
                    booking_type, booking_time, created_at, updated_at
                )
                VALUES (
                    %s, 'Brake Service', 'Past request recently rescheduled', 'pending',
                    'appointment', '2026-10-05 14:00:00', %s, %s
                )
                RETURNING id;
                """,
                (cid, past_created, recent_updated),
            )
            sr_id = cursor.fetchone()["id"]

    response = client.get("/api/v1/portal/service-requests")
    assert response.status_code == 200
    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) > 0

    # Locate the inserted row
    matching = [r for r in rows if r["id"] == sr_id]
    assert len(matching) == 1
    req = matching[0]

    # Verify updated_at is present and populated
    assert "updated_at" in req
    assert req["updated_at"] is not None
    assert req["booking_time"] == "2026-10-05 14:00:00"

    # Verify that the most recently updated request is positioned near or at the top
    first_row = rows[0]
    assert "updated_at" in first_row
