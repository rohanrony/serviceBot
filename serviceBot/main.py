from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os
import threading
from contextlib import asynccontextmanager
from serviceBot.api.telephony import router as telephony_router, voice_router as voice_router
from serviceBot.api.portal import router as portal_router


def _run_calendar_sync_loop(interval_seconds: int = 3600):
    """
    Background thread: syncs all connected agents' Google Calendar events into
    mock_calendar_slots every `interval_seconds` seconds (default: 1 hour).
    Runs immediately on first call, then sleeps between cycles.
    """
    import time
    from serviceBot.services.calendar_sync import sync_all_connected_agents

    while True:
        try:
            print("[calendar_sync] Starting scheduled slot refresh for all connected agents...")
            results = sync_all_connected_agents(days=30)
            total_new = sum(r.get("created", 0) for r in results.values() if isinstance(r, dict))
            print(f"[calendar_sync] Refresh complete. New slots created: {total_new}. Agents: {list(results.keys())}")
        except Exception as exc:
            print(f"[calendar_sync] Background sync error: {exc}")
        time.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import sys
    if any(x in sys.modules for x in ["pytest", "unittest"]) or any("demo" in arg or "test" in arg for arg in sys.argv):
        yield
        return

    # 1. Start background worker threads
    try:
        from serviceBot.services.outbox_worker import start_outbox_worker
        start_outbox_worker()
    except Exception as e:
        print(f"[outbox_worker] Warning: Failed to launch outbox worker: {e}")


    try:
        from serviceBot.services.quiet_hours import start_quiet_hours_queue_worker
        start_quiet_hours_queue_worker()
    except Exception as e:
        print(f"[quiet_hours_worker] Warning: Failed to launch quiet hours worker: {e}")

    try:
        from serviceBot.services.sms_reminders import start_reminder_polling_worker
        start_reminder_polling_worker()
    except Exception as e:
        print(f"[reminder_worker] Warning: Failed to launch reminder worker: {e}")

    yield


app = FastAPI(
    title="serviceBot Server",
    description="Coordinator for telephony, voice agents, and business configuration portal.",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

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

