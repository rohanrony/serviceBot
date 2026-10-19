import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from serviceBot.api import portal
from serviceBot.main import app


PROFILE = {
    "industry": "Salon",
    "collect_vehicle_details": False,
    "intake_fields": [
        {"key": "preference", "label": "Style preference", "type": "text", "required": True},
        {"key": "guests", "label": "Additional guests", "type": "number", "required": False},
    ],
}


@pytest.fixture
def profile_config(tmp_path, monkeypatch):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    sync = AsyncMock()
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", sync)
    portal.save_config({"business_name": "Studio", "system_prompt": "Custom policy", "first_message": "Welcome"})
    return TestClient(app), sync


def test_business_profile_persists_and_unrelated_save_preserves_prompt(profile_config):
    client, sync = profile_config
    assert client.post("/api/v1/portal/config", json={"business_profile": PROFILE}).status_code == 200
    saved = client.get("/api/v1/portal/config").json()
    assert saved["business_profile"] == PROFILE
    assert saved["system_prompt"] == "Custom policy"
    assert client.post("/api/v1/portal/config", json={"min_booking_buffer_hours": 5}).status_code == 200
    assert client.get("/api/v1/portal/config").json()["business_profile"] == PROFILE


@pytest.mark.parametrize("fields", [
    [{"key": "bad key", "label": "Label"}],
    [{"key": "x", "label": ""}],
    [{"key": "x", "label": "Label", "type": "object"}],
    [{"key": "x", "label": "A"}, {"key": "x", "label": "B"}],
    [{"key": f"k{i}", "label": "Label"} for i in range(21)],
])
def test_invalid_profile_is_rejected_without_save_or_sync(profile_config, fields):
    client, sync = profile_config
    before = portal.load_config()
    response = client.post("/api/v1/portal/config", json={"business_profile": {**PROFILE, "intake_fields": fields}})
    assert response.status_code == 422
    assert portal.load_config() == before
    sync.assert_not_awaited()


def test_generated_prompt_uses_business_identity_and_configured_intake(profile_config):
    client, sync = profile_config
    response = client.post("/api/v1/portal/config", json={
        "business_name": "Willow Studio", "business_profile": PROFILE, "regenerate_business_prompt": True,
    })
    assert response.status_code == 200
    cfg = portal.load_config()
    assert "Willow Studio" in cfg["system_prompt"] and "Willow Studio" in cfg["first_message"]
    assert "Style preference" in cfg["system_prompt"]
    assert "intake_data_json" in cfg["system_prompt"]
    assert not any(word in cfg["system_prompt"].lower() for word in ("technician", "vehicle", "work bay", "davidson"))
    assert sync.await_args.args[1] == cfg["first_message"]


@pytest.mark.parametrize("data", [{}, {"preference": " "}, {"preference": []}, {"preference": "a", "guests": True},
    {"preference": "a", "guests": "two"}, {"preference": "a", "unknown": "value"}, {"preference": "a" * 2001}])
def test_invalid_intake_does_not_create_customer_or_request(profile_config, data):
    client, _ = profile_config
    client.post("/api/v1/portal/config", json={"business_profile": PROFILE})
    from unittest.mock import patch
    with patch("serviceBot.services.booking.BookingService.create_portal_request") as create:
        response = client.post("/api/v1/portal/service-requests", json={
            "customer": {"name": "New person", "phone": "5550100099"},
            "intake_data": data,
            "service_request": {"issue_description": "Consultation", "service_type": "Consultation"},
        })
    assert response.status_code == 400
    create.assert_not_called()


def test_intake_zero_and_optional_fields_are_valid():
    from serviceBot.services.business_profile import validate_intake_data
    assert validate_intake_data({"preference": "Short", "guests": 0}, PROFILE) == {"preference": "Short", "guests": 0}


def test_voice_reports_configured_fields_in_generic_mode(profile_config):
    client, _ = profile_config
    client.post("/api/v1/portal/config", json={"business_profile": PROFILE})
    response = client.post("/api/v1/voice/tools?name=get_service_fields", json={"service_name": "Oil Change"})
    result = response.json()["result"]
    assert result["intake_fields"] == PROFILE["intake_fields"]
    assert result["required_fields"]["vehicle_details"] is False


