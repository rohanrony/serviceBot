"""Disabled native simulation controls; real bookings keep their existing owner.

Only a capability created by the authenticated lease endpoint can bind a newly
allocated request inside its booking transaction. Failures are controlled worker
faults and real response truncation, never claims about an external outage.
"""
import hashlib
import hmac
import json
import os
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg2 import sql

from serviceBot.db.connection import dict_cursor, get_db_connection

_CAPABILITY = ContextVar('simulation_fault_capability', default=None)


class FaultDenied(ValueError):
    pass


class ControlledCalendarFailure(RuntimeError):
    pass


def enabled():
    return os.getenv('SIMULATION_FAULTS_ENABLED') == 'true'


def authorize(authorization):
    secret = os.getenv('CRON_SECRET', '')
    if (not enabled() or not secret or not isinstance(authorization, str)
            or not hmac.compare_digest(authorization, 'Bearer ' + secret)):
        raise FaultDenied('Simulation fault control is unavailable')
    return secret


def _token(handle, secret):
    return hmac.new(secret.encode(), ('simulation-fault-v1:' + str(handle)).encode(), hashlib.sha256).hexdigest()


def verify_token(handle, token, secret):
    try:
        handle = str(uuid.UUID(str(handle)))
    except (ValueError, TypeError, AttributeError):
        raise FaultDenied('Invalid simulation handle') from None
    if not isinstance(token, str) or not hmac.compare_digest(token, _token(handle, secret)):
        raise FaultDenied('Invalid simulation lease')
    return handle


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _phone(value):
    digits=re.sub(r'\D','',value or '')
    if len(digits)==11 and digits.startswith('1'):
        return digits[1:]
    return digits if len(digits)==10 else ''


def _allowed(technician_id, phone):
    technicians = {value.strip() for value in os.getenv('SIMULATION_FAULT_TECHNICIAN_IDS', '').split(',') if value.strip()}
    phones = {_phone(value) for value in os.getenv('SIMULATION_FAULT_PHONE_NUMBERS', '').split(',') if value.strip()}
    if str(technician_id) not in technicians or len(_phone(phone)) != 10 or _phone(phone) not in phones:
        raise FaultDenied('Designated simulation technician and recipient are required')


def _journal(cur, handle, event):
    cur.execute('INSERT INTO simulation_fault_journal(handle,event) VALUES (%s,%s)', (str(handle), event))


def _lease(cur, handle, *, lock=False):
    cur.execute('SELECT *, expires_at>CURRENT_TIMESTAMP AS unexpired FROM simulation_fault_leases WHERE handle=%s' + (' FOR UPDATE' if lock else ''), (str(handle),))
    row = cur.fetchone()
    if not row:
        raise FaultDenied('Simulation lease not found')
    return dict(row)


def _require_supported_business_intake():
    # Fault arguments are immutable and do not yet collect configured intake.
    # Reject before resource creation or execution intent, rather than leaving
    # an unknown lease after the real voice owner rejects missing required data.
    from serviceBot.services.business_profile import validate_intake_data
    try:
        validate_intake_data({})
    except ValueError:
        raise FaultDenied('Native fault simulation does not support required business intake') from None


