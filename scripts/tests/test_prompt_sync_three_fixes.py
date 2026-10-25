import asyncio
import os
import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock, patch
from contextlib import contextmanager

from serviceBot.api import portal
from serviceBot.services.prompt_service import (
    update_prompt_business_hours,
    RECOGNIZED_SCHEDULE_RE,
)


# ==============================================================================
# Issue 1 Tests: Database publication locking
# ==============================================================================

class MockDbCursor:
    def __init__(self, execution_log):
        self.log = execution_log

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, sql_query, params=None):
        self.log.append(("execute", sql_query.strip(), params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class MockDbConnection:
    def __init__(self, execution_log):
        self.log = execution_log
        self.closed = 0

    def cursor(self, *args, **kwargs):
        return MockDbCursor(self.log)

    def commit(self):
        self.log.append("commit")

    def rollback(self):
        self.log.append("rollback")

    def close(self):
        self.closed = 1
        self.log.append("close")


@pytest.fixture
def mock_db_pool():
    execution_log = []
    conn = MockDbConnection(execution_log)
    pool_events = []

    @contextmanager
    def mock_get_db_connection():
        pool_events.append("enter_ctx")
        try:
            yield conn
        finally:
            pool_events.append("exit_ctx")

    return {
        "conn": conn,
        "log": execution_log,
        "pool_events": pool_events,
        "get_db_connection": mock_get_db_connection,
    }


def test_db_advisory_lock_lifecycle_executes_sql_and_returns_connection(mock_db_pool, monkeypatch):
    """
    Assert:
    - Connection context manager is entered and retained throughout publication
    - Lock SQL (SELECT pg_advisory_lock(%s)) executes with agent lock ID
    - Unlock SQL (SELECT pg_advisory_unlock(%s)) executes on exit
    - Connection is returned through context manager (__exit__)
    """
    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_db_pool["get_db_connection"])

    agent_id = "test-agent-lifecycle"
    expected_lock_id = portal._get_agent_advisory_lock_id(agent_id)

    async def run_lifecycle():
        async with portal.agent_publication_boundary(agent_id):
            # Verify lock acquired while inside boundary
            assert "enter_ctx" in mock_db_pool["pool_events"]
            assert ("execute", "SELECT pg_advisory_lock(%s)", (expected_lock_id,)) in mock_db_pool["log"]
            # Verify connection has NOT been exited yet
            assert "exit_ctx" not in mock_db_pool["pool_events"]

    asyncio.run(run_lifecycle())

    # Verify unlock executed and context exited
    assert ("execute", "SELECT pg_advisory_unlock(%s)", (expected_lock_id,)) in mock_db_pool["log"]
    assert "exit_ctx" in mock_db_pool["pool_events"]


def test_db_advisory_lock_cleanup_on_provider_failure(mock_db_pool, monkeypatch):
    """
    Assert that if an error occurs during publication (provider HTTP error/timeout),
    cleanup runs in finally: unlock SQL executes, connection context exits, and async lock is released.
    """
    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_db_pool["get_db_connection"])

    agent_id = "test-agent-fail-cleanup"
    expected_lock_id = portal._get_agent_advisory_lock_id(agent_id)

    async def run_failing_boundary():
        async with portal.agent_publication_boundary(agent_id):
            raise RuntimeError("Simulated ElevenLabs API 500 error during publication")

    with pytest.raises(RuntimeError, match="Simulated ElevenLabs API 500"):
        asyncio.run(run_failing_boundary())

    # Unlock must have executed despite exception
    assert ("execute", "SELECT pg_advisory_unlock(%s)", (expected_lock_id,)) in mock_db_pool["log"]
    assert "exit_ctx" in mock_db_pool["pool_events"]

    # Local async lock must be released (not left held)
    async_lock = portal._get_agent_async_lock(agent_id)
    assert not async_lock.locked()


