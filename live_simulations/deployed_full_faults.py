"""Owned C35/C36 native controls; no provider writes or automatic live admission.

The descriptor is a proposal for a separately verified owned clone. Runtime
acceptance requires actual model tool arguments, independent PostgreSQL state,
provider invocation/URL correlation and observed native transitions.
"""
import hashlib
import json
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import deployed_medium as medium
from .core import SimulationError, fingerprint, private_json, secret
from .evidence import check

BASE = '/api/v1/portal/internal/simulation-faults'
MODES = {'C35':'calendar_once','C36':'response_loss_once'}
SUPPORTED_CASE_IDS = frozenset(MODES)


def _record(adapter,cid):
    if cid not in MODES:
        raise SimulationError('Unsupported owned native fault case')
    return adapter.state.setdefault('full_faults',{}).setdefault(cid,{})


def _block(adapter,message):
    adapter.state['blocked']=True
    adapter._save()
    raise SimulationError(message)


def _origin(adapter):
    value=adapter.config['deployed_url'].rstrip('/')
    parsed=urlsplit(value)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path
            or parsed.scheme not in {'https','http'}
            or parsed.scheme=='http' and parsed.hostname not in {'localhost','127.0.0.1','::1'}):
        raise SimulationError('Fault controls require the exact configured native origin')
    return value


def _private_path(adapter,cid):
    return Path(adapter.campaign.folder)/(cid.lower()+'-fault-lease.json')


def _token(adapter,cid):
    path=_private_path(adapter,cid)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise SimulationError('Fault lease private token file is missing or unsafe')
    value=json.loads(path.read_text())['lease_token']
    if not isinstance(value,str) or fingerprint(value)!=_record(adapter,cid)['token_fingerprint']:
        raise SimulationError('Fault lease token changed')
    return value


def _request(adapter,cid,method,suffix='',body=None,*,action=None):
    adapter._guard()
    if adapter.state.get('blocked'):
        raise SimulationError('Unknown owned fault effect must be reconciled before replay')
    auth=secret(adapter.config,'simulation_faults_cron_secret')
    headers={'Authorization':'Bearer '+auth}
    if suffix:
        headers['X-Simulation-Lease']=_token(adapter,cid)
    operation=None
    if method!='GET':
        action=action or suffix
        if any(op.get('fault_case')==cid and op.get('fault_action')==action
               for op in adapter.state.setdefault('operations',[])):
            raise SimulationError('Fault control intent cannot be replayed')
        operation={'fault_case':cid,'fault_action':action,'status':'intent','body_fingerprint':fingerprint(body)}
        adapter.state['operations'].append(operation)
        adapter._save()
    supplied=getattr(adapter,'fault_client',None)
    context=nullcontext(supplied) if supplied is not None else httpx.Client(trust_env=False,follow_redirects=False)
    try:
        with context as client:
            if (client.follow_redirects or getattr(client,'_trust_env',True)
                    or 'authorization' in client.headers or 'x-simulation-lease' in client.headers
                    or 'xi-api-key' in client.headers):
                raise SimulationError('Fault controls require isolated per-request credentials')
            response=client.request(method,_origin(adapter)+BASE+suffix,json=body,headers=headers,
                timeout=medium._native_mutation_timeout(adapter.config))
            response.raise_for_status()
            result=response.json()
            if not isinstance(result,dict) or result.get('success') is not True:
                raise SimulationError('Native fault control response unavailable')
    except Exception:  # noqa: BLE001 - unknown effects must stop without replay
        if operation is not None:
            operation['status']='unknown'
            _block(adapter,'Owned fault control effect unknown; reconcile without replay')
        raise SimulationError('Native fault read-back unavailable') from None
    if operation is not None:
        operation['status']='response_received'
        adapter._save()
    return result


