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

    # 1. Seed services catalog and sync to RAG KB
    try:
        from serviceBot.seed_cba_services import main as seed_main
        print("[lifespan] Seeding services catalog...")
        seed_main()
        print("[lifespan] Services catalog seeded and synced successfully.")
    except Exception as e:
        print(f"Warning: Failed to seed services catalog: {e}")

    # 1.5. Sync prompts to ElevenLabs
    try:
        from serviceBot.api.portal import load_config, sync_prompt_to_elevenlabs
        config = load_config()
        system_prompt = config.get("system_prompt")
        await sync_prompt_to_elevenlabs(system_prompt, config.get("first_message"))
        print("[lifespan] Prompts synced to ElevenLabs successfully.")
    except Exception as e:
        print(f"Warning: Failed to sync prompts to ElevenLabs on startup: {e}")

    # 2. Immediately sync all connected agents' Google Calendar → DB slots
    try:
        from serviceBot.services.calendar_sync import sync_all_connected_agents
        results = sync_all_connected_agents(days=30)
        total_new = sum(r.get("created", 0) for r in results.values() if isinstance(r, dict))
        print(f"[calendar_sync] Startup sync complete. Agents synced: {list(results.keys())} | New slots: {total_new}")
    except Exception as e:
        print(f"[calendar_sync] Warning: Startup calendar sync failed: {e}")

    # 3. Start hourly background refresh thread (daemon so it exits with the server)
    sync_thread = threading.Thread(
        target=_run_calendar_sync_loop,
        args=(3600,),
        daemon=True,
        name="calendar-slot-refresh",
    )
    sync_thread.start()
    print("[calendar_sync] Hourly background slot refresh thread started.")

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

# Include API routers
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