def test_independent_publishers_for_same_agent_cannot_overlap(mock_db_pool, monkeypatch):
    """
    Assert that concurrent publishers for the same agent cannot overlap.
    Publisher 1 retains boundary while Publisher 2 waits, ensuring serial execution.
    """
    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_db_pool["get_db_connection"])

    agent_id = "test-agent-concurrency"
    active_publishers = []
    overlap_detected = False

    async def publisher(pub_id: int, hold_seconds: float):
        nonlocal overlap_detected
        async with portal.agent_publication_boundary(agent_id):
            active_publishers.append(pub_id)
            if len(active_publishers) > 1:
                overlap_detected = True
            await asyncio.sleep(hold_seconds)
            active_publishers.remove(pub_id)

    async def run_both():
        t1 = asyncio.create_task(publisher(1, 0.05))
        t2 = asyncio.create_task(publisher(2, 0.05))
        await asyncio.gather(t1, t2)

    asyncio.run(run_both())
    assert not overlap_detected, "Publishers for the same agent must never overlap in publication boundary"


def test_db_lock_acquisition_failure_reported_honestly_when_required(monkeypatch):
    """
    When database coordination is required (require_db=True or REQUIRE_DB_LOCK=1),
    failure to connect to DB or acquire advisory lock must raise RuntimeError, not swallow silently.
    """
    def failing_get_db_connection():
        raise ConnectionError("Database connection refused")

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", failing_get_db_connection)

    # When require_db=True, it must raise RuntimeError
    agent_id = "test-agent-honesty"
    with pytest.raises(RuntimeError, match="Database publication lock could not be acquired"):
        portal._acquire_db_agent_lock(agent_id, require_db=True)

    # When REQUIRE_DB_LOCK env var is set, it must raise RuntimeError
    monkeypatch.setenv("REQUIRE_DB_LOCK", "1")
    with pytest.raises(RuntimeError, match="Database publication lock could not be acquired"):
        portal._acquire_db_agent_lock(agent_id, require_db=False)


# ==============================================================================
# Issue 2 Tests: Split-schedule parsing and repeated saves
# ==============================================================================

def test_split_schedule_repeated_save_idempotent():
    """Save 9 AM–12 PM and 2 PM–5 PM twice; output remains identical."""
    initial_prompt = "Business hours: Monday-Friday 9:00 AM - 5:00 PM ET."

    # First save with split hours (9 AM-12 PM, 2 PM-5 PM)
    save1 = update_prompt_business_hours(
        initial_prompt,
        start_hour=9,
        end_hour=17,
        business_days=[0, 1, 2, 3, 4],
        timezone_str="America/New_York",
        business_hours=[9, 10, 11, 14, 15, 16],
    )
    assert "9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET." in save1

    # Second save using the exact output of save1
    save2 = update_prompt_business_hours(
        save1,
        start_hour=9,
        end_hour=17,
        business_days=[0, 1, 2, 3, 4],
        timezone_str="America/New_York",
        business_hours=[9, 10, 11, 14, 15, 16],
    )

    # Third save to guarantee idempotency across multiple cycles
    save3 = update_prompt_business_hours(
        save2,
        start_hour=9,
        end_hour=17,
        business_days=[0, 1, 2, 3, 4],
        timezone_str="America/New_York",
        business_hours=[9, 10, 11, 14, 15, 16],
    )

    assert save1 == save2, f"Repeated save duplicated or altered output:\nSave 1: {save1}\nSave 2: {save2}"
    assert save2 == save3, f"Third save diverged:\nSave 2: {save2}\nSave 3: {save3}"
    assert save2.count("2:00 PM - 5:00 PM") == 1


def test_split_schedule_change_to_single_interval_cleans_obsolete_hours():
    """Change split schedule (9 AM-12 PM & 2 PM-5 PM) to 8 AM–4 PM; no obsolete interval remains."""
    split_prompt = "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET."

    updated = update_prompt_business_hours(
        split_prompt,
        start_hour=8,
        end_hour=16,
        business_days=[0, 1, 2, 3, 4],
        timezone_str="America/New_York",
        business_hours=[8, 9, 10, 11, 12, 13, 14, 15],
    )

    assert "8:00 AM - 4:00 PM ET." in updated
    assert "9:00 AM" not in updated
    assert "12:00 PM" not in updated
    assert "2:00 PM" not in updated
    assert "5:00 PM" not in updated
    assert "and" not in updated


