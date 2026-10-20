"""Owned genuine C50 session driver, with injected REST/socket boundaries only.

Signed URLs and authentication headers are never persisted. Native totals require
an independently verified account unit contract; unknown effects remain unsettled.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlencode, urlsplit

from . import deployed_full_causal as causal
from .core import SimulationError, fingerprint, number, private_json
from .deployed_full_interruption import _intent, _read
from .runner import campaign_lock, current_remaining


def _paths(adapter):
    root=Path(adapter.campaign.root)
    folder=Path(adapter.campaign.folder)
    if (root.is_symlink() or folder.is_symlink() or not folder.is_dir()
            or folder.name!=adapter.campaign.manifest.get('run_id') or folder.parent.resolve()!=root.resolve()):
        raise SimulationError('Native session requires exact owned campaign folder')
    return root,folder,folder/'C50-native-session-intent.json'


def _baseline(adapter,*,financial_only=False):
    if not financial_only:
        adapter._guard()
    baseline=adapter.state.get('full_history',{})
    manifest=adapter.campaign.manifest
    if (not isinstance(baseline.get('run_id'),str) or not re.fullmatch('[0-9a-f]{32}',baseline['run_id'])
            or not isinstance(baseline.get('agent_id'),str) or not baseline['agent_id']
            or baseline.get('run_id')!=manifest.get('run_id') or baseline.get('case_id')!='C50'
            or baseline.get('agent_id')!=manifest.get('campaign_agent_id')
            or type(baseline.get('customer_id')) is not int or baseline['customer_id']<=0
            or not isinstance(baseline.get('baseline_note_ids'),list)
            or not isinstance(baseline.get('baseline_event_ids'),list)):
        raise SimulationError('Native session requires saved pre-call owned history baseline')
    if financial_only:
        # Already incurred charges belong to the immutable session identity;
        # current customer availability or profile edits cannot change it.
        if (not isinstance(baseline.get('customer_phone'),str)
                or not re.fullmatch(r'\+1[0-9]{10}',baseline['customer_phone'])
                or not isinstance(baseline.get('customer_name'),str)
                or not baseline['customer_name'].strip()):
            raise SimulationError('Native session saved customer identity is malformed')
        return baseline
    rows=causal.medium._read(adapter.config,'SELECT id,name,phone FROM customers WHERE id=%s',(baseline['customer_id'],))
    if len(rows)!=1:
        raise SimulationError('Native session customer identity is ambiguous')
    digits=re.sub(r'\D','',str(rows[0].get('phone','')))
    if len(digits)==10:
        digits='1'+digits
    if (not re.fullmatch('1[0-9]{10}',digits) or baseline.get('customer_phone')!='+'+digits
            or not isinstance(baseline.get('customer_name'),str) or rows[0].get('name')!=baseline['customer_name']):
        raise SimulationError('Native session customer phone or name changed')
    return baseline


def _units(adapter,credit_reader):
    if (adapter.config.get('budget',{}).get('native_session_credit_units_verified') is not True
            or adapter.config.get('budget',{}).get('verified_credit_units') is not True):
        raise SimulationError('Native session credit units remain unverified')
    if not callable(credit_reader):
        raise SimulationError('Native session requires independently verified credit reader')


def _report(status,*,verified=False,stop=True):
    return {'status':status,'history_verified':verified,'global_stop':stop,
            'native_acceptance':'unverified','implemented_offline':True}


def _authority(adapter,ledger):
    auth=adapter.campaign.manifest.get('stage_authorization',{})
    if (not isinstance(auth,dict) or auth.get('tier')!='full'
            or auth.get('case_ids')!=[f'C{i:02}' for i in range(17,51)]
            or not isinstance(auth.get('authorization_id'),str) or not auth['authorization_id']):
        raise SimulationError('Native session requires the existing claimed full-stage authority')
    number(auth.get('credit_ceiling'),positive=True)
    matches=[c for c in ledger.get('stage_authorizations',[]) if c.get('authorization_id')==auth['authorization_id']]
    if len(matches)!=1 or matches[0]!={**auth,'run_id':adapter.campaign.manifest['run_id']}:
        raise SimulationError('Native session full-stage claim identity differs')
    return auth['authorization_id']


def _entry(ledger,intent):
    matches=[e for e in ledger.get('entries',[]) if e.get('session_nonce')==intent['session_nonce']]
    if len(matches)!=1:
        raise SimulationError('Native session common ledger binding is unavailable')
    entry=matches[0]
    if any(entry.get(k)!=intent[k] for k in ('run_id','case_id','agent_id','session_nonce','authorization_id')) or entry.get('resource_type')!='conversation':
        raise SimulationError('Native session common ledger identity differs')
    if entry.get('intent_sha256')!=fingerprint(intent):
        raise SimulationError('Native session intent changed')
    return entry


def _save(root,folder,ledger,record):
    private_json(root/'usage-ledger.json',ledger)
    private_json(folder/'C50-native-session-state.json',record)


def _known_context(adapter,*,financial_only=False):
    baseline=_baseline(adapter,financial_only=financial_only)
    root,folder,path=_paths(adapter)
    intent=_read(path)
    if (intent.get('baseline')!=baseline or intent.get('run_id')!=baseline['run_id']
            or intent.get('agent_id')!=baseline['agent_id']):
        raise SimulationError('Native session belongs to another baseline or campaign')
    ledger=_read(root/'usage-ledger.json')
    authority=_authority(adapter,ledger)
    if intent.get('authorization_id')!=authority:
        raise SimulationError('Native session claimed authority changed')
    entry=_entry(ledger,intent)
    cid=entry.get('provider_conversation_id')
    if not isinstance(cid,str) or not cid or entry.get('billing_id')!='conversation:'+cid:
        raise SimulationError('Native session identity is unknown; no reconnect or test-ID substitution')
    return baseline,root,folder,intent,ledger,entry,cid


def _finish(adapter,provider,credit_reader,max_polls,*,financial_only=False):
    baseline,root,folder,intent,ledger,entry,cid=_known_context(adapter,financial_only=financial_only)
    result=_report('awaiting_native_history')
    for _ in range(max_polls):
        try:
            detail=provider.request('GET','/v1/convai/conversations/'+quote(cid,safe=''))
            if (not isinstance(detail,dict) or detail.get('conversation_id')!=cid
                    or detail.get('agent_id')!=intent['agent_id']):
                raise ValueError
            dynamic=detail.get('conversation_initiation_client_data',{}).get('dynamic_variables',{})
            user_ids=[v for v in (detail.get('user_id'),detail.get('conversation_initiation_client_data',{}).get('user_id')) if v is not None]
            if (not isinstance(dynamic,dict) or any(dynamic.get(k)!=v for k,v in intent['dynamic_variables'].items())
                    or not user_ids or any(v!=baseline['customer_phone'] for v in user_ids)):
                raise ValueError
            if detail.get('status') not in ('done','failed'):
                result=_report('awaiting_terminal')
                continue
            # Credit reader must use the independently verified native unit contract;
            # there is intentionally no fallback to fiat/LLM cost estimates.
            if credit_reader is native_credit_reader:
                contract=intent.get('credit_contract',{})
                if (contract.get('source')!='conversation.metadata.cost' or contract.get('units')!='credits'
                        or not isinstance(contract.get('subscription_tier'),str) or not contract['subscription_tier']):
                    raise SimulationError('Original native session credit-unit contract unavailable')
            credits=credit_reader(detail)
            if credits is None or type(credits) is bool:
                result=_report('unknown_actual_credits')
                continue
            amount=str(number(credits))
            if entry.get('unsettled') is False and number(entry['credits'])!=number(amount):
                raise SimulationError('Settled native session credits conflict')
            entry.update(credits=amount,unsettled=False,credit_units='credits',
                credit_source='conversation.metadata.cost' if credit_reader is native_credit_reader else 'verified_injected_reader')
            private_json(root/'usage-ledger.json',ledger)
            if financial_only:
                result=_report('native_charge_settled')
                break
            native=causal.observe_history(adapter,customer_id=baseline['customer_id'],conversation_id=cid)
            valid=(detail['status']=='done' and causal.verify_native_history(native,detail,
                customer_id=baseline['customer_id'],conversation_id=cid,agent_id=intent['agent_id'],
                baseline_note_ids=baseline['baseline_note_ids'],baseline_event_ids=baseline['baseline_event_ids'],
                dynamic_variables=intent['dynamic_variables'],expected_user_id=baseline['customer_phone']))
            result=_report('verified_history' if valid else 'awaiting_native_history',verified=valid,
                stop=(not valid or any(e.get('unsettled') is not False for e in ledger['entries'])))
            if valid:
                break
        except SimulationError as error:
            if str(error)=='Settled native session credits conflict':
                raise
            result=_report('native_session_observation_unavailable')
            break
        except Exception:  # noqa: BLE001 - external diagnostic text must not be persisted
            result=_report('native_session_observation_unavailable')
            break
    result['provider_conversation_id']=cid
    _save(root,folder,ledger,{'run_id':intent['run_id'],'case_id':'C50',
        'session_nonce':intent['session_nonce'],'provider_conversation_id':cid,**result})
    return result


def execute(adapter,*,provider,socket_factory,credit_reader,budget,estimate,script,max_events=50,max_polls=3,
            timeout_seconds=30,clock=time.monotonic):
    """One signed URL and one owned socket ever; retries use reconcile GET only.

    ``socket_factory(url)`` returns an owned socket with send(str),
    recv(timeout=<seconds>) and close(). The wrapper must enforce recv timeout.
    Caller must hold or delegate the common campaign lock when nesting this driver.
    """
    _units(adapter,credit_reader)
    baseline=_baseline(adapter)
    if not budget.can_start(number(estimate,positive=True)):
        raise SimulationError('Native session budget cannot admit this conversation')
    if (not callable(socket_factory) or not callable(clock) or type(max_events) is not int or not 1<=max_events<=200
            or type(max_polls) is not int or not 1<=max_polls<=20
            or type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=120
            or not isinstance(script,list) or not 1<=len(script)<=8
            or any(not isinstance(s,str) or not s.strip() or len(s)>2000 for s in script)):
        raise SimulationError('Native session requires bounded owned socket and deterministic script')
    root,folder,path=_paths(adapter)
    with campaign_lock(root):
        if path.exists():
            raise SimulationError('Native session already attempted; reconcile known conversation with GET only')
        ledger=_read(root/'usage-ledger.json')
        if not isinstance(ledger.get('entries'),list) or any(e.get('unsettled') is not False for e in ledger['entries']):
            raise SimulationError('Unsettled common ledger blocks native session')
        authority=_authority(adapter,ledger)
        if budget.cap!=number(adapter.campaign.manifest['stage_authorization']['credit_ceiling'],positive=True):
            raise SimulationError('Native session Budget differs from claimed stage ceiling')
        # Fresh account admission happens under the same lock and before intent,
        # signed URL or socket. Never replenish already-accounted headroom.
        remaining=native_credit_remaining(adapter.config,provider)
        budget.remaining=min(budget.remaining,remaining)
        if not budget.can_start(number(estimate,positive=True)):
            raise SimulationError('Native session fresh quota cannot admit this conversation')
        credit_config=adapter.config['budget']
        credit_contract={'source':'conversation.metadata.cost','units':'credits',
            'subscription_tier':credit_config['native_session_credit_subscription_tier'],
            'reset_unix':credit_config['reset_unix'],
            'monthly_credits':str(number(credit_config['monthly_credits'],positive=True))}
        nonce=secrets.token_hex(16)
        dynamic={'run_id':baseline['run_id'],'case_id':'C50','session_nonce':nonce}
        intent={'schema_version':1,'run_id':baseline['run_id'],'case_id':'C50','agent_id':baseline['agent_id'],
            'authorization_id':authority,'session_nonce':nonce,'dynamic_variables':dynamic,'baseline':baseline,
            'script_sha256':fingerprint(script),'credit_contract':credit_contract}
        _intent(path,intent)
        entry={k:intent[k] for k in ('run_id','case_id','agent_id','session_nonce','authorization_id')}
        entry.update(resource_type='conversation',unsettled=True,submission_unknown=True,intent_sha256=fingerprint(intent))
        ledger['entries'].append(entry)
        private_json(root/'usage-ledger.json',ledger)
        socket=None
        failed=False
        try:
            query=urlencode({'agent_id':intent['agent_id'],'include_conversation_id':'true'})
            signed=provider.request('GET','/v1/convai/conversation/get-signed-url?'+query)
            cid=signed.get('conversation_id')
            url=signed.get('signed_url')
            parsed=urlsplit(url) if isinstance(url,str) else None
            if (not isinstance(cid,str) or not re.fullmatch('[A-Za-z0-9_-]{1,200}',cid) or not parsed or parsed.scheme!='wss'
                    or parsed.netloc!='api.elevenlabs.io' or parsed.path!='/v1/convai/conversation'
                    or not parsed.query or parsed.fragment):
                raise ValueError
            if any(other is not entry and other.get('provider_conversation_id')==cid for other in ledger['entries']):
                raise ValueError
            # Actual provider CID is known and durable before the socket can connect.
            entry.update(provider_conversation_id=cid,billing_id='conversation:'+cid,submission_unknown=False)
            private_json(root/'usage-ledger.json',ledger)
            deadline=clock()+timeout_seconds
            socket=socket_factory(url)
            client_dynamic=dict(dynamic,caller_phone=baseline['customer_phone'],
                customer_phone=baseline['customer_phone'],customer_name=baseline['customer_name'])
            socket.send(json.dumps({'type':'conversation_initiation_client_data','dynamic_variables':client_dynamic,
                'user_id':baseline['customer_phone']}))
            handshake=False
            sent=responses=0
            for _ in range(max_events):
                left=deadline-clock()
                if left<=0:
                    raise ValueError
                raw=socket.recv(timeout=left)
                if not isinstance(raw,(str,bytes)) or len(raw)>1000000:
                    raise ValueError
                event=json.loads(raw)
                if not isinstance(event,dict):
                    raise TypeError
                kind=event.get('type')
                if kind=='conversation_initiation_metadata':
                    if handshake or event.get('conversation_initiation_metadata_event',{}).get('conversation_id')!=cid:
                        raise ValueError
                    handshake=True
                    socket.send(json.dumps({'type':'user_message','text':script[sent]}));sent+=1
                elif kind=='ping':
                    event_id=event.get('ping_event',{}).get('event_id')
                    if type(event_id) is not int:
                        raise ValueError
                    socket.send(json.dumps({'type':'pong','event_id':event_id}))
                elif kind=='agent_response':
                    if not handshake or not isinstance(event.get('agent_response_event',{}).get('agent_response'),str):
                        raise ValueError
                    responses+=1
                    if sent<len(script):
                        socket.send(json.dumps({'type':'user_message','text':script[sent]}));sent+=1
                    else:
                        break
            if not handshake or sent!=len(script) or responses<len(script):
                raise ValueError
        except Exception:  # noqa: BLE001 - unknown transport effects retain unsettled charge
            failed=True
        finally:
            if socket is not None:
                try:
                    socket.close()
                except Exception:  # noqa: BLE001 - close may fail after an actual provider effect
                    failed=True
        if failed:
            result=_report('native_session_effect_unknown')
            _save(root,folder,ledger,{'run_id':intent['run_id'],'case_id':'C50','session_nonce':nonce,**result})
            return result
        return _finish(adapter,provider,credit_reader,max_polls)


def reconcile(adapter,*,provider,credit_reader,max_polls=3):
    """Read known genuine CID only; never request signed URL or open a socket."""
    _units(adapter,credit_reader)
    if type(max_polls) is not int or not 1<=max_polls<=20:
        raise SimulationError('Native session reconciliation requires bounded polls')
    root,_,_=_paths(adapter)
    with campaign_lock(root):
        return _finish(adapter,provider,credit_reader,max_polls)


def native_socket_factory(signed_url):
    """Compiled bounded socket boundary; signed URL never reaches a logger."""
    import logging

    from websockets.sync.client import connect
    silent=logging.Logger('owned_native_session',level=logging.CRITICAL+1)  # noqa: LOG001 - private logger cannot be re-enabled globally to disclose signed URLs
    silent.propagate=False
    return connect(signed_url,open_timeout=10,close_timeout=5,max_size=1000000,max_queue=16,
                   proxy=None,logger=silent)


def unknown_credit_reader(detail):
    """Native API fiat amounts don't establish credit units; never convert them."""
    return


