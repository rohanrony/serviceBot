import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage
from serviceBot.graph.state import AgentState

# These imports should fail in the TDD Red phase since they are not implemented yet.
try:
    from serviceBot.graph.nodes import service_request_node
except ImportError:
    # We allow the import to fail or define a placeholder if needed,
    # but to ensure pytest runs and fails on assertions/imports,
    # we can either let it raise ImportError or define it as None to fail during invocation.
    service_request_node = None

try:
    from serviceBot.db.queries import create_service_request
except ImportError:
    create_service_request = None


def test_service_request_agent_missing_vehicle_fields():
    """
    Assert that if vehicle fields (make, model, year) are missing,
    the service request agent emits follow-up questions and does not create a service request.
    """
    if service_request_node is None:
        pytest.fail("service_request_node is not implemented/imported yet.")

    # State with missing vehicle fields and missing issue
    initial_state: AgentState = {
        "messages": [HumanMessage(content="My car is making a noise")],
        "customer": {
            "id": 1,
            "name": "Sarah Johnson",
            "phone": "+15551234567",
            "email": "sarah.j@example.com",
            "vehicle_make": None,
            "vehicle_model": None,
            "vehicle_year": None
        },
        "service_request_id": None,
        "appointment_id": None,
        "current_agent": "service_request",
        "dtmf_active": False
    }

    # Mock ChatOpenAI / LLM to ask for the missing make, model, and year
    with patch("serviceBot.graph.nodes.ChatOpenAI") as mock_chat, \
         patch("serviceBot.db.queries.create_service_request") as mock_create:
        
        mock_instance = mock_chat.return_value
        mock_instance.invoke.return_value = AIMessage(content="Could you please provide the make, model, and year of your vehicle?")
        
        # Invoke node
        final_state = service_request_node(initial_state)
        
        # Verify that create_service_request was not called
        mock_create.assert_not_called()
        
        # Verify that the final state contains the follow-up question in messages
        assert final_state["messages"][-1].content == "Could you please provide the make, model, and year of your vehicle?"
        # service_request_id should remain None
        assert final_state["service_request_id"] is None


def test_service_request_agent_all_fields_present():
    """
    Assert that once name, phone, make, model, year, and issue are present,
    the agent invokes create_service_request() and updates service_request_id.
    """
    if service_request_node is None:
        pytest.fail("service_request_node is not implemented/imported yet.")

    # State with all necessary customer/vehicle fields and issue description
    initial_state: AgentState = {
        "messages": [
            HumanMessage(content="My 2020 Honda Civic has a grinding noise when stopping.")
        ],
        "customer": {
            "id": 1,
            "name": "Sarah Johnson",
            "phone": "+15551234567",
            "email": "sarah.j@example.com",
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "vehicle_year": 2020,
            "location": "Springfield"
        },
        "service_request_id": None,
        "appointment_id": None,
        "current_agent": "service_request",
        "dtmf_active": False
    }

    with patch("serviceBot.graph.nodes.ChatOpenAI") as mock_chat, \
         patch("serviceBot.db.queries.create_service_request") as mock_create:
        
        # Mock create_service_request to return a new service request ID (e.g., 42)
        mock_create.return_value = 42
        
        mock_instance = mock_chat.return_value
        mock_instance.invoke.return_value = AIMessage(content="I have created a service request for your Honda Civic.")
        
        # Invoke node
        final_state = service_request_node(initial_state)
        
        # Verify create_service_request was called with the correct details
        mock_create.assert_called_once_with(
            customer_id=1,
            vehicle_details={
                "make": "Honda",
                "model": "Civic",
                "year": 2020
            },
            issue="My 2020 Honda Civic has a grinding noise when stopping.",
            service_type="Repair"
        )
        
        # Verify that service_request_id is populated in the state
        assert final_state["service_request_id"] == 42
