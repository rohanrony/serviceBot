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
        {"key": "preference", "detail_type": "general", "label": "Style preference", "type": "text", "required": True},
        {"key": "guests", "detail_type": "general", "label": "Additional guests", "type": "number", "required": False},
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


def test_generic_intake_field_detail_types_and_validation():
    """US2/AC1: Generic intake field definitions support detail types and enforce text for serial numbers."""
    from pydantic import ValidationError
    from serviceBot.services.business_profile import IntakeField

    # Valid detail types
    for dt in ("general", "asset_type", "brand", "model", "serial_number"):
        f = IntakeField(key=f"k_{dt}", label=f"Label {dt}", detail_type=dt, type="text")
        assert f.detail_type == dt

    # Number type on general detail is valid
    f_num = IntakeField(key="qty", label="Quantity", detail_type="general", type="number")
    assert f_num.type == "number"

    # Serial number cannot be numeric
    with pytest.raises(ValidationError):
        IntakeField(key="sn", label="Serial number", detail_type="serial_number", type="number")

    # Invalid detail type rejected
    with pytest.raises(ValidationError):
        IntakeField(key="bad", label="Bad", detail_type="invalid_type")


def test_repeated_detail_types_allowed():
    """US2/AC2: Repeated detail types with distinct keys, labels, and requirements are allowed."""
    from serviceBot.services.business_profile import BusinessProfile, IntakeField

    profile = BusinessProfile(
        industry="Field Service",
        collect_vehicle_details=False,
        intake_fields=[
            IntakeField(key="chassis_sn", label="Chassis serial number", detail_type="serial_number", type="text", required=True),
            IntakeField(key="engine_sn", label="Engine serial number", detail_type="serial_number", type="text", required=False),
            IntakeField(key="unit_brand", label="Equipment brand", detail_type="brand", type="text", required=True),
            IntakeField(key="component_brand", label="Attachment brand", detail_type="brand", type="text", required=False),
        ],
    )
    assert len(profile.intake_fields) == 4
    assert profile.intake_fields[0].required is True
    assert profile.intake_fields[1].required is False


def test_legacy_automotive_fields_exposed_as_generic_equivalents():
    """US2/AC3: Expose legacy automotive fields as editable generic equivalents (Make as Brand, Model as Model, Year as General number)."""
    from serviceBot.services.business_profile import get_legacy_intake_defaults

    defaults = get_legacy_intake_defaults()
    assert len(defaults) == 3
    make_field = next(f for f in defaults if f["key"] == "make")
    assert make_field["detail_type"] == "brand"
    assert make_field["label"] == "Make"
    assert make_field["type"] == "text"

    model_field = next(f for f in defaults if f["key"] == "model")
    assert model_field["detail_type"] == "model"
    assert model_field["label"] == "Model"
    assert model_field["type"] == "text"

    year_field = next(f for f in defaults if f["key"] == "year")
    assert year_field["detail_type"] == "general"
    assert year_field["label"] == "Year"
    assert year_field["type"] == "number"


def test_agent_prompt_required_vs_optional_intake_rules():
    """US2/AC4: Agent prompt instructs soliciting missing required fields and prohibits asking for optional fields."""
    from serviceBot.services.business_profile import build_business_prompt

    config = {
        "business_name": "Neutral Repair",
        "business_profile": {
            "industry": "Equipment Repair",
            "collect_vehicle_details": False,
            "intake_fields": [
                {"key": "serial_num", "label": "Serial Number", "detail_type": "serial_number", "type": "text", "required": True},
                {"key": "color_pref", "label": "Color Preference", "detail_type": "general", "type": "text", "required": False},
            ],
        },
    }
    prompt, greeting = build_business_prompt(config)
    # Must instruct agent to ask for required fields by label
    assert "Serial Number" in prompt
    assert "required" in prompt.lower()
    # Must prohibit soliciting optional fields
    assert "do not solicit" in prompt.lower() or "never ask" in prompt.lower() or "prohibit" in prompt.lower() or "do not ask" in prompt.lower()
    assert "Color Preference" in prompt


