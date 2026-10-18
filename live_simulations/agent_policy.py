"""Pure prompt revision for a caller-verified, manifest-owned simulation clone."""
from copy import deepcopy

from .core import SimulationError

SERVICE_POLICY_VERSION = 'canonical-prequote-v1'
_START = '[Owned simulation service policy: ' + SERVICE_POLICY_VERSION + ']'
_POLICY = _START + '''
Use the customer's exact full canonical catalog service names throughout the conversation
and every tool call. Never strip ownership prefixes, qualifiers or words, shorten names,
substitute a generic service, or guess defaults. Preserve each service's identity and order.
Look up each requested service with get_service_fields(service_name=<exact full canonical name>).
Use that same name in check_availability(service_type=<exact full canonical name>) and
book_appointment(service_type=<exact full canonical name>). For multiple requested services,
keep their exact names in the customer's order, joined with " and " in service_type.
Use the returned catalog price and duration for EACH requested appointment service:
quote both accurately and obtain explicit consent BEFORE create_service_request or
book_appointment. A quote after creating a booking does not satisfy this requirement.
Do not invent price, duration, availability or consent; clarify missing facts before booking.
Respect the existing tool schemas: for a single service using the legacy intake tool,
call create_service_request(issue_description=<exact full canonical name>) with the required
customer, vehicle and booking fields. Do not add service_type or services to that tool.
For multiple services use book_appointment(service_type=<exact full canonical names joined
with " and ">) and its required fields; never first create a placeholder Repair booking.
For reschedule or cancel, retain the selected existing appointment/visit identities and use
the appropriate existing tools; do not create replacement bookings or change other services.
For a service-free advisor callback, retain the callback flow without adding a catalog service.
The appointment quote rule does not require a new booking or service for a callback or cancel.
[End owned simulation service policy]'''


def apply_service_policy(override):
    """Copy an override, changing only prompt text; ownership is checked by the caller."""
    try:
        original = override['conversation_config']['agent']['prompt']['prompt']
    except (KeyError, TypeError):
        raise SimulationError('Owned policy revision requires an existing text prompt') from None
    if not isinstance(original, str) or not original.strip():
        raise SimulationError('Owned policy revision requires an existing text prompt')
    result = deepcopy(override)
    if original.endswith('\n\n' + _POLICY):
        return result
    if _START in original:
        raise SimulationError('Owned policy marker does not match the expected revision')
    result['conversation_config']['agent']['prompt']['prompt'] = original + '\n\n' + _POLICY
    return result