def create(*, run_id, mode, technician_id, phone, booking_time, secret, recovery_nonce=None):
    if (not enabled() or not secret or not isinstance(run_id, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id)
            or mode not in {'calendar_once','response_loss_once'} or type(technician_id) is not int):
        raise FaultDenied('Invalid simulation fixture')
    if recovery_nonce is not None and (not isinstance(recovery_nonce,str) or not re.fullmatch('[0-9a-f]{64}',recovery_nonce)):
        raise FaultDenied('Invalid simulation recovery identity')
    _allowed(technician_id, phone)
    _require_supported_business_intake()
    # Domain owner performs all appointment feasibility and lead-time validation.
    if not isinstance(booking_time, str) or len(booking_time) > 40:
        raise FaultDenied('Invalid simulation appointment time')
    handle = str(uuid.uuid4())
    name = 'simulation-fault-' + handle.replace('-', '')
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        cur.execute('SELECT 1 FROM simulation_fault_leases WHERE run_id=%s AND mode=%s', (run_id,mode))
        if cur.fetchone():
            raise FaultDenied('Existing simulation fixture cannot be adopted or recreated')
        cur.execute('SELECT id FROM staff_agents WHERE id=%s AND is_active=TRUE FOR SHARE', (technician_id,))
        if not cur.fetchone():
            raise FaultDenied('Designated technician is not active')
        cur.execute('SELECT id,name FROM customers WHERE regexp_replace(phone,\'[^0-9]\',\'\',\'g\') IN (%s,%s)', (_phone(phone),'1'+_phone(phone)))
        customers = cur.fetchall()
        if len(customers) != 1:
            raise FaultDenied('One unambiguous existing designated customer is required')
        customer = customers[0]
        cur.execute('SELECT make,model,year FROM vehicles WHERE customer_id=%s ORDER BY id DESC LIMIT 1', (customer['id'],))
        vehicle = cur.fetchone()
        if not vehicle:
            raise FaultDenied('Existing designated vehicle is required')
        cur.execute('INSERT INTO services(name,duration_minutes) VALUES (%s,60) RETURNING id', (name,))
        service_id = cur.fetchone()['id']
        cur.execute('SELECT to_jsonb(s) AS snapshot FROM services s WHERE id=%s', (service_id,))
        snapshot = cur.fetchone()['snapshot']
        cur.execute('INSERT INTO service_staff_agents(service_id,staff_agent_id) VALUES (%s,%s)', (service_id,technician_id))
        arguments = {'phone': phone, 'customer_name': customer['name'], 'service_type': name,
            'issue_description': name, 'booking_type':'appointment', 'booking_time':booking_time,
            'make':vehicle['make'],'model':vehicle['model'],'year':vehicle['year']}
        cur.execute("""INSERT INTO simulation_fault_leases(handle,run_id,mode,service_id,original_service_id,
            service_name,service_snapshot,technician_id,arguments,arguments_hash,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP+INTERVAL '15 minutes')""",
            (handle,run_id,mode,service_id,service_id,name,json.dumps(snapshot),technician_id,json.dumps(arguments),_digest(arguments)))
        _journal(cur,handle,'created')
        if recovery_nonce is not None:
            _journal(cur,handle,'create_intent:'+_digest(dict(run_id=run_id,mode=mode,technician_id=technician_id,
                phone=phone,booking_time=booking_time,recovery_nonce=recovery_nonce)))
        conn.commit()
    return {'success':True,'handle':handle,'lease_token':_token(handle,secret),
            'service_id':service_id,'service_name':name,'technician_id':technician_id,'mode':mode}


def recover_creation(*,run_id,mode,technician_id,phone,booking_time,recovery_nonce,secret):
    """Read the original committed create identity; never claim or replay a lease."""
    if (not enabled() or not secret or not isinstance(run_id,str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id)
            or mode not in {'calendar_once','response_loss_once'} or type(technician_id) is not int
            or not isinstance(phone,str) or not isinstance(booking_time,str)
            or not isinstance(recovery_nonce,str) or not re.fullmatch('[0-9a-f]{64}',recovery_nonce)):
        raise FaultDenied('Invalid original simulation recovery identity')
    expected=dict(run_id=run_id,mode=mode,technician_id=technician_id,phone=phone,
        booking_time=booking_time,recovery_nonce=recovery_nonce)
    digest=_digest(expected)
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        cur.execute('SELECT *, expires_at>CURRENT_TIMESTAMP AS unexpired FROM simulation_fault_leases WHERE run_id=%s AND mode=%s', (run_id,mode))
        rows=cur.fetchall()
        if len(rows)!=1:
            raise FaultDenied('Original simulation creation unavailable')
        lease=dict(rows[0])
        cur.execute('SELECT event FROM simulation_fault_journal WHERE handle=%s AND event=%s',
            (str(lease['handle']),'create_intent:'+digest))
        if (len(cur.fetchall())!=1 or lease['phase']!='prepared'
                or lease['technician_id']!=technician_id or lease['arguments']['phone']!=phone
                or lease['arguments']['booking_time']!=booking_time
                or _digest(lease['arguments'])!=lease['arguments_hash']
                or lease['service_id']!=lease['original_service_id']):
            raise FaultDenied('Original simulation creation identity changed')
        cur.execute('SELECT to_jsonb(s) AS snapshot FROM services s WHERE id=%s',(lease['service_id'],))
        row=cur.fetchone()
        if not row or row['snapshot']!=lease['service_snapshot']:
            raise FaultDenied('Original simulation service ownership changed')
        cur.execute('SELECT staff_agent_id FROM service_staff_agents WHERE service_id=%s',(lease['service_id'],))
        if [row['staff_agent_id'] for row in cur.fetchall()]!=[technician_id]:
            raise FaultDenied('Original simulation qualification changed')
        cur.execute('SELECT 1 FROM service_requests WHERE service_type=%s LIMIT 1',(lease['service_name'],))
        if cur.fetchone():
            raise FaultDenied('Original simulation service acquired a request')
    return {'success':True,'handle':str(lease['handle']),'lease_token':_token(lease['handle'],secret),
        'service_id':lease['service_id'],'service_name':lease['service_name'],'technician_id':technician_id,
        'mode':mode,'create_intent_hash':digest,'recovered_creation':True}


