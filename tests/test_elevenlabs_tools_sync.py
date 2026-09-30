import pytest
from scripts.sync_elevenlabs_tools import TOOL_DEFINITIONS, WEBHOOK_URL

def test_tool_definitions_completeness():
    """Verify that all required voice tools are present in the ElevenLabs tool suite."""
    required_tool_names = [
        "get_customer_appointments",
        "reschedule_appointment",
        "consolidate_appointment_service",
        "check_availability",
        "book_appointment",
        "create_service_request",
        "request_callback",
        "get_service_fields",
        "query_knowledge_base",
        "cba_webbook",
    ]
    tool_map = {t["name"]: t for t in TOOL_DEFINITIONS}
    
    for tool_name in required_tool_names:
        assert tool_name in tool_map, f"Missing critical tool {tool_name} from ElevenLabs tool definitions"
        tool = tool_map[tool_name]
        assert tool["type"] == "webhook"
        api_schema = tool.get("api_schema", {})
        assert api_schema.get("method") == "POST"
        assert "url" in api_schema
        assert "request_body_schema" in api_schema

def test_get_customer_appointments_tool_schema():
    """Verify get_customer_appointments tool schema matches telephony backend requirements."""
    tool_map = {t["name"]: t for t in TOOL_DEFINITIONS}
    tool = tool_map["get_customer_appointments"]
    
    body_schema = tool["api_schema"]["request_body_schema"]
    assert "phone" in body_schema["required"]
    assert "phone" in body_schema["properties"]
    assert body_schema["properties"]["phone"]["type"] == "string"

def test_reschedule_appointment_tool_schema():
    """Verify reschedule_appointment tool schema contains required parameters."""
    tool_map = {t["name"]: t for t in TOOL_DEFINITIONS}
    tool = tool_map["reschedule_appointment"]
    
    body_schema = tool["api_schema"]["request_body_schema"]
    assert "phone" in body_schema["required"]
    assert "new_appointment_datetime" in body_schema["required"]
    assert "appointment_id" in body_schema["properties"]

def test_consolidate_appointment_tool_schema():
    """Verify consolidate_appointment_service tool schema contains required parameters."""
    tool_map = {t["name"]: t for t in TOOL_DEFINITIONS}
    tool = tool_map["consolidate_appointment_service"]
    
    body_schema = tool["api_schema"]["request_body_schema"]
    assert "phone" in body_schema["required"]
    assert "additional_issue" in body_schema["required"]
    assert "additional_duration_minutes" in body_schema["properties"]

def test_tool_urls_contain_tool_name_query_parameter():
    """Verify that every tool webhook URL in TOOL_DEFINITIONS has ?name=<tool_name> for unambiguous routing."""
    for tool in TOOL_DEFINITIONS:
        name = tool["name"]
        url = tool.get("api_schema", {}).get("url", "")
        assert f"?name={name}" in url, f"Tool {name} URL does not contain ?name={name}: {url}"