def arrange(adapter,cid,values):
    adapter._guard()
    record=_record(adapter,cid)
    if record or _private_path(adapter,cid).exists() or _private_path(adapter,cid).is_symlink():
        raise SimulationError('Existing fault fixture cannot be arranged or replayed')
    if getattr(adapter,'current_ids',set()):
        raise SimulationError('Previous native booking effects must be cleaned first')
    technicians=adapter.config['deployed_medium']['technician_ids']
    phone=values['customer_phone']
    when=values['appointment_time']
    if not technicians or not isinstance(phone,str) or not isinstance(when,str):
        raise SimulationError('Actual canonical phone/time/designated technician required')
    prerequisites(adapter,cid,values)
    expected={'run_id':adapter.campaign.manifest['run_id'],'mode':MODES[cid],
        'technician_id':technicians[0],'phone':phone,'booking_time':when}
    record.update(status='creating',expected=expected,observations=[])
    adapter._save()
    result=_request(adapter,cid,'POST',body=expected,action='create')
    try:
        handle=str(uuid.UUID(result['handle']))
        if (result['mode']!=MODES[cid] or result['technician_id']!=technicians[0]
                or type(result['service_id']) is not int or result['service_id']<=0
                or not isinstance(result['service_name'],str) or not result['service_name']
                or not isinstance(result['lease_token'],str) or not result['lease_token']):
            raise ValueError
        if result['service_id'] in {v['id'] for v in adapter.state.get('services',{}).values()}:
            raise ValueError
        private_json(_private_path(adapter,cid),{'lease_token':result['lease_token']})
    except Exception:  # noqa: BLE001 - incomplete resource identity cannot be adopted
        _block(adapter,'Fault fixture creation identity/token unknown; reconcile without replay')
    record.update(status='prepared',handle=handle,service_id=result['service_id'],service_name=result['service_name'],
        token_fingerprint=fingerprint(result['lease_token']))
    adapter.state['operations'][-1]['status']='observed'
    adapter._save()
    return {'service_name':record['service_name'],'service_id':record['service_id'],
            'customer_phone':phone,'appointment_time':when,'booking_type':'appointment'}


def tool_target_descriptor(adapter,cid):
    record=_record(adapter,cid)
    _token(adapter,cid)  # Verify the private artifact without returning its secret.
    expected=record['expected']
    properties={key:{'type':'string'} for key in ('phone','service_type','booking_time','booking_type')}
    properties['customer_consent_obtained']={'type':'boolean','description':'True only after the caller explicitly confirms this exact booking.'}
    return {'name':'create_service_request','url':_origin(adapter)+BASE+'/'+record['handle']+'/tool','method':'POST',
        'credential_bindings':{'authorization_env':adapter.config['secrets']['simulation_faults_cron_secret'],
            'authorization_prefix':'Bearer ','lease_token_file':str(_private_path(adapter,cid)),'lease_header':'X-Simulation-Lease'},
        'immutable_arguments':{'phone':expected['phone'],'service_type':record['service_name'],
            'booking_time':expected['booking_time'],'booking_type':'appointment'},
        'request_schema':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False},
        'requires_owned_clone_readback':True,'operator_execute_is_agent_proof':False}


def prepare_case_agent(adapter,cid):
    """Return descriptor only. Root owns clone-only application and exact readback."""
    return tool_target_descriptor(adapter,cid)


def _database(adapter,cid):
    record=_record(adapter,cid)
    rows=medium._read(adapter.config,"""SELECT l.handle::text AS handle,l.run_id,l.mode,l.service_id,l.service_name,
        l.technician_id,l.phase,l.request_watermark,l.request_id,l.reservation_id,l.outbox_id,l.tool_payload_hash,
        l.fault_consumed_at,l.response_loss_consumed_at,l.expires_at>CURRENT_TIMESTAMP AS unexpired,
        l.arguments,l.retired_binding,sr.status AS request_status,ar.status AS reservation_status,
        ar.calendar_integration_status AS projection_status,o.status AS outbox_status,o.attempts,
        (SELECT count(*) FROM service_requests r WHERE r.service_type=l.service_name) AS request_count,
        (SELECT count(*) FROM outbox_notifications n WHERE n.request_id=l.request_id AND n.status<>'DELIVERED') AS unsettled_outbox
        FROM simulation_fault_leases l LEFT JOIN service_requests sr ON sr.id=l.request_id
        LEFT JOIN appointment_reservations ar ON ar.id=l.reservation_id
        LEFT JOIN outbox_notifications o ON o.id=l.outbox_id WHERE l.handle=%s""",(record['handle'],))
    if len(rows)!=1:
        raise SimulationError('Exact native fault lease is unavailable')
    row=medium._serial(rows[0])
    expected=record['expected']
    if (row['handle']!=record['handle'] or row['run_id']!=expected['run_id'] or row['mode']!=MODES[cid]
            or row['service_name']!=record['service_name'] or row['technician_id']!=expected['technician_id']
            or row['arguments']['phone']!=expected['phone'] or row['arguments']['booking_time']!=expected['booking_time']
            or row['phase']!='cleaned' and row['service_id']!=record['service_id']):
        _block(adapter,'Owned native fault lease identity changed')
    if row['request_id']:
        if (type(row['request_id']) is not int or row['request_id'] in adapter.original_ids
                or row['request_id']<=row['request_watermark'] or row['request_count']!=1
                or not row['reservation_id'] or not row['outbox_id']
                or record.get('request_id') not in (None,row['request_id'])):
            _block(adapter,'Fault booking is not one exact new owned native transaction')
    elif row['request_count'] and row['phase']!='cleaned':
        _block(adapter,'Unbound request acquired the fault service; refuse adoption')
    return row