@contextmanager
def booking_capability(lease):
    token = _CAPABILITY.set({'handle':str(lease['handle']), 'arguments_hash':lease['arguments_hash']})
    try:
        yield
    finally:
        _CAPABILITY.reset(token)


def has_booking_capability():
    """Normal bookings retain their original SQL and do not read fault state."""
    return _CAPABILITY.get() is not None


def bind_booking(cursor, *, request_id, reservation_id, outbox_id, staff_agent_id, service_type, customer_phone):
    """Called using the booking owner's cursor BEFORE its successful commit."""
    capability = _CAPABILITY.get()
    if capability is None:
        return
    if not enabled():
        raise FaultDenied('Simulation capability disarmed during booking')
    from serviceBot.services.booking import parse_reservation_start
    lease = _lease(cursor,capability['handle'],lock=True)
    if (not lease['unexpired'] or lease['phase'] != 'executing'
            or lease['arguments_hash'] != capability['arguments_hash']
            or lease['service_name'] != service_type or lease['technician_id'] != staff_agent_id
            or _phone(lease['arguments']['phone']) != _phone(customer_phone)
            or request_id <= lease['request_watermark']):
        raise FaultDenied('Booking cannot adopt or modify another simulation resource')
    cursor.execute("""SELECT 1 FROM appointment_reservations WHERE id=%s AND service_request_id=%s
        AND staff_agent_id=%s AND status='ACTIVE' AND starts_at=%s::timestamp AND ends_at=starts_at+INTERVAL '60 minutes'""",
        (reservation_id,request_id,staff_agent_id,parse_reservation_start(lease['arguments']['booking_time'])))
    if not cursor.fetchone():
        raise FaultDenied('Simulation reservation differs from immutable fixture')
    cursor.execute("""SELECT service_id,staff_agent_id FROM service_staff_agents
        WHERE service_id=%s ORDER BY staff_agent_id FOR SHARE""", (lease['service_id'],))
    rows = cursor.fetchall()
    if len(rows) != 1 or rows[0]['staff_agent_id'] != staff_agent_id:
        raise FaultDenied('Simulation qualification changed')
    cursor.execute("SELECT payload FROM outbox_notifications WHERE id=%s AND request_id=%s AND event_type='calendar_projection'", (outbox_id,request_id))
    outbox = cursor.fetchone()
    if not outbox:
        raise FaultDenied('Simulation outbox identity unavailable')
    payload_hash = _digest(outbox['payload'])
    cursor.execute("""UPDATE simulation_fault_leases SET phase='bound',request_id=%s,reservation_id=%s,
        outbox_id=%s,outbox_payload_hash=%s,updated_at=CURRENT_TIMESTAMP WHERE handle=%s""",
        (request_id,reservation_id,outbox_id,payload_hash,str(lease['handle'])))
    _journal(cursor,lease['handle'],'booking_bound_in_transaction')


