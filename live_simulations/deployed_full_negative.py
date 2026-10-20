"""Native negative-case observations; no provider outages or transfers invented."""
from __future__ import annotations

import re
from contextlib import nullcontext
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx

from . import deployed_medium as medium
from .core import SimulationError, fingerprint, secret
from .evidence import check
from .provider import ElevenLabs, empty_workflow

BUSINESS_TABLES = ('customers', 'vehicles', 'service_requests', 'appointment_reservations',
                   'appointment_reservation_segments', 'mock_calendar_slots', 'outbox_notifications',
                   'service_request_audit_log', 'sms_messages', 'sms_log', 'sms_reminders', 'sms_conversations')
_HANDOFF_NAMES = {'cba_webbook', 'cba_webhook', 'transfer_call', 'handoff'}
_NATIVE_TOOLS = _HANDOFF_NAMES | {'check_availability', 'create_service_request', 'get_customer_appointments',
    'reschedule_appointment', 'cancel_appointment', 'consolidate_appointment_service', 'book_appointment',
    'request_callback', 'query_knowledge_base', 'faq_lookup', 'get_service_fields', 'get_required_fields'}
C23_SETUP_BLOCKER = ('C23 native setup is blocked: no atomic conditional noncascading owned-technician cleanup exists')


def native_setup_allowed():
    """Compiled owned lifecycle exists; deployment opt-in/auth remain independent."""
    return True


class _ReadOnlyProvider(ElevenLabs):
    def request(self, method, path, payload=None, *, missing_ok=False):
        if method != 'GET' or payload is not None:
            raise SimulationError('Handoff capability observation permits provider GET only')
        result = super().request(method, path, missing_ok=missing_ok)
        if path.startswith('/v1/convai/tools/') and isinstance(result, dict) and result.get('response_mocks'):
            raise SimulationError('Mocked native handoff definitions cannot establish actual capability absence')
        return result


def unknown(result):
    return (isinstance(result, dict) and result.get('success') is False
            and result.get('error_code') == 'AVAILABILITY_UNKNOWN'
            and result.get('availability_status') == 'unknown'
            and type(result.get('available_slots')) is list and result['available_slots'] == []
            and result.get('retryable') is True)


def unavailable(result):
    return (isinstance(result, dict) and result.get('success') is False
            and result.get('handoff_status') == 'unavailable' and result.get('transfer_completed') is False
            and isinstance(result.get('summary'), str)
            and '- Business Hours Status: OPEN' in result['summary'].splitlines())


def footprint(adapter):
    # Fixed internal scopes, computed in one read-only statement. Only counts and
    # digests cross the database boundary; no customer/message bodies persist.
    statement = ' UNION ALL '.join(
        f"SELECT '{table}' AS scope,count(*) AS rows,md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text,'[]')) AS fingerprint FROM {table} t"
        for table in BUSINESS_TABLES)
    service_ids = [item['id'] for item in adapter.state['services'].values()]
    owned_service_id = adapter.state.get('full_unconnected_staff', {}).get('service_id')
    if type(owned_service_id) is int and owned_service_id > 0:
        service_ids.append(owned_service_id)
    staff_id = adapter.state.get('full_unconnected_staff', {}).get('id', -1)
    for scope, source in (
        ('original_services', 'SELECT * FROM services WHERE NOT(id=ANY(%s))'),
        ('original_service_mappings', 'SELECT * FROM service_staff_agents WHERE NOT(service_id=ANY(%s))'),
        ('original_staff', 'SELECT * FROM staff_agents WHERE id<>%s'),
        ('oauth_identity', 'SELECT agent_id,provider,google_account_id,email,granted_scopes FROM user_google_accounts'),
    ):
        statement += f" UNION ALL SELECT '{scope}' AS scope,count(*) AS rows,md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text,'[]')) AS fingerprint FROM ({source}) t"
    scopes = {*BUSINESS_TABLES, 'original_services', 'original_service_mappings', 'original_staff', 'oauth_identity'}
    rows = medium._read(adapter.config, statement, (service_ids, service_ids, staff_id))
    if (len(rows) != len(scopes) or {r.get('scope') for r in rows} != scopes
            or any(type(r.get('rows')) is not int or r['rows'] < 0
                   or not isinstance(r.get('fingerprint'), str)
                   or not re.fullmatch('[0-9a-f]{32}', r['fingerprint']) for r in rows)):
        raise SimulationError('Negative-case business baseline is unavailable')
    return sorted(rows, key=lambda row: row['scope'])