def observe(adapter,cid):
    """Call while provider.wait polls so FAILED cannot be replaced by a later snapshot."""
    record=_record(adapter,cid)
    status=_request(adapter,cid,'GET','/'+record['handle'])
    row=_database(adapter,cid)
    if any(status.get(key)!=row[key] for key in ('request_id','reservation_id','outbox_id','tool_payload_hash')):
        raise SimulationError('Native HTTP/database fault identities disagree')
    snapshot={key:row[key] for key in ('phase','request_id','reservation_id','outbox_id','projection_status',
        'outbox_status','attempts','fault_consumed_at','response_loss_consumed_at','tool_payload_hash')}
    snapshot['observed_at']=datetime.now(timezone.utc).isoformat()
    record['observations'].append(snapshot)
    if row['request_id']:
        record.update(request_id=row['request_id'],reservation_id=row['reservation_id'],outbox_id=row['outbox_id'])
        adapter.owned_ids.add(row['request_id'])
        adapter.current_ids.add(row['request_id'])
    adapter._save()
    return row,status


def bind(adapter,cid,*,invocation_id,test_id):
    record=_record(adapter,cid)
    manifest=adapter.campaign.manifest
    binding={'invocation_id':invocation_id,'test_id':test_id}
    if (not isinstance(invocation_id,str) or not invocation_id or not isinstance(test_id,str) or not test_id
            or invocation_id not in manifest.get('invocations',[]) or test_id not in manifest.get('provider_tests',[])):
        raise SimulationError('Fault invocation/test must already belong to this run')
    ledger=json.loads((Path(adapter.campaign.root)/'usage-ledger.json').read_text())
    entries=[entry for entry in ledger['entries'] if entry.get('invocation_id')==invocation_id]
    if len(entries)!=1 or any(entries[0].get(k)!=v for k,v in {**binding,'case_id':cid,'run_id':manifest['run_id']}.items()):
        raise SimulationError('Fault invocation differs from the common ledger')
    if record.get('binding') not in (None,binding):
        raise SimulationError('Fault invocation cannot be rebound')
    record['binding']=binding
    adapter._save()


bind_invocation=bind


def reconcile(adapter,cid):
    row,status=observe(adapter,cid)
    if cid!='C36' or not row['response_loss_consumed_at'] or not row['request_id']:
        raise SimulationError('Server commit/loss must be observed before lease reconciliation')
    if status.get('lease_reconciliation') is not True or status.get('core_generic_retry_proven') is not False:
        raise SimulationError('Native recovery must be labeled as lease reconciliation')
    _record(adapter,cid)['reconciliation']={'request_id':row['request_id'],'reservation_id':row['reservation_id'],
        'outbox_id':row['outbox_id'],'lease_reconciliation':True,'core_generic_retry_proven':False}
    adapter._save()
    return _record(adapter,cid)['reconciliation']


def _native_payload_hash(material):
    return hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _provider_proof(adapter,cid,provider,row):
    record=_record(adapter,cid)
    binding=record.get('binding')
    if not binding or provider is None:
        return False
    invocation=provider.get(binding['invocation_id'])
    if (not isinstance(invocation,dict) or invocation.get('id')!=binding['invocation_id']
            or invocation.get('agent_id')!=adapter.campaign.manifest.get('campaign_agent_id')
            or invocation.get('cancelled') is not False or len(invocation.get('test_runs',[]))!=1):
        return False
    runs=[run for run in invocation.get('test_runs',[]) if run.get('test_id')==binding['test_id']
          and run.get('test_invocation_id')==binding['invocation_id']]
    if len(runs)!=1 or runs[0].get('status') not in {'passed','failed'}:
        return False
    calls=[]
    results=[]
    for response in runs[0].get('agent_responses',[]):
        calls.extend(call for call in response.get('tool_calls',[]) if call.get('tool_name')=='create_service_request')
        results.extend(result for result in response.get('tool_results',[]) if result.get('tool_name')=='create_service_request')
    if not calls or len(calls)!=len(results):
        return False
    wanted=tool_target_descriptor(adapter,cid)['url']
    errors=0
    for call in calls:
        try:
            arguments=call['params_as_json']
            if isinstance(arguments,str): arguments=json.loads(arguments)
            details=call['tool_details']
            if (call.get('type')!='webhook' or call.get('tool_has_been_called') is not True
                    or not isinstance(call.get('request_id'),str) or not call['request_id']
                    or details.get('type')!='webhook' or details.get('method')!='POST' or details.get('url')!=wanted
                    or _native_payload_hash({'name':'create_service_request','arguments':arguments})!=row['tool_payload_hash']):
                return False
            matches=[result for result in results if result.get('request_id')==call['request_id']]
            if len(matches)!=1:
                return False
            result=matches[0]
            if result.get('is_error') is True:
                errors+=1
                if cid!='C36': return False
            elif result.get('is_error') is False:
                value=result['result_value']
                if isinstance(value,str): value=json.loads(value)
                native=value.get('result',value)
                if native.get('success') is not True or native.get('service_request_id')!=row['request_id']:
                    return False
                if cid=='C36' and value.get('lease_reconciliation') is not True:
                    return False
            else:
                return False
        except (KeyError,TypeError,ValueError):
            return False
    return errors==1 if cid=='C36' else errors==0


