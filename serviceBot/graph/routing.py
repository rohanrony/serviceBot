from langgraph.graph import StateGraph, START, END
from serviceBot.graph.state import AgentState
from serviceBot.graph.nodes import intent_classifier_node, service_request_node, appointment_booking_node, faq_node, handoff_node

workflow = StateGraph(AgentState)

# Register nodes
workflow.add_node("intent_classifier", intent_classifier_node)
workflow.add_node("service_request", service_request_node)
workflow.add_node("appointment", appointment_booking_node)
workflow.add_node("faq", faq_node)
workflow.add_node("handoff", handoff_node)

# Set entry point
workflow.add_edge(START, "intent_classifier")

# Conditional routing function based on current_agent state variable
def route_intent(state: AgentState):
    agent = state.get("current_agent", "classifier")
    if agent == "service_request":
        return "service_request"
    elif agent == "appointment":
        return "appointment"
    elif agent == "faq":
        return "faq"
    elif agent == "handoff":
        return "handoff"
    else:
        return END

# Route conditionally from the classifier node
workflow.add_conditional_edges(
    "intent_classifier",
    route_intent,
    {
        "service_request": "service_request",
        "appointment": "appointment",
        "faq": "faq",
        "handoff": "handoff",
        END: END
    }
)

# Connect remaining nodes to END
workflow.add_edge("service_request", END)
workflow.add_edge("appointment", END)
workflow.add_edge("faq", END)
workflow.add_edge("handoff", END)

graph = workflow.compile()