def _block(adapter, message):
    adapter.state['blocked'] = True
    adapter._save()
    raise SimulationError(message)


def _record(adapter, cid):
    return adapter.state.setdefault('full_negative_cases', {}).setdefault(cid, {})


def observe(adapter, cid, name, arguments):
    adapter._guard()
    record = _record(adapter, cid)
    before = footprint(adapter)
    if before != record['business_baseline']:
        _block(adapter, 'Negative-case business state changed; stop without cleanup writes')
    observation = {'name': name, 'status': 'intent', 'arguments_fingerprint': fingerprint(arguments)}
    record.setdefault('observations', []).append(observation)
    adapter._save()
    try:
        response = adapter.client.post(adapter.config['deployed_url'].rstrip('/') + '/api/v1/voice/tools',
            json={'name': name, 'arguments': arguments}, timeout=10)
        response.raise_for_status()
        result = response.json()['result']
    except Exception:  # noqa: BLE001 - unknown native response can hide an effect; never retry
        observation['status'] = 'unknown'
        _block(adapter, 'Negative-case native observation is unknown; reconcile without retry')
    if footprint(adapter) != before:
        observation['status'] = 'unexpected_effect'
        _block(adapter, 'Negative-case native observation changed business state')
    valid = unknown(result) if cid == 'C23' else unavailable(result)
    observation.update(status='observed', exact_negative_result=valid,
                       result_fingerprint=fingerprint(result), no_business_effects=True)
    adapter._save()
    if not valid:
        raise SimulationError('Exact structured unknown/unavailable native response is required')
    return observation


def _resolved_handoff(adapter):
    identifier = adapter.campaign.manifest.get('campaign_agent_id') or adapter.config.get('agent_id')
    if not isinstance(identifier, str) or not identifier:
        raise SimulationError('Actual handoff agent identity is required')
    supplied = getattr(adapter, 'provider_client', None)
    context = nullcontext(supplied) if supplied is not None else httpx.Client(
        timeout=30, trust_env=False, follow_redirects=False)
    with context as client:
        if client.follow_redirects or 'xi-api-key' in client.headers:
            raise SimulationError('Provider observation requires isolated per-request credentials and no redirects')
        provider = _ReadOnlyProvider(secret(adapter.config, 'elevenlabs_key'), client=client)
        agent = provider.agent(identifier)
        if not isinstance(agent, dict) or agent.get('agent_id') != identifier or not empty_workflow(agent.get('workflow')):
            raise SimulationError('Actual handoff routing capability is unknown')
        resolved = provider.resolve_reference(agent)
    return identifier, agent, resolved


