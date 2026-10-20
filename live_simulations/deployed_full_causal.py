"""Read-only causal diagnostics for cases without safe native effect triggers.

These helpers deliberately confer no runner capability. A native outbox transition
is partial evidence; authenticated ingress is independently joined through its dedicated audit table.
Webhook replay state alone also includes sync and direct payload ingestion.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import deployed_medium as medium
from .core import SimulationError
from .evidence import check

REQUIREMENTS = {
    'C35': 'requires an independently audited, owned-reservation-scoped deployed projection fault and recovery trigger; shared calendar credentials must not be changed',
    'C36': 'requires deployed server commit and response-loss correlation tied to the same native idempotency identity and retry; a local proxy timeout is insufficient',
    'C37': 'requires an actual provider rejection bound to the owned notification and provider message attempt without shared messaging changes',
    'C50': 'requires actual provider conversation readback plus authenticated native callback ingress provenance bound to its raw payload hash; authenticated ingress migration must be applied and native provenance observed',
}
SUPPORTED_CASE_IDS = frozenset()


def _case(cid):
    if cid not in REQUIREMENTS:
        raise SimulationError('Unknown causal case')


def arrange(adapter, cid, values):
    """Reject before mutation or provider submission; ready flags cannot bypass."""
    adapter._guard()
    _case(cid)
    if cid != 'C50':
        raise SimulationError(cid + ' ' + REQUIREMENTS[cid])
    if not hasattr(adapter,'config'):
        raise SimulationError('C50 requires native customer identity')
    identity = medium._identity_id(adapter.config)
    if identity is None or adapter.state.get('full_history'):
        raise SimulationError('C50 requires unique native customer identity and fresh lifecycle')
    rows = medium._read(adapter.config,'SELECT id,name,phone FROM customers WHERE id=%s',(identity,))
    expected = adapter.config['existing_customer_identity']
    phone = medium._digits(adapter.config.get('variables',{}).get('customer_phone',''))
    if (len(rows) != 1 or rows[0]['name'] != expected['name'] or not phone
            or medium._digits(rows[0]['phone']) != phone):
        raise SimulationError('C50 requires exact unambiguous native customer identity')
    baseline = history_baseline(adapter,customer_id=identity)
    raw_phone=re.sub(r'\D','',str(rows[0]['phone']))
    if len(raw_phone)==10:
        raw_phone='1'+raw_phone
    if len(raw_phone)!=11 or not raw_phone.startswith('1'):
        raise SimulationError('C50 requires designated native North American phone identity')
    baseline.update(run_id=adapter.campaign.manifest['run_id'],case_id=cid,
                    agent_id=adapter.campaign.manifest['campaign_agent_id'],
                    customer_phone='+'+raw_phone,customer_name=rows[0]['name'])
    adapter.state['full_history'] = baseline
    adapter._save()
    return baseline


def projection_transition(failed, recovered, *, owned_request_ids):
    """Partial native evidence only: same owned outbox row failed then delivered.

    The caller must independently read both snapshots. This predicate does not
    prove invocation ownership, reservation integrity or provider event delivery.
    """
    try:
        if not isinstance(failed, dict) or not isinstance(recovered, dict):
            return False
        if not isinstance(owned_request_ids, (set, frozenset)) or not owned_request_ids:
            return False
        if any(type(i) is not int or i <= 0 for i in owned_request_ids):
            return False
        for row in (failed, recovered):
            if (any(type(row[k]) is not int or row[k] <= 0 for k in ('id','request_id','attempts'))
                    or row['request_id'] not in owned_request_ids
                    or row['event_type'] != 'calendar_projection'):
                return False
        times = [datetime.fromisoformat(r['updated_at']) for r in (failed,recovered)]
        return (all(t.tzinfo is not None for t in times) and times[0] < times[1]
                and failed['status'] == 'PENDING'
                and isinstance(failed['error_log'], str) and bool(failed['error_log'].strip())
                and recovered['status'] == 'DELIVERED'
                and all(failed[k] == recovered[k] for k in ('id','request_id','event_type'))
                and recovered['attempts'] >= failed['attempts'])
    except (KeyError, TypeError, ValueError):
        return False


def observe_projection(adapter, *, request_ids):
    adapter._guard()
    if (not isinstance(request_ids, (set, frozenset)) or not request_ids
            or any(type(i) is not int or i <= 0 for i in request_ids)
            or not request_ids <= set(adapter.current_ids)):
        raise SimulationError('Projection observation requires exact registered owned request IDs')
    return medium._serial(medium._read(adapter.config, '''SELECT id,request_id,event_type,status,
        attempts,error_log,updated_at,payload FROM outbox_notifications
        WHERE request_id=ANY(%s) AND event_type='calendar_projection' ORDER BY id''',
        (sorted(request_ids),)))


def observe_history(adapter, *, customer_id, conversation_id):
    adapter._guard()
    if (type(customer_id) is not int or customer_id <= 0
            or not isinstance(conversation_id,str) or not conversation_id.strip()):
        raise SimulationError('Exact native customer and provider conversation identities are required')
    notes = medium._read(adapter.config, '''SELECT id,call_id,customer_id,summary,transcript,created_at
        FROM crm_notes WHERE customer_id=%s AND call_id=%s ORDER BY id''', (customer_id,conversation_id))
    events = medium._read(adapter.config, '''SELECT id,provider,event_id,payload_hash,status,updated_at,
        completed_at AT TIME ZONE current_setting('TimeZone') AS completed_at
        FROM webhook_events WHERE provider='elevenlabs' AND event_id=%s ORDER BY id''', (conversation_id,))
    audit = medium._read(adapter.config, '''SELECT provider,event_id,conversation_id,payload_hash,verified_at
        FROM authenticated_webhook_ingress WHERE provider='elevenlabs' AND event_id=%s''', (conversation_id,))
    return {'notes':medium._serial(notes),'events':medium._serial(events),'audit':medium._serial(audit),
            'authenticated_callback_provenance':'native_audit_requires_provider_join','case_verified':False}


def checks(adapter, cid, values, before, after, provider=None):
    adapter._guard()
    _case(cid)
    if cid != 'C50':
        return [check(cid + ' native causal provenance', False, REQUIREMENTS[cid])]
    try:
        from . import deployed_full_session as session
        reader=getattr(adapter,'native_session_credit_reader',session.native_credit_reader)
        if not callable(reader):
            return [check('C50 genuine native session accounting is unavailable',False)]
        report=session.reconcile(adapter,provider=provider,credit_reader=reader)
        return [check('C50 genuine native audited history',report.get('history_verified') is True)]
    except Exception:  # noqa: BLE001 - provider/session diagnostics may include credentials
        return [check('C50 genuine native session correlation unavailable',False)]


def bind_invocation(adapter, *, invocation_id, test_id):
    """Agent-test invocation identities cannot establish a genuine C50 session."""
    raise SimulationError('C50 requires a genuine provider conversation session; agent-test binding is insufficient')


def cleanup(adapter, cid):
    """No effects were created: never adopt or delete rows seen by these readers."""
    adapter._guard()
    _case(cid)
    return {'mutations': [], 'case_supported':False, 'requirement':REQUIREMENTS[cid]}


def verify_history(observation, provider_conversation, *, customer_id, conversation_id,
                   agent_id, baseline_note_ids, baseline_event_ids):
    """Join fresh independent provider GET, audit, replay state and owned CRM row.

    Caller must acquire provider_conversation through authenticated provider GET;
    test dictionaries are synthetic and do not activate deployed capability.
    """
    try:
        notes, events, audit = (observation[k] for k in ('notes','events','audit'))
        if len(notes) != 1 or len(events) != 1 or len(audit) != 1:
            return False
        note, event, ingress = notes[0],events[0],audit[0]
        verified, completed = [datetime.fromisoformat(v) for v in (ingress['verified_at'],event['completed_at'])]
        turns = provider_conversation['transcript']
        if not isinstance(turns,list) or not turns or any(not isinstance(t,dict) for t in turns):
            return False
        # Match the native webhook's formatting exactly. Provider tool-only
        # turns may omit message or carry null; neither is a failed callback.
        transcript = '\n'.join(
            f"{'User' if t.get('role', 'unknown') == 'user' else 'Agent'}: {t.get('message', '')}"
            for t in turns)
        return (verified.tzinfo is not None and completed.tzinfo is not None and verified <= completed
                and note['transcript'] == transcript and bool(transcript.strip())) and (type(customer_id) is int and customer_id > 0
                and isinstance(conversation_id,str) and bool(conversation_id)
                and isinstance(agent_id,str) and bool(agent_id)
                and provider_conversation['conversation_id'] == conversation_id
                and provider_conversation['agent_id'] == agent_id
                and provider_conversation['status'] == 'done'
                and type(note['id']) is int and note['id'] > 0 and note['id'] not in baseline_note_ids
                and type(event['id']) is int and event['id'] > 0 and event['id'] not in baseline_event_ids
                and type(note['customer_id']) is int and note['customer_id'] == customer_id
                and note['call_id'] == conversation_id
                and event['provider'] == ingress['provider'] == 'elevenlabs'
                and event['event_id'] == ingress['event_id'] == ingress['conversation_id'] == conversation_id
                and event['status'] == 'COMPLETED' and bool(event['completed_at'])
                and isinstance(event['payload_hash'],str) and len(event['payload_hash']) == 64
                and all(c in '0123456789abcdef' for c in event['payload_hash'])
                and event['payload_hash'] == ingress['payload_hash'] and bool(ingress['verified_at']))
    except (KeyError, TypeError, ValueError):
        return False


def history_baseline(adapter, *, customer_id):
    """Capture fresh pre-invocation IDs; never reconstruct them after the call."""
    adapter._guard()
    if type(customer_id) is not int or customer_id <= 0:
        raise SimulationError('Exact owned customer ID required for history baseline')
    notes = medium._read(adapter.config, 'SELECT id FROM crm_notes WHERE customer_id=%s ORDER BY id', (customer_id,))
    events = medium._read(adapter.config, "SELECT id FROM webhook_events WHERE provider='elevenlabs' ORDER BY id")
    return {'customer_id':customer_id,'baseline_note_ids':[r['id'] for r in notes],
            'baseline_event_ids':[r['id'] for r in events]}


def verify_native_history(observation,provider_conversation,*,dynamic_variables,expected_user_id,**binding):
    """Genuine session provenance comes from GET initiation data, never test IDs."""
    try:
        client_data=provider_conversation['conversation_initiation_client_data']
        actual=client_data['dynamic_variables']
        user_ids=[v for v in (provider_conversation.get('user_id'),client_data.get('user_id')) if v is not None]
        if (not isinstance(expected_user_id,str) or not expected_user_id or not user_ids
                or any(v!=expected_user_id for v in user_ids)):
            return False
        if (not isinstance(dynamic_variables,dict) or set(dynamic_variables)!={'run_id','case_id','session_nonce'}
                or dynamic_variables['case_id']!='C50'
                or any(not isinstance(v,str) or not v for v in dynamic_variables.values())
                or not isinstance(actual,dict) or any(actual.get(k)!=v for k,v in dynamic_variables.items())):
            return False
        return verify_history(observation,provider_conversation,**binding)
    except (KeyError,TypeError,ValueError):
        return False