def test_generic_service_request_does_not_fabricate_vehicle(profile_config):
    """US2/AC5: Generic service requests store data in intake_data without fabricating dummy vehicle records."""
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.services.booking import BookingService

    client, _ = profile_config
    client.post("/api/v1/portal/config", json={
        "business_profile": {
            "industry": "Appliance Repair",
            "collect_vehicle_details": False,
            "intake_fields": [
                {"key": "model_num", "label": "Model Number", "detail_type": "model", "type": "text", "required": True},
            ],
        }
    })

    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT COUNT(*) AS cnt FROM vehicles;")
        vehicle_count_before = cursor.fetchone()["cnt"]

    booking = BookingService()
    receipt = booking.create_portal_request(
        customer_name="Jordan Generic",
        phone="+15559870001",
        vehicle_details={"intake_data": {"model_num": "X100-PRO"}},
        request_details={
            "issue_description": "Appliance buzzing sound",
            "service_type": "Diagnostics",
            "booking_type": "appointment",
            "duration_minutes": 60,
        },
    )
    request_id = receipt["request_id"]

    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT vehicle_id, intake_data FROM service_requests WHERE id = %s;", (request_id,))
        row = cursor.fetchone()
        assert row["vehicle_id"] is None
        assert row["intake_data"] == {"model_num": "X100-PRO"}

        cursor.execute("SELECT COUNT(*) AS cnt FROM vehicles;")
        vehicle_count_after = cursor.fetchone()["cnt"]
        # No vehicle rows should be fabricated
        assert vehicle_count_after == vehicle_count_before


def test_unconfigured_legacy_profile_defaults():
    """US2/AC6: Installations without business_profile default to legacy automotive intake."""
    from serviceBot.services.business_profile import get_business_profile, get_legacy_intake_defaults

    # When config is empty or missing business_profile
    profile = get_business_profile({})
    assert profile["collect_vehicle_details"] is True
    assert len(profile["intake_fields"]) == 3
    defaults = get_legacy_intake_defaults()
    assert [f["key"] for f in profile["intake_fields"]] == [f["key"] for f in defaults]


def test_legacy_asset_inputs_normalized_into_generic_fields():
    """US2/AC7: Compatibility normalization maps legacy make/model/year into matching generic intake fields."""
    from serviceBot.services.business_profile import normalize_legacy_intake_args

    generic_profile = {
        "industry": "Equipment Rental",
        "collect_vehicle_details": False,
        "intake_fields": [
            {"key": "equip_brand", "detail_type": "brand", "label": "Brand", "type": "text", "required": True},
            {"key": "equip_model", "detail_type": "model", "label": "Model", "type": "text", "required": True},
            {"key": "equip_year", "detail_type": "general", "label": "Year", "type": "number", "required": False},
        ],
    }

    raw_args = {"make": "Caterpillar", "model": "320D", "year": "2021"}
    normalized = normalize_legacy_intake_args(raw_args, generic_profile)
    assert normalized["equip_brand"] == "Caterpillar"
    assert normalized["equip_model"] == "320D"
    assert normalized["equip_year"] == 2021


def test_explicit_empty_intake_profile_preserved(profile_config):
    """US2/AC8: An explicitly empty intake configuration is preserved without restoring automotive defaults."""
    client, _ = profile_config
    empty_profile = {
        "industry": "Consulting",
        "collect_vehicle_details": False,
        "intake_fields": [],
    }
    res = client.post("/api/v1/portal/config", json={"business_profile": empty_profile})
    assert res.status_code == 200

    saved = client.get("/api/v1/portal/config").json()
    assert saved["business_profile"]["industry"] == "Consulting"
    assert saved["business_profile"]["collect_vehicle_details"] is False
    assert saved["business_profile"]["intake_fields"] == []