def handoff_capability(adapter):
    """Observe real referenced definitions; flags and supplied receipts cannot pass."""
    identifier, agent, resolved = _resolved_handoff(adapter)
    native_agent = resolved.get('conversation_config', {}).get('agent', {})
    subagents = native_agent.get('subagent_config')
    if subagents is not None and (not isinstance(subagents, dict)
            or set(subagents) != {'agents', 'self_subagent'} or subagents['agents'] != []
            or subagents['self_subagent'] is not None):
        raise SimulationError('Actual handoff subagent capability is configured or unknown')
    prompt = native_agent.get('prompt', {})
    builtins = prompt.get('built_in_tools')
    if builtins is not None:
        if not isinstance(builtins, dict):
            raise SimulationError('Actual agent built-in capability map is malformed')
        for name, tool in builtins.items():
            if tool is None:
                continue
            # A transfer-key value is a configured capability even when its
            # object claims a harmless type. Disabled built-ins must be null.
            if (name not in {'end_call', 'skip_turn', 'language_detection'}
                    or not isinstance(tool, dict) or tool.get('type') != 'system'
                    or not isinstance(tool.get('params'), dict)
                    or tool['params'].get('system_tool_type') != name):
                raise SimulationError('Actual agent has a transfer or unknown built-in capability')
    tools = prompt.get('tools')
    if not isinstance(tools, list) or not tools:
        raise SimulationError('Actual handoff tool definitions are unavailable')
    origin = urlsplit(adapter.config['deployed_url'])
    handoffs = []
    for tool in tools:
        if tool.get('type') == 'system':
            if tool.get('params', {}).get('system_tool_type') not in {'end_call', 'skip_turn', 'language_detection'}:
                raise SimulationError('Actual agent has a transfer or unknown system capability')
            continue
        if tool.get('type') != 'webhook' or tool.get('name') not in _NATIVE_TOOLS:
            raise SimulationError('Actual agent has an unknown transfer-capable tool')
        schema = tool.get('api_schema', {})
        target = urlsplit(schema.get('url', ''))
        query = parse_qs(target.query, keep_blank_values=True)
        if ((target.scheme, target.netloc) != (origin.scheme, origin.netloc)
                or target.username or target.password or target.fragment or target.path != '/api/v1/voice/tools'
                or schema.get('method') != 'POST' or query not in ({}, {'name': [tool.get('name')]})):
            raise SimulationError('Actual agent has external or unknown transfer routing')
        if tool.get('name') in _HANDOFF_NAMES:
            handoffs.append(tool['name'])
    if len(handoffs) != 1:
        raise SimulationError('One exact native unavailable-handoff webhook is required')
    # Provider operation metadata (usage, last_called, update clocks) is not behavior.
    # Keep the complete material scopes, including resolved auth and subagents.
    scopes = ('conversation_config', 'platform_settings', 'workflow', 'name')
    return {'agent_id': identifier,
            'agent_fingerprint': fingerprint({key: agent.get(key) for key in scopes}),
            'resolved_fingerprint': fingerprint({key: resolved.get(key) for key in scopes}),
            'tool_name': handoffs[0]}


def _verify_unconnected(adapter, *, active, mapped):
    owned = adapter.state['full_unconnected_staff']
    rows = medium._read(adapter.config, """SELECT sa.id,sa.name,sa.email,sa.phone_number,sa.is_active,
        (SELECT count(*) FROM service_requests r WHERE r.staff_agent_id=sa.id) AS requests,
        (SELECT count(*) FROM appointment_reservations r WHERE r.staff_agent_id=sa.id) AS reservations,
        (SELECT count(*) FROM user_google_accounts g WHERE g.agent_id=sa.id) AS oauth,
        (SELECT count(*) FROM oauth_states o WHERE o.agent_id=sa.id) AS oauth_states,
        (SELECT count(*) FROM mock_calendar_slots s WHERE s.staff_agent_id=sa.id) AS slots,
        COALESCE((SELECT array_agg(m.service_id ORDER BY m.service_id) FROM service_staff_agents m
          WHERE m.staff_agent_id=sa.id),'{}'::integer[]) AS mappings
        FROM staff_agents sa WHERE sa.id=%s""", (owned['id'],))
    if (len(rows) != 1 or any(rows[0].get(key) != owned[key] for key in ('id', 'name', 'email', 'phone_number'))
            or rows[0].get('is_active') is not active
            or any(rows[0].get(key) != 0 for key in ('requests', 'reservations', 'oauth', 'oauth_states', 'slots'))
            or rows[0].get('mappings') != mapped):
        _block(adapter, 'Owned unconnected technician changed; refuse unsafe mutation or cleanup')


