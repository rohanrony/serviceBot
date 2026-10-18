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


LINKED_VISIT_POLICY_VERSION = 'linked-visit-anchor-v1'
_LINKED_START = '[Owned simulation linked visit policy: ' + LINKED_VISIT_POLICY_VERSION + ']'
_LINKED_POLICY = _LINKED_START + '''
Before moving or cancelling an existing linked visit, call get_customer_appointments.
Use only its authoritative visit_group_id, visit_anchor_id, visit_start and visit_member_ids.
Never infer a group from the same date, adjacent times, similar service names, vehicle,
or the caller's assertion alone; do not invent membership or synthesize group identifiers.
Verify every member ID is present in the lookup and belongs to the same returned group,
with consistent membership, anchor and visit start. Read each member's appointment_datetime
and duration_minutes. The visit_anchor_id must identify the earliest component and
visit_start must match that component's start. If metadata is missing, incomplete,
contradictory or uncertain, clarify the intended visit and stop the mutation until an
authoritative lookup can establish its full identity and scope.
When the caller requests a new VISIT start, explain that the linked services move together
and obtain explicit consent for the whole identified group and requested VISIT start.
Make exactly one reschedule_appointment(appointment_id=visit_anchor_id,
new_appointment_datetime=<requested VISIT start>) call with the required existing phone
fields. The server shifts linked companions automatically relative to the selected anchor.
Never parallel companion reschedules or reschedule each component to the same target;
that would move the group repeatedly and change its overall start.
Await that single result, then call get_customer_appointments again and read back
every member ID, appointment time and duration before confirming success. Verify the
earliest start equals the requested VISIT start, all member identities and durations are
preserved, the visit remains contiguous, and unrelated bookings are unchanged. If the
mutation or read-back is uncertain or mismatched, report uncertainty without a false
success claim; do not retry the mutation or issue a second companion reschedule.
For cancellation of a confirmed linked group, obtain consent for all its members and
call cancel_appointment once with appointment_id=visit_anchor_id and the required existing
phone fields. Await the result and read back the member outcomes before claiming complete
cancellation; absence from an active-only lookup alone is not proof of cancellation.
Do not issue parallel or repeated companion cancellations. If the caller
wants only one component, clarify the server's whole-group scope before any mutation.
Keep separate or unlinked appointments separate; never merge selected/unselected
bookings merely because they share a customer or date. Use the selected appointment ID
and ordinary existing flow for an unlinked visit, preserving every unselected booking.
Keep service-free advisor callback handling and the existing canonical service and
prebooking quote/consent policy unchanged. Do not create replacement bookings.
Do not add visit_group_id or visit_member_ids to mutation arguments; use the existing
reschedule/cancel schemas and use returned group metadata only to select and verify scope.
[End owned simulation linked visit policy]'''


def apply_linked_visit_policy(override):
    """Prepare a separate prompt-only candidate; this function never updates an agent."""
    try:
        original = override['conversation_config']['agent']['prompt']['prompt']
    except (KeyError, TypeError):
        raise SimulationError('Linked visit policy requires an existing text prompt') from None
    if not isinstance(original, str) or not original.strip():
        raise SimulationError('Linked visit policy requires an existing text prompt')
    result = deepcopy(override)
    if original.endswith('\n\n' + _LINKED_POLICY):
        return result
    if _LINKED_START in original:
        raise SimulationError('Linked visit policy marker does not match the expected revision')
    result['conversation_config']['agent']['prompt']['prompt'] = original + '\n\n' + _LINKED_POLICY
    return result
