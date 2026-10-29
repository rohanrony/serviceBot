"""Stable ownership markers for calendar events created by the service."""

MANAGED_EVENT_PROPERTY = "serviceBotManagedEvent"
AGENT_BOOKING_EVENT = "agent_booking"
ADMIN_BOOKING_EVENT = "admin_booking"


def managed_event_extended_properties(owner: str) -> dict:
    """Return a private Calendar API marker that survives display-name changes."""
    return {"private": {MANAGED_EVENT_PROPERTY: owner}}


def is_managed_calendar_event(event: dict, owner: str) -> bool:
    extended = event.get("extendedProperties") or {}
    private = extended.get("private") or {}
    return private.get(MANAGED_EVENT_PROPERTY) == owner
