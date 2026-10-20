import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

if os.getenv("PYTHON_DOTENV_DISABLED") != "1":
    _is_testing_env = (
        "pytest" in sys.modules
        or any("pytest" in arg or "unittest" in arg or "run_tests" in arg for arg in sys.argv)
        or os.getenv("TESTING") == "1"
        or os.getenv("TEST_DATABASE_URL") is not None
        or os.getenv("TEST_LOG_FILE") is not None
    )
    _override = not _is_testing_env
    _env = find_dotenv()
    if _env:
        load_dotenv(dotenv_path=_env, override=_override)
    else:
        load_dotenv(override=_override)

from serviceBot.api.middleware import RequestLoggingMiddleware, global_exception_handler
from serviceBot.api.portal import router as portal_router
from serviceBot.api.simulation_faults import router as simulation_faults_router
from serviceBot.api.simulation_sessions import router as simulation_sessions_router
from serviceBot.api.telephony import router as telephony_router
from serviceBot.api.telephony import voice_router as voice_router
from serviceBot.logger import get_logger

# Initialize structured logger
logger = get_logger("main")





def _isolated_startup():
    return any(x in sys.modules for x in ["pytest", "unittest"]) or any(
        "demo" in arg or "test" in arg for arg in sys.argv
    )


async def _restore_startup_catalog():
    """Restore disposable catalog artifacts from PostgreSQL before readiness."""
    from serviceBot.api.portal import sync_services_to_kb

    started = time.monotonic()
    try:
        await asyncio.to_thread(sync_services_to_kb)
    except Exception:  # noqa: BLE001 - startup fails closed without exposing owner diagnostics
        logger.error(
            "[catalog_startup] Recovery failed duration_seconds=%.3f acceptance_budget_seconds=120",
            time.monotonic() - started,
        )
        raise RuntimeError("Service catalog startup recovery failed") from None
    logger.info(
        "[catalog_startup] Recovery completed duration_seconds=%.3f acceptance_budget_seconds=120",
        time.monotonic() - started,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _isolated_startup():
        yield
        return

    await _restore_startup_catalog()

    # 1. Start background worker threads (For persistent container environments like Docker / Render)
    try:
        from serviceBot.services.outbox_worker import start_outbox_worker
        start_outbox_worker()
        logger.info("[outbox_worker] Started background outbox worker thread.")
    except Exception as e:
        logger.warning(f"[outbox_worker] Failed to launch outbox worker: {e}", exc_info=e)

    try:
        from serviceBot.services.quiet_hours import start_quiet_hours_queue_worker
        start_quiet_hours_queue_worker()
        logger.info("[quiet_hours_worker] Started quiet hours queue worker thread.")
    except Exception as e:
        logger.warning(f"[quiet_hours_worker] Failed to launch quiet hours worker: {e}", exc_info=e)

    try:
        from serviceBot.services.sms_reminders import start_reminder_polling_worker
        start_reminder_polling_worker()
        logger.info("[reminder_worker] Started SMS reminder polling worker thread.")
    except Exception as e:
        logger.warning(f"[reminder_worker] Failed to launch reminder worker: {e}", exc_info=e)

    from serviceBot.services.webhook_security import (
        elevenlabs_webhook_secret_configured,
    )
    if not elevenlabs_webhook_secret_configured():
        logger.error(
            "[webhook_config] ELEVENLABS_WEBHOOK_SECRET is missing; "
            "ElevenLabs post-call webhooks will be rejected."
        )

    api_key_present = bool(os.getenv("ELEVENLABS_API_KEY", "").strip())
    agent_id_present = bool(os.getenv("ELEVENLABS_AGENT_ID", "").strip())
    if api_key_present and agent_id_present:
        try:
            from serviceBot.services.call_sync import start_call_sync_worker
            start_call_sync_worker(interval_seconds=300)
            logger.info("[call_sync_worker] Started ElevenLabs reconciliation worker (interval=300s).")
        except Exception as e:
            logger.exception("[call_sync_worker] Failed to start ElevenLabs reconciliation worker: %s", e)
    else:
        missing = []
        if not api_key_present:
            missing.append("ELEVENLABS_API_KEY")
        if not agent_id_present:
            missing.append("ELEVENLABS_AGENT_ID")
        logger.error("[call_sync_worker] Reconciliation disabled; missing %s.", ", ".join(missing))

    yield

    try:
        from serviceBot.services.call_sync import stop_call_sync_worker
        stop_call_sync_worker()
    except Exception as e:
        logger.warning("[call_sync_worker] Failed to stop reconciliation worker: %s", e)


app = FastAPI(
    title="BayFull Server",
    description="Coordinator for telephony, voice agents, and business configuration portal.",
    version="1.0.0",
    lifespan=lifespan
)

# Register request logging & global exception middleware
app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(Exception, global_exception_handler)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# --- Vercel Serverless Cron Triggers ---
CRON_SECRET = os.getenv("CRON_SECRET", "")

def _verify_cron_auth(authorization: str = Header(None)):
    if CRON_SECRET and authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized cron trigger")

@app.post("/api/cron/outbox")
@app.get("/api/cron/outbox")
async def cron_process_outbox(authorization: str = Header(None)):
    """Trigger outbox processing batch for serverless platforms (e.g. Vercel Crons)."""
    _verify_cron_auth(authorization)
    from serviceBot.services.outbox_worker import process_outbox_batch
    logger.info("[cron_outbox] Executing cron outbox batch...")
    processed_count = process_outbox_batch()
    return {"status": "success", "processed_events": processed_count}

@app.post("/api/cron/reminders")
@app.get("/api/cron/reminders")
async def cron_process_reminders(authorization: str = Header(None)):
    """Trigger SMS reminder check for serverless platforms."""
    _verify_cron_auth(authorization)
    from serviceBot.services.sms_reminders import check_and_send_due_reminders
    logger.info("[cron_reminders] Executing cron SMS reminder check...")
    sent = check_and_send_due_reminders()
    return {"status": "success", "reminders_sent": sent}


app.include_router(telephony_router)
app.include_router(voice_router)
app.include_router(portal_router)
app.include_router(simulation_sessions_router)
app.include_router(simulation_faults_router)

# Root-level aliases for Twilio webhooks configured without /api/v1/telephony prefix
@app.post("/sms/inbound")
async def root_sms_inbound_alias(request: Request):
    from serviceBot.api.telephony import inbound_sms_webhook
    return await inbound_sms_webhook(request)

@app.post("/sms/status")
async def root_sms_status_alias(request: Request):
    from serviceBot.api.telephony import sms_status_callback_webhook
    return await sms_status_callback_webhook(request)


@app.get("/portal")
async def redirect_portal_to_slash():
    return RedirectResponse(url="/portal/")

# Mount Static Files for Frontend Dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/portal", StaticFiles(directory=static_dir, html=True), name="portal")