def test_voice_invalid_intake_fails_before_customer_lookup(profile_config):
    client, _ = profile_config
    client.post("/api/v1/portal/config", json={"business_profile": PROFILE})
    from unittest.mock import patch
    with patch("serviceBot.api.telephony.lookup_customer_by_phone") as lookup:
        result = client.post("/api/v1/voice/tools?name=create_service_request", json={
            "customer_name": "New person", "phone": "5550100099", "intake_data_json": json.dumps({}),
        }).json()["result"]
    assert result["success"] is False
    assert "Style preference" in result["message"]
    lookup.assert_not_called()


def test_generated_prompt_stays_synchronized_after_policy_change(profile_config):
    client, _ = profile_config
    client.post("/api/v1/portal/config", json={"business_profile": PROFILE, "regenerate_business_prompt": True})
    response = client.post("/api/v1/portal/config", json={
        "min_booking_buffer_hours": 6, "min_callback_buffer_hours": 3,
        "business_hours_start": 9, "business_hours_end": 17,
    })
    assert response.status_code == 200
    prompt = portal.load_config()["system_prompt"]
    assert "Appointments require at least 6 hours" in prompt
    assert "callbacks require 3 hours" in prompt
    assert "9:00 AM - 5:00 PM" in prompt


def test_summary_uses_configured_business_and_field_labels():
    from serviceBot.services.business_profile import build_summary_prompt
    prompt = build_summary_prompt({"business_name": "Willow Studio", "business_profile": PROFILE})
    assert "Willow Studio" in prompt and "Style preference" in prompt
    assert not any(word in prompt.lower() for word in ("automotive", "vehicle", "davidson", "technician"))


def test_migration_preserves_rows_and_guards_rollback():
    from pathlib import Path
    from serviceBot.db.connection import get_db_connection
    from psycopg2 import errors
    migration = Path(__file__).resolve().parents[1] / "serviceBot/db/migrations/0010_business_intake.sql"
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE profile_migration_test (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO profile_migration_test VALUES (1)")
        cursor.execute(migration.read_text().replace("service_requests", "profile_migration_test"))
        cursor.execute("SELECT id, intake_data FROM profile_migration_test")
        assert list(cursor.fetchone()) == [1, {}]
        cursor.execute("UPDATE profile_migration_test SET intake_data = %s::jsonb", (json.dumps({"preference": "Short"}),))
        cursor.execute("SAVEPOINT rollback_guard")
        down = migration.with_name("0010_business_intake.down.sql").read_text().replace("service_requests", "profile_migration_test")
        with pytest.raises(errors.RaiseException):
            cursor.execute(down)
        cursor.execute("ROLLBACK TO SAVEPOINT rollback_guard")
        cursor.execute("SELECT intake_data FROM profile_migration_test")
        assert cursor.fetchone()[0] == {"preference": "Short"}
        cursor.execute("UPDATE profile_migration_test SET intake_data = '{}'::jsonb")
        cursor.execute(down)
        cursor.execute("SELECT * FROM profile_migration_test")
        assert list(cursor.fetchone()) == [1]


def test_graph_intake_respects_generic_profile(profile_config):
    from langchain_core.messages import HumanMessage
    from unittest.mock import patch
    from serviceBot.graph.nodes import service_request_node

    client, _ = profile_config
    client.post("/api/v1/portal/config", json={"business_profile": PROFILE, "required_fields": {
        "customer_name": True, "phone_number": True, "vehicle_details": True, "issue_description": True,
    }})
    with patch("serviceBot.graph.nodes.ChatOpenAI"), patch("serviceBot.db.queries.create_service_request", return_value=99) as create:
        result = service_request_node({
            "customer": {"id": 1, "name": "Salon Customer", "phone": "5550100099"},
            "intake_data": {"preference": "Short"},
            "messages": [HumanMessage(content="Style consultation")],
        })
    assert result["service_request_id"] == 99
    assert create.call_args.kwargs["vehicle_details"]["intake_data"] == {"preference": "Short"}


def test_notification_portal_link_uses_configured_business_url():
    from serviceBot.services.business_profile import notification_portal_url
    assert notification_portal_url({"portal_base_url": "https://studio.example/"}) == "https://studio.example/portal/#dashboard"
    assert notification_portal_url({}) == ""


@pytest.mark.parametrize("url", ["javascript:alert(1)", "not a URL", "https://user:password@example.com", "https://studio.example/?secret=x"])
def test_invalid_portal_url_does_not_save_or_sync(profile_config, url):
    client, sync = profile_config
    before = portal.load_config()
    response = client.post("/api/v1/portal/config", json={"portal_base_url": url})
    assert response.status_code == 422
    assert portal.load_config() == before
    sync.assert_not_awaited()
