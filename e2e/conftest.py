"""Real HTTP/browser tests with disposable PostgreSQL and provider boundaries."""

import os
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import httpx
import psycopg2
import pytest
from playwright.sync_api import sync_playwright
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True
# App imports otherwise reload developer credentials with override=True.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["TESTING"] = "1"
os.environ["LOG_LEVEL"] = "CRITICAL"
os.environ["LOG_FILE"] = ""
for key in tuple(os.environ):
    if key.startswith(
        (
            "TWILIO_",
            "ELEVENLABS_",
            "GOOGLE_",
            "GMAIL_",
            "SMTP_",
            "OPENAI_",
            "ANTHROPIC_",
            "GEMINI_",
            "BETTERSTACK_",
            "LOGTAIL_",
        )
    ):
        os.environ.pop(key, None)
os.environ["ENCRYPTION_KEY"] = "e2e-only-encryption-key"
os.environ["CRON_SECRET"] = "e2e-only-cron-secret"


def pytest_addoption(parser):
    parser.addoption(
        "--e2e-headed", action="store_true", help="Show the E2E Chromium window"
    )


def pytest_collection_modifyitems(items):
    roots = {
        "e2e" if PROJECT_ROOT / "e2e" in Path(item.path).parents else "other"
        for item in items
    }
    if roots == {"e2e", "other"}:
        raise pytest.UsageError(
            "Run e2e/ separately from tests/: they have different database lifecycles."
        )


@pytest.fixture(scope="session")
def isolated_database():
    """Create/drop only our own database; never truncate the supplied database."""
    params = parse_dsn(
        os.getenv("TEST_DATABASE_URL", "postgresql://localhost/voice_service_test")
    )
    host = params.get("host", "localhost")
    if host not in {"localhost", "127.0.0.1", "::1"} or not params.get(
        "dbname", ""
    ).endswith("_test"):
        pytest.fail(
            "E2E requires a loopback TEST_DATABASE_URL with a database name ending in _test."
        )
    # Pin the address as well as the hostname: libpq's PGHOSTADDR/service
    # defaults or a URL hostaddr parameter must not redirect setup elsewhere.
    params["host"] = host
    params["hostaddr"] = "127.0.0.1" if host == "localhost" else host
    params.pop("service", None)
    params.pop("options", None)
    admin_dsn = make_dsn(**{**params, "dbname": "postgres", "connect_timeout": "3"})
    database_name = f"voice_e2e_{uuid.uuid4().hex}_test"
    try:
        admin = psycopg2.connect(admin_dsn)
    except psycopg2.OperationalError:
        pytest.fail(
            "Local PostgreSQL is unavailable. See e2e/README.md; the database user needs CREATEDB."
        )
    admin.autocommit = True
    created = False
    original = {
        key: os.environ.get(key) for key in ("TEST_DATABASE_URL", "DATABASE_URL")
    }
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(database_name)
                )
            )
        created = True
        authority = f"[{host}]" if host == "::1" else host
        if params.get("port"):
            authority += ":" + params["port"]
        if params.get("user"):
            credentials = quote(params["user"], safe="")
            if params.get("password"):
                credentials += ":" + quote(params["password"], safe="")
            authority = credentials + "@" + authority
        extra = {
            key: value
            for key, value in params.items()
            if key not in {"host", "port", "dbname", "user", "password"}
        }
        test_url = f"postgresql://{authority}/{database_name}"
        if extra:
            test_url += "?" + urlencode(extra)
        os.environ["TEST_DATABASE_URL"] = test_url
        os.environ["DATABASE_URL"] = test_url
        from serviceBot.db import connection

        connection.close_db_pool()
        connection.init_db(force=True)
        from serviceBot.db.migrations import available_migrations

        with connection.get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM schema_migrations")
            assert cursor.fetchone()[0] == len(available_migrations()), (
                "Database migrations must complete before E2E tests"
            )
        yield
    finally:
        connection = sys.modules.get("serviceBot.db.connection")
        if connection is not None:
            connection.close_db_pool()
            connection._db_initialized = False
        if created:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        admin.close()
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class MemoryCollection:
    """Chroma storage boundary: real FAQService chunking, no embedding downloads."""

    def __init__(self):
        self.entries = {}

    def add(self, documents, metadatas, ids):
        self.entries.update(
            {key: (doc, meta) for key, doc, meta in zip(ids, documents, metadatas)}
        )

    def delete(self, where):
        self.entries = {
            key: value
            for key, value in self.entries.items()
            if value[1]["filename"] != where["filename"]
        }