def arrange_unknown(adapter, values):
    if not native_setup_allowed():
        raise SimulationError(C23_SETUP_BLOCKER)
    policy = adapter._policy()
    when = medium._dt(values['appointment_time'], adapter.config)
    now = medium._dt(medium._now(adapter.config), adapter.config)
    lead = policy.get('min_booking_buffer_hours')
    if (type(lead) not in (int, float) or not 0 <= lead < float('inf') or when <= now
            or when < now + timedelta(hours=lead)
            or when.weekday() not in policy['business_days'] or when.minute % 30 or when.second or when.microsecond
            or when.hour < policy['business_hours_start']
            or when + timedelta(hours=1) > when.replace(hour=0, minute=0) + timedelta(hours=policy['business_hours_end'])):
        raise SimulationError('Unknown-calendar fixture requires a future locally feasible native interval')
    if adapter.state.get('full_unconnected_staff'):
        raise SimulationError('Existing unconnected technician fixture cannot be adopted or repeated')
    owned = create_owned_staff(adapter)
    _verify_unconnected(adapter, active=True, mapped=[owned['service_id']])
    arguments = {'service_type': owned['service_name'], 'booking_type': 'appointment',
                 'preferred_date': when.date().isoformat(), 'preferred_time': when.strftime('%I:%M %p')}
    _record(adapter, 'C23')['arguments'] = arguments
    adapter._save()
    observe(adapter, 'C23', 'check_availability', arguments)


def arrange(adapter, cid, values):
    record = _record(adapter, cid)
    if record:
        raise SimulationError('Negative-case observation cannot be rebased or repeated')
    record['business_baseline'] = footprint(adapter)
    adapter._save()
    if cid == 'C23':
        arrange_unknown(adapter, values)
    else:
        capability = handoff_capability(adapter)
        arguments = {'phone': values['customer_phone'], 'summary_text': 'Caller requests a human; callback declined.'}
        record.update(capability=capability, arguments=arguments)
        adapter._save()
        observe(adapter, cid, capability['tool_name'], arguments)


def checks(adapter, cid, provider=None):
    record = _record(adapter, cid)
    if cid == 'C23':
        _verify_unconnected(adapter, active=True, mapped=[adapter.state['full_unconnected_staff']['service_id']])
        name = 'check_availability'
    else:
        actual = handoff_capability(adapter)
        if actual != record.get('capability'):
            _block(adapter, 'Actual handoff capability changed since arrangement')
        name = actual['tool_name']
    observe(adapter, cid, name, record['arguments'])
    proof = [check('actual conversation tool call and result correlation remains unverified', False)]
    if provider is not None:
        from .deployed_full_provenance import negative_checks
        proof = negative_checks(adapter, cid, provider)
    return [
            check('exact native structured unknown' if cid == 'C23' else 'actual open-window unavailable handoff',
                  all(o.get('status') == 'observed' and o.get('exact_negative_result') is True
                      and o.get('no_business_effects') is True for o in record['observations'])),
            check('no changes in observed local request reservation audit outbox message or calendar tables',
                  footprint(adapter) == record['business_baseline'])] + proof


def cleanup(adapter):
    if adapter.current_case not in {'C23', 'C47'}:
        return
    cid = adapter.current_case
    record = _record(adapter, cid)
    if footprint(adapter) != record['business_baseline']:
        _block(adapter, 'Negative-case cleanup cannot change unexplained business effects')
    if cid == 'C23':
        if not adapter.state.get('full_unconnected_staff'):
            return
        cleanup_owned_staff(adapter)


def before_cleanup(adapter):
    if adapter.current_case not in {'C23', 'C47'}:
        return
    adapter._guard()
    record = _record(adapter, adapter.current_case)
    if footprint(adapter) != record['business_baseline']:
        _block(adapter, 'Negative-case cleanup cannot change unexplained business effects')
    if adapter.current_case == 'C23':
        owned = adapter.state.get('full_unconnected_staff')
        if not owned:
            return
        mapped = [owned['service_id']]
        _verify_unconnected(adapter, active=not owned['cleanup_complete'], mapped=mapped)


