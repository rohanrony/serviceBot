from typing import TypedDict, Annotated, Sequence, Optional
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

class AgentState(TypedDict):
    # The message history of the call
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Customer record loaded from CRM
    customer: Optional[CustomerInfo]
    
    # Active IDs created during call
    service_request_id: Optional[int]
    appointment_id: Optional[int]
    
    # Router state
    current_agent: str  # "classifier" | "service_request" | "appointment" | "faq" | "handoff"
    
    # Flag to enable/disable DTMF input mode
    dtmf_active: bool