@pytest.fixture(autouse=True)
def scenario(isolated_database, tmp_path, monkeypatch):
    """Each test starts with synthetic data and fresh writable configuration."""
    from serviceBot.api import portal
    from serviceBot.db import connection
    from serviceBot.services import booking, encryption, google_calendar
    from serviceBot.services.rag import FAQService

    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(
        portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt")
    )
    monkeypatch.setattr(portal, "KB_DIR", str(tmp_path / "kb"))
    config = portal.load_config()
    config.update(
        gmail_enabled=False, enable_agent_selection=True, business_name="E2E Garage"
    )
    portal.save_config(config)
    collection = MemoryCollection()
    monkeypatch.setattr(
        FAQService,
        "__init__",
        lambda self, **kwargs: setattr(self, "collection", collection),
    )
    # This legacy resolver hardcodes the developer config path. Keep credentials
    # behind a boundary until it supports the same configurable storage as portal.
    monkeypatch.setattr(encryption, "get_active_secret", lambda name: "")
    monkeypatch.setattr(booking, "_IN_FLIGHT_BOOKING_SESSIONS", {})
    # A successful provider read with no external events. Domain availability
    # must still account for PostgreSQL reservations and local blocked slots.
    monkeypatch.setattr(
        google_calendar, "fetch_agent_events", lambda *args, **kwargs: []
    )

    send_sync = httpx.Client._send_single_request
    send_async = httpx.AsyncClient._send_single_request

    def external_response(request):
        if str(request.url) == "https://api.elevenlabs.io/v1/voices":
            return httpx.Response(200, json={"voices": []}, request=request)
        raise AssertionError(f"Unstubbed external HTTP request: {request.url.host}")

    def local_sync(self, request):
        if request.url.host in {"127.0.0.1", "localhost", "testserver"}:
            return send_sync(self, request)
        return external_response(request)

    async def local_async(self, request):
        if request.url.host in {"127.0.0.1", "localhost", "testserver"}:
            return await send_async(self, request)
        return external_response(request)

    monkeypatch.setattr(httpx.Client, "_send_single_request", local_sync)
    monkeypatch.setattr(httpx.AsyncClient, "_send_single_request", local_async)
    connect = socket.socket.connect

    def local_connect(self, address):
        if isinstance(address, tuple) and address[0] not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise AssertionError("E2E does not permit external sockets")
        return connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    # No booking/status/query logic is mocked.
    target = datetime.now(booking.BUSINESS_TZ).replace(tzinfo=None) + timedelta(days=7)
    while target.weekday() > 4:
        target += timedelta(days=1)
    target = target.replace(hour=10, minute=0, second=0, microsecond=0)
    with connection.get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename != 'schema_migrations'"
        )
        tables = [sql.Identifier(row[0]) for row in cursor.fetchall()]
        cursor.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(tables)
            )
        )
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES ('Alex E2E', '+15550100001'), ('Blair E2E', '+15550100002')"
        )
        cursor.execute(
            "INSERT INTO vehicles (customer_id, make, model, year) VALUES (1, 'Toyota', 'Camry', 2020), (2, 'Honda', 'Civic', 2021)"
        )
        cursor.execute(
            "INSERT INTO staff_agents (name, role, email, phone_number) VALUES ('Taylor E2E', 'Technician', 'taylor@example.test', '+15550100003'), ('Morgan E2E', 'Technician', 'morgan@example.test', '+15550100004')"
        )
        cursor.execute(
            "INSERT INTO services (name, description, price_range, duration_minutes) VALUES ('Oil Change', 'Routine oil change', '$79 - $119', 60)"
        )
        cursor.execute(
            "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status, booking_type) VALUES (1, 1, 'Oil Change', 'Routine oil change', 'pending', 'appointment')"
        )
        cursor.execute(
            "INSERT INTO sms_config (environment, quiet_hours_enabled, support_phone_number, auto_responder_template) VALUES ('TEST', FALSE, '+15550100005', 'Thanks; call {support_number}')"
        )
        cursor.execute(
            "INSERT INTO sms_whitelist (phone_number, friendly_name, twilio_verified) VALUES ('+15550100001', 'Alex E2E', TRUE)"
        )
        cursor.execute(
            "INSERT INTO sms_matrix_rules (event_type, recipient_role, channel, enabled) VALUES ('BOOKING', 'admin', 'SMS', FALSE), ('BOOKING', 'admin', 'WHATSAPP', TRUE), ('BOOKING', 'customer', 'SMS', TRUE)"
        )
        cursor.execute(
            "INSERT INTO sms_conversations (customer_phone, state, context_appointment_id) VALUES ('+15550100001', 'HANDOFF_REQUIRED', 1), ('+15550100002', 'IN_PROGRESS', NULL)"
        )
        cursor.execute(
            "INSERT INTO sms_messages (conversation_id, direction, sender_type, sender_name, body) VALUES (1, 'inbound', 'customer', 'Alex E2E', 'Please help with my oil change')"
        )
        for agent in (1, 2):
            for offset in range(0, 120, 15):
                cursor.execute(
                    "INSERT INTO mock_calendar_slots (staff_agent_id, slot_datetime) VALUES (%s, %s)",
                    (agent, target + timedelta(minutes=offset)),
                )
    yield {"start": target, "date": target.date().isoformat(), "collection": collection}