def test_split_schedule_change_one_split_to_another():
    """Change one split schedule to another without retaining obsolete intervals."""
    prompt_split1 = "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET."

    # Update to 8 AM - 11 AM and 1 PM - 6 PM
    prompt_split2 = update_prompt_business_hours(
        prompt_split1,
        start_hour=8,
        end_hour=18,
        business_days=[0, 1, 2, 3, 4],
        timezone_str="America/New_York",
        business_hours=[8, 9, 10, 13, 14, 15, 16, 17],
    )

    assert "8:00 AM - 11:00 AM and 1:00 PM - 6:00 PM ET." in prompt_split2
    assert "9:00 AM" not in prompt_split2
    assert "12:00 PM" not in prompt_split2
    assert "2:00 PM" not in prompt_split2
    assert "5:00 PM" not in prompt_split2


def test_preserve_custom_instructions_semicolon_period_and_next_line():
    """Preserve semicolon-separated, period-separated, and next-line custom instructions idempotently."""
    # 1. Semicolon-separated
    semi_prompt = "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET; by appointment only on Saturdays."
    semi_save1 = update_prompt_business_hours(semi_prompt, start_hour=8, end_hour=16)
    assert "8:00 AM - 4:00 PM ET; by appointment only on Saturdays." in semi_save1
    semi_save2 = update_prompt_business_hours(semi_save1, start_hour=8, end_hour=16)
    assert semi_save1 == semi_save2

    # 2. Period-separated
    period_prompt = "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET. Note: closed on national holidays."
    period_save1 = update_prompt_business_hours(period_prompt, start_hour=8, end_hour=16)
    assert "8:00 AM - 4:00 PM ET. Note: closed on national holidays." in period_save1
    period_save2 = update_prompt_business_hours(period_save1, start_hour=8, end_hour=16)
    assert period_save1 == period_save2

    # 3. Next-line instructions
    next_line_prompt = (
        "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET.\n"
        "Customer parking is available in the rear lot.\n"
        "Please check in at the front desk upon arrival."
    )
    nl_save1 = update_prompt_business_hours(next_line_prompt, start_hour=8, end_hour=16)
    assert "Customer parking is available in the rear lot." in nl_save1
    assert "Please check in at the front desk upon arrival." in nl_save1
    nl_save2 = update_prompt_business_hours(nl_save1, start_hour=8, end_hour=16)
    assert nl_save1 == nl_save2


def test_unrelated_settings_saves_do_not_accumulate_schedule_text():
    """Confirm repeated saves across unrelated settings updates do not accumulate schedule text."""
    prompt = "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET."

    current = prompt
    for _ in range(5):
        current = update_prompt_business_hours(
            current,
            start_hour=9,
            end_hour=17,
            business_days=[0, 1, 2, 3, 4],
            timezone_str="America/New_York",
            business_hours=[9, 10, 11, 14, 15, 16],
        )

    assert current == "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET."


# ==============================================================================
# Issue 3 Tests: Give synchronization failures precedence
# ==============================================================================

def test_sync_ordering_superseded_dev_plus_production_http_500(monkeypatch, tmp_path):
    """
    When dev agent is superseded and production agent returns HTTP 500,
    overall status must be 'failed', retaining per-agent results and failure details.
    """
    dev_id = "agent-dev-500"
    prod_id = "agent-prod-500"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", dev_id)
    monkeypatch.setenv("ELEVENLABS_PRODUCTION_AGENT_ID", prod_id)

    # Isolated config
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(portal, "CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    portal.save_config({"prompt_generation": 2, "system_prompt": "Test Prompt Gen 2"})

    # Mock DB prompt_sync_state: dev is already at published_generation 2, prod is not
    @contextmanager
    def mock_get_db():
        class MockRowConn:
            def cursor(self, *a, **k):
                class C:
                    def __init__(self):
                        self.last_aid = None
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                    def execute(self, q, p=None):
                        if p:
                            self.last_aid = p[0]
                    def fetchone(self):
                        if self.last_aid == dev_id:
                            return {"published_generation": 2, "desired_generation": 2}
                        return None
                    def fetchall(self): return []
                return C()
            def commit(self): pass
        yield MockRowConn()

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_get_db)

    async def mock_patch(client_self, url, json=None, **kwargs):
        if prod_id in url:
            return httpx.Response(status_code=500, text="Internal Server Error: Voice Engine Unavailable")
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)

    # Calling sync for generation 1:
    # Dev: target_gen=1 < published_gen=2 -> superseded
    # Prod: PATCH returns 500 -> failed
    res = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))

    assert res["status"] == "failed", f"Expected failed, got: {res['status']}"
    assert prod_id in res["message"]
    assert "500" in res["message"]
    assert res["agents"][dev_id]["status"] == "superseded"
    assert res["agents"][prod_id]["status"] == "failed"
    assert res["agents"][prod_id]["status_code"] == 500