def begin_execute(handle, *, tool_payload=None):
    _require_supported_business_intake()
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        lease = _lease(cur,handle,lock=True)
        _allowed(lease['technician_id'],lease['arguments']['phone'])
        if tool_payload is not None:
            tool_payload = validate_tool_payload(lease, tool_payload)
            if lease['tool_payload_hash'] is not None and lease['tool_payload_hash']!=_digest(tool_payload):
                raise FaultDenied('Actual model retry payload differs from the bound invocation')
        if not enabled() or not lease['unexpired']:
            raise FaultDenied('Simulation lease expired or disarmed')
        if _digest(lease['arguments']) != lease['arguments_hash']:
            raise FaultDenied('Immutable simulation arguments changed')
        if lease['phase'] in {'bound','committed'}:
            return lease, False
        if lease['phase'] != 'prepared':
            raise FaultDenied('Simulation execution unknown or already started; reconcile without retry')
        # Sequence watermark excludes every already allocated original request ID.
        cur.execute('SELECT last_value,is_called FROM service_requests_id_seq')
        sequence = cur.fetchone()
        watermark = sequence['last_value'] if sequence['is_called'] else sequence['last_value'] - 1
        cur.execute("UPDATE simulation_fault_leases SET phase='executing',request_watermark=%s,updated_at=CURRENT_TIMESTAMP WHERE handle=%s", (watermark,str(handle)))
        if tool_payload is not None:
            cur.execute('UPDATE simulation_fault_leases SET tool_payload_hash=%s WHERE handle=%s', (_digest(tool_payload),str(handle)))
            _journal(cur,handle,'agent_payload_validated')
        _journal(cur,handle,'execution_intent')
        conn.commit()
        lease['phase']='executing'
        return lease, True


def finish_execute(handle, response):
    result = response.get('result') if isinstance(response,dict) else None
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        lease = _lease(cur,handle,lock=True)
        if (not isinstance(result,dict) or result.get('success') is not True
                or lease['phase'] != 'bound'
                or result.get('service_request_id') != lease['request_id']):
            cur.execute("UPDATE simulation_fault_leases SET phase='unknown',updated_at=CURRENT_TIMESTAMP WHERE handle=%s", (str(handle),))
            _journal(cur,handle,'execution_unknown')
            conn.commit()
            raise FaultDenied('Native booking response or binding unknown; reconcile without retry')
        lose = lease['mode']=='response_loss_once' and lease['unexpired'] and lease['response_loss_consumed_at'] is None
        cur.execute("""UPDATE simulation_fault_leases SET phase='committed',result=%s,
            response_loss_consumed_at=CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE response_loss_consumed_at END,
            updated_at=CURRENT_TIMESTAMP WHERE handle=%s""", (json.dumps(response),lose,str(handle)))
        _journal(cur,handle,'response_loss_committed' if lose else 'booking_committed')
        conn.commit()
    return lose


def mark_unknown(handle):
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        # A transactionally bound request is recoverable even if its HTTP result was lost.
        cur.execute("UPDATE simulation_fault_leases SET phase=CASE WHEN phase='executing' THEN 'unknown' ELSE phase END,updated_at=CURRENT_TIMESTAMP WHERE handle=%s", (str(handle),))
        _journal(cur,handle,'execution_interrupted')
        conn.commit()


