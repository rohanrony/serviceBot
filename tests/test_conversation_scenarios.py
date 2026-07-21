import pytest
from unittest.mock import patch, MagicMock
from serviceBot.conversation_simulator import ConversationSimulator, VOICE_TOOLS

@pytest.fixture
def simulator():
    return ConversationSimulator(use_mock=True)

def test_simulator_initialization(simulator):
    """Verify simulator starts with correct system prompt and initial assistant message."""
    assert len(simulator.messages) == 2
    assert simulator.messages[0]["role"] == "system"
    assert simulator.messages[1]["role"] == "assistant"
    assert "Rachel" in simulator.messages[1]["content"]

def test_voice_tools_definitions():
    """Verify all required tool schemas are registered in VOICE_TOOLS."""
    tool_names = [t["function"]["name"] for t in VOICE_TOOLS]
    expected_tools = [
        "check_availability",
        "get_service_fields",
        "create_service_request",
        "book_appointment",
        "request_callback",
        "get_customer_appointments",
        "reschedule_appointment",
        "query_knowledge_base",
        "cba_webhook"
    ]
    for tool_name in expected_tools:
        assert tool_name in tool_names, f"Missing tool definition: {tool_name}"

def test_scenario_appointment_booking(simulator):
    """Test end-to-end appointment booking flow with tool execution."""
    script = [
        "What are your business hours?",
        "I need an oil change for my 2021 Toyota Camry. My name is Alex Smith, phone 555-123-4567.",
        "Can you check what time slots are open for 2026-06-10?",
        "Yes, 10:00 AM on 2026-06-10 works for me. Please book it."
    ]

    transcript = simulator.run_scenario(script)
    assert len(transcript) == 4

    # Turn 1: FAQ query
    assert transcript[0]["turn"] == 1
    assert any(tc["tool_name"] == "query_knowledge_base" for tc in transcript[0]["tool_calls"])

    # Turn 2: Service fields lookup
    assert transcript[1]["turn"] == 2
    assert any(tc["tool_name"] == "get_service_fields" for tc in transcript[1]["tool_calls"])

    # Turn 3: Check availability
    assert transcript[2]["turn"] == 3
    assert any(tc["tool_name"] == "check_availability" for tc in transcript[2]["tool_calls"])

    # Turn 4: Booking appointment
    assert transcript[3]["turn"] == 4
    assert any(tc["tool_name"] == "book_appointment" for tc in transcript[3]["tool_calls"])

def test_scenario_callback_request(simulator):
    """Test callback request flow when user prefers a callback."""
    turn_res = simulator.run_turn("I need a callback for my vehicle, name Sarah Connor, phone 5559876543, 2019 Honda Civic brake issue.")
    assert len(turn_res["tool_calls"]) > 0
    assert turn_res["tool_calls"][0]["tool_name"] in ["request_callback", "create_service_request"]

def test_scenario_faq_query(simulator):
    """Test FAQ and general knowledge queries."""
    turn_res = simulator.run_turn("What are your business hours?")
    assert len(turn_res["tool_calls"]) == 1
    assert turn_res["tool_calls"][0]["tool_name"] == "query_knowledge_base"
    assert "7:00 AM to 6:00 PM" in turn_res["assistant_response"]

def test_scenario_human_handoff(simulator):
    """Test human agent handoff request."""
    turn_res = simulator.run_turn("Can I please speak with a human service advisor?")
    assert len(turn_res["tool_calls"]) == 1
    assert turn_res["tool_calls"][0]["tool_name"] == "cba_webhook"
    assert "connecting" in turn_res["assistant_response"].lower() or "hold" in turn_res["assistant_response"].lower()
