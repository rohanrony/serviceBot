import pytest
from unittest.mock import patch
from langchain_core.messages import HumanMessage, AIMessage
from serviceBot.graph.state import AgentState

def test_handoff_node_compiles_summary_and_transfers():
    """
    Asserts that transitioning to handoff compiles a 3-5 bullet point transcript summary.
    Asserts the summary contains customer name, active service request ID, and urgency indicator.
    """
    # Attempt to import handoff_node. This will fail or return a placeholder if not implemented.
    from serviceBot.graph.nodes import handoff_node

    initial_state = {
        "messages": [
            HumanMessage(content="Hello, I need urgent service."),
            AIMessage(content="I can help with that. What is your name?"),
            HumanMessage(content="My name is John Doe, and I need a brake repair done immediately! It is urgent."),
        ],
        "customer": {
            "id": 42,
            "name": "John Doe",
            "phone": "+15559876543",
            "email": "john.doe@example.com",
            "vehicle_make": "Toyota",
            "vehicle_model": "Camry",
            "vehicle_year": 2018
        },
        "service_request_id": 101,
        "appointment_id": None,
        "current_agent": "handoff",
        "dtmf_active": False
    }

    # Execute handoff_node
    final_state = handoff_node(initial_state)

    # Assert that handoff_node returned a handoff summary
    assert "handoff_summary" in final_state, "handoff_summary key must be present in the returned state dictionary"
    summary = final_state["handoff_summary"]

    # Assert summary is a string
    assert isinstance(summary, str), "handoff_summary must be a string"

    # Assert that the summary has 3 to 5 bullet points
    # Bullet points typically start with '-', '*', or a number like '1.'
    lines = [line.strip() for line in summary.split("\n") if line.strip()]
    bullet_lines = [line for line in lines if line.startswith("-") or line.startswith("*") or (line and line[0].isdigit() and "." in line)]
    
    assert 3 <= len(bullet_lines) <= 5, f"Summary must contain 3-5 bullet points, found {len(bullet_lines)}: {bullet_lines}"

    # Assert summary contains customer name, active service request ID, and urgency indicator
    customer_name = initial_state["customer"]["name"]
    service_request_id = str(initial_state["service_request_id"])
    
    assert customer_name.lower() in summary.lower(), f"Customer name '{customer_name}' not found in summary: {summary}"
    assert service_request_id in summary, f"Service request ID '{service_request_id}' not found in summary: {summary}"
    
    urgency_terms = ["urgency", "urgent", "immediate", "priority", "critical"]
    has_urgency = any(term in summary.lower() for term in urgency_terms)
    assert has_urgency, f"Urgency indicator not found in summary: {summary}"
