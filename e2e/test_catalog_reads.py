"""Catalog GET preserves persisted offerings and technician mappings."""

from e2e.test_workflows import PORTAL


def test_catalog_get_preserves_duplicate_offerings_and_their_agent_tags(api, db):
    first = db("SELECT id FROM services ORDER BY id LIMIT 1")[0]["id"]
    second = db("INSERT INTO services (name, duration_minutes, price_range) SELECT name, 45, '$90' FROM services WHERE id=%s RETURNING id", (first,))[0]["id"]
    db("INSERT INTO service_staff_agents (service_id, staff_agent_id) VALUES (%s, 1), (%s, 2)", (first, second))
    before = db("SELECT * FROM services ORDER BY id")
    before_tags = db("SELECT * FROM service_staff_agents ORDER BY service_id, staff_agent_id")
    response = api.get(f"{PORTAL}/services")
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    assert set(rows) == {row["id"] for row in before}
    assert rows[first]["assigned_agent_ids"] == [1]
    assert rows[second]["assigned_agent_ids"] == [2]
    assert db("SELECT * FROM services ORDER BY id") == before
    assert db("SELECT * FROM service_staff_agents ORDER BY service_id, staff_agent_id") == before_tags


def test_empty_catalog_get_does_not_seed_or_index(api, db, monkeypatch):
    from serviceBot.api import portal

    db("DELETE FROM service_staff_agents")
    db("DELETE FROM services")
    indexing = []
    monkeypatch.setattr(portal, "sync_services_to_kb", lambda: indexing.append(True))
    response = api.get(f"{PORTAL}/services")
    assert response.status_code == 200, response.text
    assert response.json() == []
    assert db("SELECT id FROM services") == []
    assert indexing == []