def status(handle):
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        lease = _lease(cur,handle)
        evidence = {}
        if lease['request_id']:
            cur.execute("""SELECT sr.id,sr.status,ar.id AS reservation_id,ar.status AS reservation_status,
                ar.calendar_integration_status,o.id AS outbox_id,o.status AS outbox_status,o.attempts
                FROM service_requests sr JOIN appointment_reservations ar ON ar.service_request_id=sr.id
                JOIN outbox_notifications o ON o.id=%s
                WHERE sr.id=%s AND ar.id=%s AND sr.service_type=%s AND ar.staff_agent_id=%s""",
                (lease['outbox_id'],lease['request_id'],lease['reservation_id'],lease['service_name'],lease['technician_id']))
            row = cur.fetchone()
            if not row:
                raise FaultDenied('Bound simulation booking changed; reconciliation required')
            evidence = dict(row)
        cur.execute('SELECT event FROM simulation_fault_journal WHERE handle=%s ORDER BY id', (str(handle),))
        journal = [row['event'] for row in cur.fetchall()]
    return {'success':True,'handle':str(handle),'phase':lease['phase'],'unexpired':lease['unexpired'],
            'mode':lease['mode'],'request_id':lease['request_id'],'reservation_id':lease['reservation_id'],
            'outbox_id':lease['outbox_id'],'fault_consumed':lease['fault_consumed_at'] is not None,
            'response_loss_consumed':lease['response_loss_consumed_at'] is not None,
            'evidence':evidence,'journal':journal,'result':lease['result'],'retired_binding':lease['retired_binding'],
            'expires_at':lease['expires_at'].isoformat(),
            'agent_tool_verified':lease['tool_payload_hash'] is not None,'tool_payload_hash':lease['tool_payload_hash'],
            'lease_reconciliation':True,'core_generic_retry_proven':False}


def before_calendar_dispatch(outbox_id, request_id, payload):
    if not enabled() or payload.get('action','upsert') != 'upsert':
        return
    consumed = False
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        cur.execute("""SELECT * FROM simulation_fault_leases WHERE outbox_id=%s AND request_id=%s
            AND reservation_id=%s AND technician_id=%s AND mode='calendar_once'
            AND phase IN ('bound','committed') AND expires_at>CURRENT_TIMESTAMP
            AND fault_consumed_at IS NULL FOR UPDATE""",
            (outbox_id,request_id,payload.get('reservation_id'),payload.get('agent_id')))
        lease = cur.fetchone()
        if lease:
            if _digest(payload) != lease['outbox_payload_hash']:
                raise FaultDenied('Owned calendar payload changed')
            cur.execute("""SELECT 1 FROM service_requests sr JOIN appointment_reservations ar ON ar.service_request_id=sr.id
                JOIN services s ON s.id=%s WHERE sr.id=%s AND ar.id=%s AND sr.service_type=s.name
                AND s.name=%s AND ar.staff_agent_id=%s AND ar.status='ACTIVE'""",
                (lease['service_id'],request_id,lease['reservation_id'],lease['service_name'],lease['technician_id']))
            if not cur.fetchone():
                raise FaultDenied('Owned calendar fault binding changed')
            cur.execute('UPDATE simulation_fault_leases SET fault_consumed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE handle=%s', (str(lease['handle']),))
            _journal(cur,lease['handle'],'controlled_calendar_failure_consumed')
            conn.commit()
            consumed=True
    if consumed:
        raise ControlledCalendarFailure('Controlled native simulation worker projection failure (not a Google outage)')


def disarm(handle):
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        lease = _lease(cur,handle,lock=True)
        if lease['phase']=='executing':
            raise FaultDenied('In-flight execution cannot be cleaned; reconcile first')
        cur.execute("UPDATE simulation_fault_leases SET phase=CASE WHEN phase='cleaned' THEN phase ELSE 'disarmed' END,expires_at=LEAST(expires_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE handle=%s", (str(handle),))
        _journal(cur,handle,'disarmed')
        conn.commit()
    return {'success':True,'handle':str(handle),'disarmed':True,'cleanup_complete':False,
            'cleanup_blocker':'Owned booking/provider retirement must be verified before resource deletion; journal retained'}


def _reference_columns(cur):
    """Deterministic snapshot of service FKs and existing legacy identity columns."""
    cur.execute("""SELECT n.nspname AS schema,c.relname AS table,a.attname AS column
        FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=ANY(f.conkey)
        WHERE f.contype='f' AND f.confrelid='services'::regclass""")
    refs={(row['schema'],row['table'],row['column']) for row in cur.fetchall()}
    cur.execute("""SELECT table_schema AS schema,table_name AS table,column_name AS column
        FROM information_schema.columns WHERE table_schema=current_schema()
        AND column_name='service_id' AND data_type IN ('integer','bigint','smallint')""")
    refs.update((row['schema'],row['table'],row['column']) for row in cur.fetchall())
    return [{'schema':schema,'table':table,'column':column} for schema,table,column in sorted(refs)]


