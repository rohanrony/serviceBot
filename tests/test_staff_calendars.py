import datetime as dt_mod

import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.db.queries import check_availability, book_appointment

client = TestClient(app)


def _future_business_datetime(hour: int, days_ahead: int = 28) -> str:
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=days_ahead)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)
    return f"{candidate.isoformat()} {hour:02d}:00:00"

@pytest.fixture(autouse=True)
def clean_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-12 15:00:00';")
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-11 09:00:00';")
        conn.commit()
    yield
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-12 15:00:00';")
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-11 09:00:00';")
        conn.commit()

def test_get_staff_agents_endpoint():
    response = client.get("/api/v1/portal/agents")
    assert response.status_code == 200
    agents = response.json()
    assert isinstance(agents, list)
    assert len(agents) >= 3
    # Check seeded agents exist
    names = [a["name"] for a in agents]
    assert "John Doe" in names
    assert "Jane Smith" in names
    assert "Bob Johnson" in names



def test_db_queries_integration():
    target_time = _future_business_datetime(8)
