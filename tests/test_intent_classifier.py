import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

# Import AgentState and compiled graph
# (In TDD Red phase, these will fail because they are not yet defined)
from serviceBot.graph.state import AgentState
from serviceBot.graph.routing import graph

def test_intent_classifier_routing_appointment():
    """
    Assert that passing 'I need to schedule brake repair' routes and updates state current_agent = 'appointment'.
    """
    initial_state = {
        "messages": [HumanMessage(content="I need to schedule brake repair")],
        "customer": None,
        "service_request_id": None,
        "appointment_id": None,
        "current_agent": "classifier",
        "dtmf_active": False
    }
    
    # Mock ChatOpenAI invocation to classify the intent as appointment booking
    with patch("serviceBot.graph.nodes.ChatOpenAI") as mock_chat:
        mock_instance = mock_chat.return_value
        mock_structured = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured
        mock_structured.invoke.return_value = {"intent": "appointment_booking"}
        mock_structured.return_value = {"intent": "appointment_booking"}
        
        # Execute the compiled graph
        final_state = graph.invoke(initial_state)
        
        # Verify the state's current_agent is updated to appointment
        assert final_state["current_agent"] == "appointment"

def test_intent_classifier_routing_greeting():
    """
    Assert that greeting inputs update/keep state current_agent = 'classifier'.
    """
    initial_state = {
        "messages": [HumanMessage(content="Hello, dynamic assistant!")],
        "customer": None,
        "service_request_id": None,
        "appointment_id": None,
        "current_agent": "classifier",
        "dtmf_active": False
    }
    
    # Mock ChatOpenAI invocation to classify the intent as a greeting/fallback
    with patch("serviceBot.graph.nodes.ChatOpenAI") as mock_chat:
        mock_instance = mock_chat.return_value
        mock_structured = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured
        mock_structured.invoke.return_value = {"intent": "greeting"}
        mock_structured.return_value = {"intent": "greeting"}
        
        # Execute the compiled graph
        final_state = graph.invoke(initial_state)
        
        # Verify the state's current_agent is classifier
        assert final_state["current_agent"] == "classifier"
