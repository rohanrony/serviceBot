"""Authenticated inactive-by-default controls for owned native simulation faults."""
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from starlette.responses import Response

from serviceBot.services import simulation_faults as faults

router = APIRouter(prefix='/api/v1/portal/internal/simulation-faults', tags=['internal-simulation'])


class FixtureCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: StrictStr
    mode: StrictStr
    technician_id: StrictInt
    phone: StrictStr
    booking_time: StrictStr


def _auth(request, handle=None):
    try:
        secret = faults.authorize(request.headers.get('authorization'))
        if handle is not None:
            faults.verify_token(handle,request.headers.get('x-simulation-lease'),secret)
        return secret
    except faults.FaultDenied as exc:
        raise HTTPException(403, str(exc)) from None


def _call(function, *args, **kwargs):
    try:
        return function(*args,**kwargs)
    except faults.FaultDenied as exc:
        raise HTTPException(409,str(exc)) from None


class CommittedResponseLoss(Response):
    """Actual native HTTP truncation, after the booking and fault journal commit."""
    async def __call__(self, scope, receive, send):
        await send({'type':'http.response.start','status':200,
            'headers':[(b'content-type',b'application/json'),(b'content-length',b'128')]})
        await send({'type':'http.response.body','body':b'{"committed":','more_body':True})
        raise RuntimeError('Controlled simulation response loss after committed booking')


@router.post('', status_code=201)
def create_fixture(payload: FixtureCreate, request: Request, background_tasks: BackgroundTasks):
    secret = _auth(request)
    result = _call(faults.create,**payload.model_dump(),secret=secret)
    from serviceBot.api.portal import sync_services_to_kb
    background_tasks.add_task(sync_services_to_kb)
    return result


@router.get('/{handle}')
def fixture_status(handle: UUID, request: Request):
    _auth(request,handle)
    return _call(faults.status,handle)


@router.post('/{handle}/execute')
async def execute_fixture(handle: UUID, request: Request, background_tasks: BackgroundTasks):
    _auth(request,handle)
    return await _execute(handle,request,background_tasks)


async def _execute(handle,request,background_tasks,tool_payload=None):
    lease, execute = _call(faults.begin_execute,handle,tool_payload=tool_payload)
    if not execute:
        observed = _call(faults.status,handle)
        if tool_payload is not None and observed.get('result'):
            return {**observed['result'],'lease_reconciliation':True,'core_generic_retry_proven':False}
        return observed
    from serviceBot.api.telephony import voice_tools
    try:
        with faults.booking_capability(lease):
            payload = faults.validate_tool_payload(lease,tool_payload) if tool_payload is not None else {'name':'create_service_request','arguments':lease['arguments']}
            response = await voice_tools(payload,
                request=request,background_tasks=background_tasks)
        lose = faults.finish_execute(handle,response)
    except Exception as exc:  # noqa: BLE001 - every interrupted booking needs durable unknown state
        faults.mark_unknown(handle)
        if isinstance(exc,faults.FaultDenied):
            raise HTTPException(409,str(exc)) from None
        raise HTTPException(409,'Native execution interrupted; reconcile lease without retry') from None
    if lose:
        return CommittedResponseLoss()
    if tool_payload is not None:
        return response
    return {'success':True,'native_result':response,'lease_reconciliation':False,
            'core_generic_retry_proven':False,'handle':str(handle)}


@router.post('/{handle}/disarm')
def disarm_fixture(handle: UUID, request: Request):
    _auth(request,handle)
    return _call(faults.disarm,handle)


@router.post('/{handle}/cleanup')
def cleanup_fixture(handle: UUID, request: Request, background_tasks: BackgroundTasks):
    _auth(request,handle)
    result = _call(faults.cleanup,handle)
    from serviceBot.api.portal import sync_services_to_kb
    background_tasks.add_task(sync_services_to_kb)
    return result


@router.post('/{handle}/tool')
async def execute_model_tool(handle: UUID, payload: dict, request: Request, background_tasks: BackgroundTasks):
    _auth(request,handle)
    return await _execute(handle,request,background_tasks,tool_payload=payload)


@router.get('')
def native_capabilities(request: Request):
    _auth(request)
    return _call(faults.capabilities)
