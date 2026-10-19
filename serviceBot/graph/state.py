from typing import TypedDict, Annotated, Sequence, Optional, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class CustomerInfo(TypedDict):
    id: Optional[int]
    name: Optional[str]
    phone: str
    email: Optional[str]
    vehicle_make: Optional[str]
    vehicle_model: Optional[str]
    vehicle_year: Optional[int]
    location: Optional[str]
    intake_data: NotRequired[dict]

class AgentState(TypedDict):
    # The message history of the call
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Customer record loaded from CRM
    customer: Optional[CustomerInfo]
    
    # Active IDs created during call
    service_request_id: Optional[int]
    appointment_id: Optional[int]
    
    intake_data: NotRequired[dict]
    service_type: NotRequired[str]

    # Router state
    current_agent: str  # "classifier" | "service_request" | "appointment" | "faq" | "handoff"
    
    # Flag to enable/disable DTMF input mode
    dtmf_active: bool
