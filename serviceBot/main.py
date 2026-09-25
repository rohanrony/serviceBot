from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os
import threading
from contextlib import asynccontextmanager

from serviceBot.logger import get_logger, setup_logging
from serviceBot.api.middleware import RequestLoggingMiddleware, global_exception_handler
from serviceBot.api.telephony import router as telephony_router, voice_router as voice_router
from serviceBot.api.portal import router as portal_router

# Initialize structured logger
logger = get_logger("main")





@asynccontextmanager
async def lifespan(app: FastAPI):
    import sys
    if any(x in sys.modules for x in ["pytest", "unittest"]) or any("demo" in arg or "test" in arg for arg in sys.argv):
        yield
        return

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

    yield


app = FastAPI(
    title="serviceBot Server",
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


@app.get("/portal")
async def redirect_portal_to_slash():
    return RedirectResponse(url="/portal/")

# Mount Static Files for Frontend Dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/portal", StaticFiles(directory=static_dir, html=True), name="portal")
