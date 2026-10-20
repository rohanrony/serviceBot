"""Read-only, explicitly enabled native-session prerequisite capability probe."""

from fastapi import APIRouter, HTTPException, Request

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.services import simulation_staff
from serviceBot.services.webhook_security import (
    elevenlabs_webhook_secret_configured,
    is_test_environment,
)

router=APIRouter(prefix='/api/v1/portal/internal',tags=['simulation-session-capabilities'])


@router.get('/simulation-session-capabilities')
def session_capabilities(request:Request):
    try:
        simulation_staff.authorize(request.headers.get('authorization'))
    except simulation_staff.LifecycleDenied:
        raise HTTPException(status_code=403,detail='Native session capability is unavailable') from None
    with get_db_connection() as conn,dict_cursor(conn) as cursor:
        cursor.execute("""SELECT to_regclass('authenticated_webhook_ingress') IS NOT NULL
            AND to_regclass('webhook_events') IS NOT NULL AND to_regclass('crm_notes') IS NOT NULL
            AND (SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema()
                AND table_name='authenticated_webhook_ingress'
                AND column_name IN ('provider','event_id','conversation_id','payload_hash','verified_at'))=5 AS ready""")
        row=cursor.fetchone()
    return {'success':True,'capability':'owned-session-v1','enabled':True,
            'audit_schema_ready':bool(row and row.get('ready') is True),
            'hmac_configured':elevenlabs_webhook_secret_configured(),'verification_bypass_active':is_test_environment()}