def cleanup(handle):
    """Remove only the owned catalog row after existing owners retire booking effects.

    Journal, booked request and reservation remain available as audit evidence.
    This function never deletes a shared technician/customer or provider event.
    """
    from serviceBot.services.booking import parse_reservation_start
    disarm(handle)  # Durable even when terminal-state checks below refuse cleanup.
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        cur.execute("SET LOCAL lock_timeout='2s'")
        refs=_reference_columns(cur)
        relations={('public',table) for table in ('services','service_staff_agents','service_requests',
            'appointment_reservations','outbox_notifications','simulation_fault_leases')}
        relations.update((row['schema'],row['table']) for row in refs)
        for schema,table in sorted(relations):
            cur.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(sql.Identifier(schema,table)))
        if refs != _reference_columns(cur):
            raise FaultDenied('Reference schema changed during cleanup; refuse deletion')
        lease=_lease(cur,handle,lock=True)
        if lease['phase']=='cleaned':
            return {'success':True,'handle':str(handle),'cleanup_complete':True,'journal_retained':True}
        if lease['phase']!='disarmed' or lease['request_watermark'] is not None and lease['request_id'] is None:
            raise FaultDenied('Unknown execution cannot be cleaned without reconciliation')
        cur.execute('SELECT to_jsonb(s) AS snapshot FROM services s WHERE id=%s FOR UPDATE',(lease['service_id'],))
        row=cur.fetchone()
        if not row or row['snapshot'] != lease['service_snapshot']:
            raise FaultDenied('Owned service changed; refuse cleanup')
        cur.execute('SELECT staff_agent_id FROM service_staff_agents WHERE service_id=%s',(lease['service_id'],))
        if [row['staff_agent_id'] for row in cur.fetchall()] != [lease['technician_id']]:
            raise FaultDenied('Owned qualification changed; refuse cleanup')
        cur.execute('SELECT id FROM service_requests WHERE service_type=%s',(lease['service_name'],))
        if {row['id'] for row in cur.fetchall()} != ({lease['request_id']} if lease['request_id'] else set()):
            raise FaultDenied('Service acquired an unowned request; refuse cleanup')
        if lease['request_id']:
            cur.execute("""SELECT 1 FROM service_requests sr JOIN appointment_reservations ar ON ar.service_request_id=sr.id
                WHERE sr.id=%s AND sr.status IN ('cancelled','cancelled_by_customer') AND ar.id=%s
                AND ar.status='CANCELLED' AND ar.calendar_integration_status='DELETED'
                AND ar.staff_agent_id=%s AND sr.staff_agent_id=%s AND ar.starts_at=%s::timestamp""",
                (lease['request_id'],lease['reservation_id'],lease['technician_id'],lease['technician_id'],
                    parse_reservation_start(lease['arguments']['booking_time'])))
            if not cur.fetchone():
                raise FaultDenied('Existing domain owner must cancel and retire the exact provider projection first')
            cur.execute("SELECT 1 FROM outbox_notifications WHERE request_id=%s AND status<>'DELIVERED' LIMIT 1",(lease['request_id'],))
            if cur.fetchone():
                raise FaultDenied('Owned outbox effects are not terminal; refuse cleanup')
        for ref in refs:
            if ref['schema']=='public' and ref['table'] in {'service_staff_agents','simulation_fault_leases'}:
                continue
            cur.execute(sql.SQL('SELECT 1 FROM {} WHERE {}=%s LIMIT 1').format(
                sql.Identifier(ref['schema'],ref['table']),sql.Identifier(ref['column'])),(lease['service_id'],))
            if cur.fetchone():
                raise FaultDenied('Owned service acquired references; refuse cleanup')
        cur.execute('DELETE FROM service_staff_agents WHERE service_id=%s AND staff_agent_id=%s',(lease['service_id'],lease['technician_id']))
        retired = {'request_id':lease['request_id'],'reservation_id':lease['reservation_id'],
            'outbox_id':lease['outbox_id'],'outbox_payload_hash':lease['outbox_payload_hash'],
            'terminal_domain_and_projection_verified':lease['request_id'] is not None}
        cur.execute("""UPDATE simulation_fault_leases SET service_id=NULL,phase='cleaned',
            request_id=NULL,reservation_id=NULL,outbox_id=NULL,outbox_payload_hash=NULL,
            retired_binding=%s,updated_at=CURRENT_TIMESTAMP WHERE handle=%s""",(json.dumps(retired),str(handle)))
        cur.execute('DELETE FROM services WHERE id=%s AND name=%s',(lease['service_id'],lease['service_name']))
        if cur.rowcount!=1:
            raise FaultDenied('Owned catalog deletion refused')
        _journal(cur,handle,'owned_service_cleaned_journal_retained')
        conn.commit()
    return {'success':True,'handle':str(handle),'cleanup_complete':True,'journal_retained':True}