def test_sync_ordering_superseded_dev_plus_production_timeout(monkeypatch, tmp_path):
    """
    When dev agent is superseded and production agent times out,
    overall status must be 'failed', retaining per-agent results and failure details.
    """
    dev_id = "agent-dev-timeout"
    prod_id = "agent-prod-timeout"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", dev_id)
    monkeypatch.setenv("ELEVENLABS_PRODUCTION_AGENT_ID", prod_id)

    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(portal, "CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    portal.save_config({"prompt_generation": 3, "system_prompt": "Test Prompt Gen 3"})

    @contextmanager
    def mock_get_db():
        class MockRowConn:
            def cursor(self, *a, **k):
                class C:
                    def __init__(self):
                        self.last_aid = None
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                    def execute(self, q, p=None):
                        if p:
                            self.last_aid = p[0]
                    def fetchone(self):
                        if self.last_aid == dev_id:
                            return {"published_generation": 3, "desired_generation": 3}
                        return None
                    def fetchall(self): return []
                return C()
            def commit(self): pass
        yield MockRowConn()

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_get_db)

    async def mock_patch(client_self, url, json=None, **kwargs):
        if prod_id in url:
            raise httpx.ReadTimeout("ElevenLabs request timed out after 15s")
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)

    res = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))

    assert res["status"] == "failed", f"Expected failed, got: {res['status']}"
    assert prod_id in res["message"]
    assert "timed out" in res["message"]
    assert res["agents"][dev_id]["status"] == "superseded"
    assert res["agents"][prod_id]["status"] == "failed"
    assert "timed out" in res["agents"][prod_id]["error"]


def test_sync_ordering_superseded_without_failures(monkeypatch, tmp_path):
    """
    When one target is superseded and the other succeeds without failures,
    overall status must be 'superseded'.
    """
    dev_id = "agent-dev-superseded"
    prod_id = "agent-prod-synced"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", dev_id)
    monkeypatch.setenv("ELEVENLABS_PRODUCTION_AGENT_ID", prod_id)

    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(portal, "CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    portal.save_config({"prompt_generation": 2, "system_prompt": "Prompt Gen 2"})

    @contextmanager
    def mock_get_db():
        class MockRowConn:
            def cursor(self, *a, **k):
                class C:
                    def __init__(self):
                        self.last_aid = None
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                    def execute(self, q, p=None):
                        if p:
                            self.last_aid = p[0]
                    def fetchone(self):
                        if self.last_aid == dev_id:
                            return {"published_generation": 2, "desired_generation": 2}
                        return None
                    def fetchall(self): return []
                return C()
            def commit(self): pass
        yield MockRowConn()

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_get_db)

    async def mock_patch(client_self, url, json=None, **kwargs):
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)

    res = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))

    assert res["status"] == "superseded"
    assert res["agents"][dev_id]["status"] == "superseded"
    assert not any(r["status"] == "failed" for r in res["agents"].values())


def test_sync_ordering_all_targets_synced(monkeypatch, tmp_path):
    """
    When all targets succeed (HTTP 200), overall status must be 'synced'.
    """
    dev_id = "agent-dev-synced"
    prod_id = "agent-prod-synced"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", dev_id)
    monkeypatch.setenv("ELEVENLABS_PRODUCTION_AGENT_ID", prod_id)

    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(portal, "CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    portal.save_config({"prompt_generation": 1, "system_prompt": "Prompt Gen 1"})

    @contextmanager
    def mock_get_db():
        class MockRowConn:
            def cursor(self, *a, **k):
                class C:
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                    def execute(self, q, p=None): pass
                    def fetchone(self): return None
                    def fetchall(self): return []
                return C()
            def commit(self): pass
        yield MockRowConn()

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_get_db)

    async def mock_patch(client_self, url, json=None, **kwargs):
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)

    res = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))

    assert res["status"] == "synced"
    assert res["generation"] == 1
    assert res["agents"][dev_id]["status"] == "synced"
    assert res["agents"][prod_id]["status"] == "synced"
