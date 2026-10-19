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


GROUPED_VISIT_POLICY_VERSION = 'linked-visit-service-removal-v2'
_GROUPED_START = '[Owned simulation linked visit policy: ' + GROUPED_VISIT_POLICY_VERSION + ']'
_GROUPED_REMOVAL = '''For new multi-service appointments, the server creates one appointment and calendar entry per technician.
Each appointment's service_components contains its ordered exact canonical service names and
snapshotted duration values. Keep every requested service in the single booking request;
do not create separate duplicate appointments to imitate the server's grouping.
When the caller wants only one service removed, use the authoritative lookup to select
the exact owned appointment and exact canonical service_name from service_components.
Do not infer component identity by splitting a display label or using current catalog
durations. Missing, malformed, ambiguous or unsupported legacy component metadata needs
clarification or supported staff recovery, never a whole-visit cancellation as a fallback.
Explain the precise revision and obtain explicit consent: retain the same appointment start,
remove only the selected service and shorten its end by that service's snapshotted duration.
Keep the other technicians' appointment start times, end times and services unchanged.
Make exactly one cancel_appointment(appointment_id=<selected owned appointment ID>,
service_name=<exact canonical component name>) call with the existing required phone fields.
The service_name argument selects removal; omit it only after explicit consent for the
entire linked visit, or for an unlinked appointment cancellation. A selected technician appointment alone does not authorize whole-group cancellation.
For a selected linked appointment, select the exact returned service component; clarify
broader scope before mutation rather than omitting service_name as a shortcut.
Never parallel or retry ambiguous removal mutations.
Await the result and call get_customer_appointments again. For a shortened appointment,
verify the same ID/start, only the requested component absent, exact remaining duration,
shortened end and unchanged companion identities/times before confirming success.
If this was its last component, require the mutation's explicit selected-only cancellation
outcome plus companion read-back; absence from an active-only lookup is not cancellation proof.
Do not invent calendar or notification delivery. State pending or failed projection/delivery
honestly and offer supported recovery when the result or read-back is uncertain.'''
_GROUPED_POLICY = _LINKED_POLICY.replace(_LINKED_START, _GROUPED_START).replace(
    'the visit remains contiguous, and unrelated bookings are unchanged.',
    'relative appointment offsets are preserved, and unrelated bookings are unchanged. '
    'Do not close an intentional gap left by a previous service removal.',
).replace(
    "If the caller\nwants only one component, clarify the server's whole-group scope before any mutation.",
    _GROUPED_REMOVAL,
)


def apply_grouped_visit_policy(override):
    """Versioned prompt-only candidate; prior live policy helpers stay immutable."""
    try:
        original = override['conversation_config']['agent']['prompt']['prompt']
    except (KeyError, TypeError):
        raise SimulationError('Grouped visit policy requires an exact known source prompt') from None
    if not isinstance(original, str) or original.count(_POLICY) != 1:
        raise SimulationError('Grouped visit policy requires the exact canonical quote policy')
    result = deepcopy(override)
    if (original.count(_GROUPED_POLICY) == 1 and original.count(_GROUPED_START) == 1
            and _LINKED_START not in original):
        return result
    if (_GROUPED_START in original or original.count(_LINKED_POLICY) != 1
            or original.count(_LINKED_START) != 1):
        raise SimulationError('Grouped visit policy marker does not match the expected revision')
    result['conversation_config']['agent']['prompt']['prompt'] = original.replace(_LINKED_POLICY, _GROUPED_POLICY)
    return result