def validate_tool_payload(lease, payload):
    """Reject a wrong model request/consent before the execution intent or booking.

    Flat tool arguments and the native wrapped envelope are accepted. Matching
    canonical arguments are forwarded to the real voice owner unchanged.
    """
    from serviceBot.services.booking import parse_reservation_start
    if not isinstance(payload, dict):
        raise FaultDenied('Actual model tool payload is required')
    if 'arguments' in payload:
        if set(payload)-{'name','arguments','tool_call_id'} or payload.get('name')!='create_service_request':
            raise FaultDenied('Only the owned create_service_request tool is permitted')
        arguments=payload['arguments']
    else:
        arguments=dict(payload)
        if arguments.pop('name','create_service_request')!='create_service_request':
            raise FaultDenied('Only the owned create_service_request tool is permitted')
    allowed={'phone','service_type','booking_time','booking_type','customer_consent_obtained',
        'customer_name','make','model','year','issue_description'}
    if not isinstance(arguments,dict) or set(arguments)-allowed:
        raise FaultDenied('Actual model arguments contain unsupported mutation fields')
    expected=lease['arguments']
    if (arguments.get('customer_consent_obtained') is not True
            or not isinstance(arguments.get('phone'),str)
            or _phone(arguments['phone'])!=_phone(expected['phone'])
            or arguments.get('service_type')!=expected['service_type']
            or arguments.get('booking_type')!='appointment'
            or not isinstance(arguments.get('booking_time'),str)):
        raise FaultDenied('Model phone/service/type/time and explicit consent must match the immutable fixture')
    try:
        if parse_reservation_start(arguments['booking_time'])!=parse_reservation_start(expected['booking_time']):
            raise ValueError
    except (ValueError,TypeError):
        raise FaultDenied('Model appointment time differs from the immutable fixture') from None
    for key in set(arguments)-{'phone','service_type','booking_time','booking_type','customer_consent_obtained'}:
        if arguments[key]!=expected[key]:
            raise FaultDenied('Model intake differs from the designated fixture')
    return {'name':'create_service_request','arguments':dict(arguments)}


def capabilities():
    """Authenticated caller only: read metadata; never claim, create or refresh."""
    _require_supported_business_intake()
    technicians=sorted({int(value.strip()) for value in os.getenv('SIMULATION_FAULT_TECHNICIAN_IDS','').split(',')
        if value.strip().isdigit() and int(value.strip())>0})
    phones={'+1'+_phone(value) for value in os.getenv('SIMULATION_FAULT_PHONE_NUMBERS','').split(',') if len(_phone(value))==10}
    with get_db_connection() as conn, dict_cursor(conn) as cur:
        cur.execute("""SELECT table_name,column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name IN ('simulation_fault_leases','simulation_fault_journal')""")
        columns={(row['table_name'],row['column_name']) for row in cur.fetchall()}
    required={('simulation_fault_leases',column) for column in ('handle','service_id','service_snapshot','phase',
        'request_id','reservation_id','outbox_id','outbox_payload_hash','tool_payload_hash','retired_binding')}
    required.add(('simulation_fault_journal','event'))
    return {'success':True,'capability':'owned-faults-v1','enabled':enabled(),
        'modes':['calendar_once','response_loss_once'],'schema_ready':required<=columns,
        'allowlisted_technician_ids':technicians,
        'allowlisted_phone_fingerprints':sorted(hashlib.sha256(phone.encode()).hexdigest() for phone in phones)}
