"""Full-stage dispatch inside the existing deployed Campaign and common ledger.

Only compiled native observers can satisfy admission. Configuration declarations
are never evidence. No provider/client is created here and no default effects run.
"""
import json

from .core import SimulationError, number
from .runner import owned_campaign_scope

FULL_IDS=tuple(f'C{i:02}' for i in range(17,51))


def total_estimate(config, estimates):
    return sum(estimates,number(0))+number(config.get('budget',{}).get('c48_recovery_upper_estimate'),positive=True)


def prerequisites(config, client, cases, baseline, module):
    observer=getattr(module,'native_prerequisites',None)
    if not callable(observer):
        raise SimulationError('Full native prerequisite observer is unavailable')
    if not set(FULL_IDS) <= set(getattr(module,'SUPPORTED_CASE_IDS',())):
        return ['Full native prerequisites lack compiled adapters for every case']
    observed=observer(config,client,cases,baseline)
    if not isinstance(observed,dict) or set(observed)!=set(FULL_IDS):
        return ['Full native prerequisites must independently cover C17-C50']
    problems=[]
    for cid in FULL_IDS:
        checks=observed[cid]
        if (not isinstance(checks,list) or not checks or any(not isinstance(c,dict)
                or c.get('passed') is not True or not isinstance(c.get('name'),str) or not c['name'] for c in checks)):
            problems.append(cid+' native mechanism or permission remains unverified')
    return problems


def bind_invocation(adapter, case, invocation_id, test_id):
    hook=getattr(adapter,'bind_invocation',None)
    if not callable(hook):
        raise SimulationError('Full adapter lacks durable invocation binding hook')
    hook(case,invocation_id=invocation_id,test_id=test_id)


def case_checks(adapter, case, values, before, after, provider):
    hook=getattr(adapter,'execution_checks',None)
    if not callable(hook):
        raise SimulationError('Full adapter lacks native execution assertion hook')
    with owned_campaign_scope(adapter.campaign.root):
        return hook(case,values,before,after,provider=provider)


def run_c48(adapter, *, provider, budget, ledger, campaign, estimate):
    hook=getattr(adapter,'execute_c48',None)
    reserve=number(campaign.config['budget']['c48_recovery_upper_estimate'],positive=True)
    if not callable(hook) or not budget.can_start(number(estimate,positive=True)+reserve):
        raise SimulationError('C48 requires native two-phase coordinator and both phase budgets')
    before={e.get('invocation_id') for e in ledger['entries'] if e.get('invocation_id')}
    try:
        with owned_campaign_scope(campaign.root):
            report=hook(provider=provider,budget=budget,ledger=ledger,campaign=campaign)
    finally:
        # Coordinator owns durable common-ledger writes; reload even after unknown
        # submission so the outer executor cannot overwrite its unsettled entry.
        fresh=json.loads((campaign.root/'usage-ledger.json').read_text())
        ledger.clear()
        ledger.update(fresh)
        for entry in ledger['entries']:
            identifier=entry.get('invocation_id')
            if entry.get('run_id') != campaign.run_id or entry.get('case_id') != 'C48' or identifier in before:
                continue
            if not identifier or entry.get('unsettled') is not False:
                budget.unknown=True
            elif identifier not in budget.settled:
                budget.settle(identifier,entry.get('credits'))
    if not isinstance(report,dict):
        raise SimulationError('C48 native coordinator result unavailable')
    if report.get('recovery_verified') is True:
        try:
            identifiers=[report[key]['invocation_id'] for key in ('source_binding','recovery_binding')]
            if (any(not isinstance(i,str) or not i for i in identifiers) or len(set(identifiers)) != 2
                    or any(i in before for i in identifiers)):
                raise ValueError
            charges=[e for e in ledger['entries'] if e.get('invocation_id') in identifiers]
            if (len(charges) != 2 or any(e.get('run_id') != campaign.run_id or e.get('case_id') != 'C48'
                    or e.get('unsettled') is not False for e in charges)):
                raise ValueError
        except (KeyError,TypeError,ValueError):
            raise SimulationError('C48 verified result lacks two distinct settled owned phase charges') from None
    return report


def run_c50(adapter, *, provider, budget, ledger, campaign, estimate):
    """Dedicated genuine session channel; agent-test IDs are never conversation IDs.

    Native executor must journal session initiation before effects and preserve
    unknown provider-session charges in the common ledger. Its prerequisite
    observer must independently verify session credit units before admission.
    """
    hook=getattr(adapter,'execute_c50',None)
    if not callable(hook) or not budget.can_start(number(estimate,positive=True)):
        raise SimulationError('C50 requires native session executor and verified session accounting')
    before={e.get('billing_id') for e in ledger['entries'] if e.get('billing_id')}
    try:
        with owned_campaign_scope(campaign.root):
            report=hook(provider=provider,budget=budget,ledger=ledger,campaign=campaign)
    finally:
        fresh=json.loads((campaign.root/'usage-ledger.json').read_text())
        ledger.clear()
        ledger.update(fresh)
        for entry in ledger['entries']:
            identifier=entry.get('billing_id')
            if entry.get('run_id') != campaign.run_id or entry.get('case_id') != 'C50' or identifier in before:
                continue
            conversation=entry.get('provider_conversation_id')
            if (entry.get('resource_type') != 'conversation' or not isinstance(conversation,str) or not conversation
                    or identifier != 'conversation:'+conversation or entry.get('unsettled') is not False
                    or entry.get('credits') is None):
                budget.unknown=True
            elif identifier not in budget.settled:
                budget.settle(identifier,entry.get('credits'))
    if not isinstance(report,dict):
        raise SimulationError('C50 native session result unavailable')
    return report


def special_checks(case,report,verified,budget):
    """Retain special-case native proof and the same explicit receiving gate."""
    from .evidence import check
    checks=list(report.get('checks',[]))
    checks += [check('actual native '+case['id']+' lifecycle verified',verified),
               check('actual credits verified',not budget.unknown),
               check('tier budget respected',budget.spent<=budget.cap)]
    if 'email' in case.get('required_evidence',[]):
        checks.append({'name':'receiving inbox contains expected content','passed':False,'status':'unverified',
                       'reason':'Native receiving-inbox verification pending; operator receipt is separate.'})
    return checks