def _staff_lifecycle_request(adapter, action, body):
    """Authenticated isolated transport; journal contains no bearer or receipt."""
    adapter._guard()
    auth = secret(adapter.config, 'simulation_staff_cron_secret')
    operations = adapter.state.setdefault('operations', [])
    if any(op.get('owned_staff_action') == action for op in operations):
        raise SimulationError('Owned staff lifecycle cannot be replayed; reconcile existing intent')
    operation = {'owned_staff_action': action, 'status': 'intent',
                 'body_fingerprint': fingerprint(body)}
    if action == 'create':
        operation.update(run_id=body['run_id'], intent_id=body['intent_id'])
    operations.append(operation)
    adapter._save()
    supplied = getattr(adapter, 'simulation_staff_client', None)
    context = nullcontext(supplied) if supplied is not None else httpx.Client(
        trust_env=False, follow_redirects=False)
    try:
        with context as client:
            if (client.follow_redirects or getattr(client, '_trust_env', True)
                    or 'authorization' in client.headers or 'xi-api-key' in client.headers):
                raise SimulationError('Owned staff requires isolated per-request credentials')
            suffix = '/cleanup' if action == 'cleanup' else ''
            response = client.post(adapter.config['deployed_url'].rstrip('/') +
                '/api/v1/portal/internal/simulation-staff' + suffix,
                json=body, headers={'Authorization': 'Bearer ' + auth},
                timeout=medium._native_mutation_timeout(adapter.config))
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or result.get('success') is not True:
                raise SimulationError('Owned staff lifecycle response is unknown')
    except Exception:  # noqa: BLE001 - retain unknown effects without replaying a write
        _staff_unknown(adapter, operation, 'Owned staff lifecycle effect unknown; reconcile without replay')
    operation['status'] = 'response_received'
    adapter._save()
    return result, operation


def create_owned_staff(adapter):
    """Reviewed lifecycle building block; C23 admission guard remains separate."""
    from pathlib import Path

    if adapter.state.get('full_unconnected_staff'):
        raise SimulationError('Existing technician fixture cannot be adopted')
    path = Path(adapter.campaign.folder) / 'c23-owned-staff-receipt.json'
    if path.exists() or path.is_symlink():
        raise SimulationError('Existing owned fixture receipt requires reconciliation')
    run_id = adapter.campaign.manifest['run_id']
    from uuid import uuid4
    intent_id = uuid4().hex
    result, operation = _staff_lifecycle_request(adapter, 'create', {'run_id': run_id, 'intent_id': intent_id})
    return _accept_staff(adapter, result, operation, path)


def _staff_owner(operation):
    return {key: operation.get(key) for key in ('owned_staff_action', 'run_id', 'intent_id', 'body_fingerprint')} | {'kind': 'staff'}


def _staff_unknown(adapter, operation, message):
    if not adapter.state.get('blocked'):
        adapter.state['blocked_operation_owner'] = _staff_owner(operation)
    operation['status'] = 'unknown'
    _block(adapter, message)


def _accept_staff(adapter, result, operation, path):
    from .core import private_json
    run_id = operation['run_id']
    if (result.get('intent_id') != operation['intent_id'] or result.get('run_id') != run_id
            or any(type(result.get(k)) is not int or result[k] <= 0 for k in ('staff_id', 'service_id'))
            or any(not isinstance(result.get(k), str) or not result[k] for k in ('name','service_name','receipt'))
            or result['staff_id'] in adapter.config.get('deployed_medium', {}).get('technician_ids', [])):
        _staff_unknown(adapter, operation, 'Owned fixture identity unknown; reconcile without replay')
    try:
        if path.exists() or path.is_symlink():
            import json
            if path.is_symlink() or path.stat().st_mode & 0o077 or json.loads(path.read_text()) != {'receipt': result['receipt']}:
                raise SimulationError('Existing private receipt does not match original intent')
        else:
            private_json(path, {'receipt': result['receipt']})
    except Exception:  # noqa: BLE001 - missing receipt prevents safe ownership adoption
        _staff_unknown(adapter, operation, 'Owned fixture private receipt unavailable; reconcile without replay')
    owned = {'id': result['staff_id'], 'name': result['name'], 'email': None, 'phone_number': None,
             'service_id': result['service_id'], 'service_name': result['service_name'],
             'receipt_fingerprint': fingerprint(result['receipt']), 'cleanup_complete': False}
    adapter.state['full_unconnected_staff'] = owned
    operation.update(status='observed', staff_id=owned['id'], service_id=owned['service_id'])
    adapter._save()
    return owned


