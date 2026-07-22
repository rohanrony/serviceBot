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

def test_multiple_service_issues_extraction(simulator):
    """Verify that when a user mentions multiple issues (e.g. oil change + brakes), both issues are extracted into issue_description."""
    simulator.run_turn("I need an oil change and my brakes are squeaking on my 2020 Honda Civic. Name is John Doe, 555-111-2222.")
    assert simulator.intake_state["issue_description"] is not None
    assert "Oil Change" in simulator.intake_state["issue_description"]
    assert "Brake Inspection & Repair" in simulator.intake_state["issue_description"]

def test_scenario_multiple_issues_booking_flow(simulator):
    """Test complete flow where caller requests multiple services, rates are checked, and booking happens at the end of the call."""
    script = [
        "Hi, I need an oil change and brake inspection for my 2022 Ford F-150. My name is Mark Taylor, phone 555-888-9999.",
        "What time slots are available for 2026-06-12?",
        "That works. Please book the 10:00 AM appointment for both services."
    ]

    transcript = simulator.run_scenario(script)
    assert len(transcript) == 3

    # Turn 1: All intake details and multiple issues captured
    assert simulator.intake_state["name"] == "Mark Taylor"
    assert "Oil Change" in simulator.intake_state["issue_description"]
    assert "Brake Inspection & Repair" in simulator.intake_state["issue_description"]

    # Turn 2: Availability check before final booking request
    assert any(tc["tool_name"] == "check_availability" for tc in transcript[1]["tool_calls"])

    # Turn 3: Booking occurs as the final step after all details, pricing, and slots are captured
    assert any(tc["tool_name"] == "book_appointment" for tc in transcript[2]["tool_calls"])

def test_booking_deferred_until_call_completion(simulator):
    """Verify that booking tool is executed only after all mandatory intake details and slot selection are finalized at the end of turn sequence."""
    # Step 1: Initial intake without date selection - book_appointment should NOT be called yet
    turn1 = simulator.run_turn("I want to book an appointment for an oil change. Name: Bob Smith, Phone: 555-333-4444, Car: 2018 Toyota Corolla.")
    tool_names_turn1 = [tc["tool_name"] for tc in turn1["tool_calls"]]
    assert "book_appointment" not in tool_names_turn1

    # Step 2: Slot requested - availability checked first
    turn2 = simulator.run_turn("Check slots for 2026-06-15.")
    tool_names_turn2 = [tc["tool_name"] for tc in turn2["tool_calls"]]
    assert "check_availability" in tool_names_turn2
    assert "book_appointment" not in tool_names_turn2

    # Step 3: Final confirmation at end of call - book_appointment called
    turn3 = simulator.run_turn("Book the 10:00 AM slot on 2026-06-15.")
    tool_names_turn3 = [tc["tool_name"] for tc in turn3["tool_calls"]]
    assert "book_appointment" in tool_names_turn3

def test_intake_overview_and_sequential_asking(simulator):
    """Verify assistant asks intake details sequentially (one at a time) rather than dumping multiple questions simultaneously."""
    # Turn 1: Initial vague request - Assistant should ask for name first
    turn1 = simulator.run_turn("Hi, I'd like to bring my car in for service.")
    response1 = turn1["assistant_response"].lower()
    assert "name" in response1
    # Ensure it doesn't ask for phone AND year AND model simultaneously in turn 1
    assert not ("phone" in response1 and "year" in response1 and "model" in response1)

    # Turn 2: User provides name - Assistant verifies name and asks for phone next
    turn2 = simulator.run_turn("My name is Alex Smith.")
    response2 = turn2["assistant_response"].lower()
    assert "phone" in response2 or "number" in response2

    # Turn 3: User provides phone - Assistant asks for vehicle details next
    turn3 = simulator.run_turn("555-123-4567")
    response3 = turn3["assistant_response"].lower()
    assert any(w in response3 for w in ["vehicle", "year", "make", "model"])

def test_tool_execution_filler_phrases(simulator):
    """Verify conversational filler phrases are spoken during tool execution to set caller expectations and prevent dead air."""
    # Test FAQ query filler phrase
    faq_turn = simulator.run_turn("What are your business hours?")
    assert len(faq_turn["tool_calls"]) > 0
    assert any(phrase in faq_turn["assistant_response"].lower() for phrase in ["moment", "look that up", "check", "hours", "open"])

    # Test Calendar availability check filler phrase
    cal_turn = simulator.run_turn("Can you check open slots for 2026-06-10?")
    assert len(cal_turn["tool_calls"]) > 0
    assert any(phrase in cal_turn["assistant_response"].lower() for phrase in ["moment", "check", "schedule", "open slots", "availability"])