def checks(adapter,cid,values=None,before=None,after=None,*,provider=None):
    row,status=observe(adapter,cid)
    record=_record(adapter,cid)
    agent=bool(row['tool_payload_hash']) and status.get('agent_tool_verified') is True and _provider_proof(adapter,cid,provider,row)
    common=[check('actual owned-clone tool URL arguments and consent match the native lease',agent),
        check('one exact owned native request reservation and outbox',bool(row['request_id']) and row['request_count']==1)]
    if cid=='C35':
        sequence=record['observations']
        failed=[i for i,s in enumerate(sequence) if s['projection_status']=='FAILED' and s['outbox_status']=='PENDING'
                and s['attempts']>=1 and s['fault_consumed_at'] and s['request_id']==row['request_id']
                and s['reservation_id']==row['reservation_id'] and s['outbox_id']==row['outbox_id']]
        recovered=bool(failed) and any(s['projection_status']=='CREATED' and s['outbox_status']=='DELIVERED'
            and (s['request_id'],s['reservation_id'],s['outbox_id'])==(row['request_id'],row['reservation_id'],row['outbox_id'])
            for s in sequence[min(failed)+1:])
        return common+[check('observed controlled native worker FAILED then normal retry CREATED on same identities',recovered)]
    return common+[check('actual server commit and response-loss journal on same owned binding',bool(row['response_loss_consumed_at'])),
        check('explicit native lease reconciliation preserves booking; generic voice idempotency is not claimed',
            record.get('reconciliation',{}).get('request_id')==row['request_id'] and bool(row['request_id']))]


def cleanup(adapter,cid):
    record=_record(adapter,cid)
    row,_=observe(adapter,cid)
    if record.get('cleanup_complete'):
        return {'success':True,'cleanup_complete':True}
    if not record.get('disarmed'):
        _request(adapter,cid,'POST','/'+record['handle']+'/disarm',body={},action='disarm')
        record['disarmed']=True
        adapter._save()
    request_id=row['request_id']
    if request_id:
        if request_id not in adapter.owned_ids or request_id not in adapter.current_ids or request_id in adapter.original_ids:
            raise SimulationError('Only a registered owned fault booking can be canceled')
        if row['request_status'] not in {'cancelled','cancelled_by_customer'}:
            adapter._mutate('POST','/api/v1/voice/tools',{'name':'cancel_appointment','arguments':{
                'phone':record['expected']['phone'],'appointment_id':request_id,
                'cancellation_reason':'Owner-designated simulation cleanup'}})
        adapter._settle_cleanup({request_id})
        settled=_database(adapter,cid)
        if settled['projection_status']!='DELETED' or settled['unsettled_outbox']:
            raise SimulationError('Owned provider retirement or outbox delivery remains pending; do not delete fixture')
    result=_request(adapter,cid,'POST','/'+record['handle']+'/cleanup',body={},action='cleanup')
    if result.get('cleanup_complete') is not True:
        _block(adapter,'Owned native fault cleanup is unverified')
    retired=_database(adapter,cid)
    if retired['phase']!='cleaned' or retired['service_id'] is not None:
        _block(adapter,'Owned native fault cleanup read-back differs')
    record['cleanup_complete']=True
    adapter.current_ids.discard(request_id)
    adapter._save()
    return result



def prerequisites(adapter,cid,values):
    """Fresh authenticated native control probe plus independent read-only schema."""
    result=_request(adapter,cid,'GET')
    phone=medium._digits(values['customer_phone'])
    canonical='+1'+phone[-10:]
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    technician=adapter.config['deployed_medium']['technician_ids'][0]
    if (result.get('capability')!='owned-faults-v1' or result.get('enabled') is not True
            or result.get('schema_ready') is not True or MODES[cid] not in result.get('modes',[])
            or technician not in result.get('allowlisted_technician_ids',[])
            or digest not in result.get('allowlisted_phone_fingerprints',[])):
        raise SimulationError('Native owned fault controls/schema/designated allowlists are unavailable')
    rows=medium._read(adapter.config,"""SELECT
        to_regclass('simulation_fault_leases') IS NOT NULL AND to_regclass('simulation_fault_journal') IS NOT NULL
        AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema()
            AND table_name='simulation_fault_leases' AND column_name='tool_payload_hash') AS ready""")
    if rows!=[{'ready':True}]:
        raise SimulationError('Independent native fault lease schema is not ready')
    return result