def cleanup_owned_staff(adapter):
    import json
    from pathlib import Path
    owned = adapter.state['full_unconnected_staff']
    path = Path(adapter.campaign.folder) / 'c23-owned-staff-receipt.json'
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise SimulationError('Owned fixture private receipt is unsafe')
    receipt = json.loads(path.read_text())['receipt']
    if fingerprint(receipt) != owned['receipt_fingerprint']:
        raise SimulationError('Owned fixture receipt changed')
    result, operation = _staff_lifecycle_request(adapter, 'cleanup', {'receipt': receipt})
    if result.get('staff_id') != owned['id'] or result.get('service_id') != owned['service_id']:
        _staff_unknown(adapter, operation, 'Owned fixture cleanup identity unknown; reconcile without replay')
    owned['cleanup_complete'] = True
    operation.update(status='observed', staff_id=owned['id'], service_id=owned['service_id'])
    adapter._save()
    return result


def recover_owned_staff(adapter):
    """Read only recovery of the exact durable create intent, never a create retry."""
    from pathlib import Path
    operations = adapter.state.get('operations', [])
    candidates = [op for op in operations if op.get('owned_staff_action') == 'create']
    if len(candidates) != 1:
        raise SimulationError('Exactly one saved owned staff creation intent is required')
    operation = candidates[0]
    body = {key: operation.get(key) for key in ('run_id', 'intent_id')}
    if (not isinstance(body['run_id'], str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}', body['run_id']) is None
            or body['run_id'] != adapter.campaign.manifest['run_id']
            or not isinstance(body['intent_id'], str)
            or re.fullmatch(r'[0-9a-f]{32}', body['intent_id']) is None
            or fingerprint(body) != operation.get('body_fingerprint')):
        raise SimulationError('Saved owned staff creation intent changed')
    supplied = getattr(adapter, 'simulation_staff_client', None)
    context = nullcontext(supplied) if supplied is not None else httpx.Client(trust_env=False, follow_redirects=False)
    auth = secret(adapter.config, 'simulation_staff_cron_secret')
    with context as client:
        if (client.follow_redirects or getattr(client, '_trust_env', True)
                or 'authorization' in client.headers or 'xi-api-key' in client.headers):
            raise SimulationError('Owned staff requires isolated per-request credentials')
        response = client.get(adapter.config['deployed_url'].rstrip('/') +
            '/api/v1/portal/internal/simulation-staff/recover/' + body['run_id'],
            params={'intent_id': body['intent_id']}, headers={'Authorization': 'Bearer ' + auth},
            timeout=medium._native_mutation_timeout(adapter.config))
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict) or result.get('success') is not True:
        raise SimulationError('Original owned staff intent could not be recovered')
    owned = _accept_staff(adapter, result, operation, Path(adapter.campaign.folder) / 'c23-owned-staff-receipt.json')
    if result.get('cleanup_complete') is True:
        owned['cleanup_complete'] = True
        cleanups = [op for op in operations if op.get('owned_staff_action') == 'cleanup']
        if len(cleanups) == 1 and cleanups[0].get('body_fingerprint') == fingerprint({'receipt': result['receipt']}):
            cleanup = cleanups[0]
            cleanup['status'] = 'observed'
            if adapter.state.get('blocked_operation_owner') == _staff_owner(cleanup):
                operation = cleanup
    if (adapter.state.get('blocked_operation_owner') == _staff_owner(operation)
            and not any(op.get('status') in {'intent', 'unknown', 'response_received', 'ambiguous'}
                        for op in operations if op is not operation)):
        adapter.state['blocked'] = False
        adapter.state.pop('blocked_operation_owner', None)
    adapter._save()
    return owned


def pending_owned_staff_recovery(adapter):
    return any(op.get('owned_staff_action') in {'create', 'cleanup'}
               and (op.get('status') in {'intent', 'unknown', 'response_received'}
                    or (adapter.state.get('blocked') is True
                        and adapter.state.get('blocked_operation_owner') == _staff_owner(op)))
               for op in adapter.state.get('operations', []))