@pytest.fixture
def live_server(scenario):
    import uvicorn

    from serviceBot.main import app

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="error", access_log=False
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                pytest.fail("E2E HTTP server did not start within 10 seconds")
            time.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), (
            "E2E server failed to stop before fixture teardown"
        )


@pytest.fixture
def api(live_server):
    with httpx.Client(base_url=live_server, timeout=10, trust_env=False) as client:
        yield client


@pytest.fixture
def db(scenario):
    """Arrange worker inputs and inspect durable effects in our disposable DB."""
    from serviceBot.db.connection import dict_cursor, get_db_connection

    def execute(statement, parameters=()):
        with get_db_connection() as conn, dict_cursor(conn) as cursor:
            cursor.execute(statement, parameters)
            return (
                [dict(row) for row in cursor.fetchall()] if cursor.description else []
            )

    return execute


@pytest.fixture
def freeze_business_clock(scenario, monkeypatch):
    """Freeze app clocks, not datetime globally or PostgreSQL's transaction clock."""
    import datetime as datetime_module
    from types import SimpleNamespace

    from serviceBot.api import portal, telephony
    from serviceBot.services import booking, quiet_hours, sms_reminders

    def freeze(value):
        current = (
            value.replace(tzinfo=booking.BUSINESS_TZ) if value.tzinfo is None else value
        )

        class FrozenDateTime(datetime_module.datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    current.astimezone(tz)
                    if tz is not None
                    else current.astimezone(booking.BUSINESS_TZ).replace(tzinfo=None)
                )

            @classmethod
            def utcnow(cls):
                return current.astimezone(datetime_module.UTC).replace(tzinfo=None)

        clock_module = SimpleNamespace(**vars(datetime_module))
        clock_module.datetime = FrozenDateTime
        for module in (portal, booking, quiet_hours, sms_reminders):
            monkeypatch.setattr(module, "dt_mod", clock_module)
        monkeypatch.setattr(telephony, "datetime", FrozenDateTime)
        return current

    return freeze


@pytest.fixture(scope="session")
def browser_instance(request):
    headed = (
        request.config.getoption("--e2e-headed")
        or request.config.getoption("--headed", default=False)
        or os.getenv("PLAYWRIGHT_HEADED") == "1"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        yield browser
        browser.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, "rep_" + call.when, outcome.get_result())


@pytest.fixture
def page(browser_instance, live_server, request, tmp_path):
    context = browser_instance.new_context(
        viewport={"width": 1280, "height": 800}, base_url=live_server
    )

    def browser_route(route):
        if urlparse(route.request.url).hostname == "127.0.0.1":
            route.continue_()
        else:
            route.abort()

    context.route("**/*", browser_route)
    page = context.new_page()
    yield page
    report = getattr(request.node, "rep_call", None)
    if report and report.failed:
        page.screenshot(path=str(tmp_path / "failure.png"), full_page=True)
    context.close()