def native_credit_reader(detail):
    """Read only the exact total under a separately verified account unit contract.

    Provider schemas do not prove credit equivalence for every plan. The caller
    must retain the account-specific unit gate. Charging components have no
    established additive/alias formula and fiat values are never substitutes.
    """
    if not isinstance(detail,dict) or detail.get('status') not in ('done','failed'):
        return None
    metadata=detail.get('metadata')
    if not isinstance(metadata,dict):
        return None
    amount=metadata.get('cost')
    return amount if type(amount) is int and amount>=0 else None


def native_credit_remaining(config,provider):
    """Observe fresh native admission headroom, never infer real account units.

    The explicit verified tier pins the account-specific operator verification.
    GET-only reconciliation deliberately does not use this new-admission gate.
    """
    budget=config.get('budget',{})
    tier=budget.get('native_session_credit_subscription_tier')
    if (budget.get('verified_credit_units') is not True
            or budget.get('native_session_credit_units_verified') is not True
            or not isinstance(tier,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',tier)):
        raise SimulationError('Native session credit units and pinned subscription tier require independent verification')
    try:
        sub=provider.subscription()
        if (not isinstance(sub,dict) or sub.get('status')!='active' or sub.get('tier')!=tier
                or any(type(sub.get(key)) is not int for key in
                    ('character_count','character_limit','next_character_count_reset_unix'))
                or sub['character_count']<0 or sub['character_limit']<=0):
            raise ValueError
        # Reuse the existing owner for monthly allowance, future reset/rollover
        # and refreshed remaining accounting; do not infer a minutes/credit rate.
        return current_remaining(config,SimpleNamespace(subscription=lambda:sub))
    except Exception:  # noqa: BLE001 - external diagnostics can contain credentials
        raise SimulationError('Native session current account quota is unavailable or changed') from None


def reconcile_campaign(campaign,provider):
    """Financial recovery from retained ownership evidence, independent of fixtures.

    This capability does not construct a mutable fixture adapter or change its
    blocked flag. Only the exact retained native conversation may be queried.
    """
    adapter=SimpleNamespace(campaign=campaign,config=campaign.config,
        state=campaign.manifest.get('deployed_medium',{}))
    _units(adapter,native_credit_reader)
    root,_,_=_paths(adapter)
    with campaign_lock(root):
        return _finish(adapter,provider,native_credit_reader,3,financial_only=True)
