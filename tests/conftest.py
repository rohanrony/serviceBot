"""Offline legacy-suite harness: owned database, synthetic secrets, isolated files."""

import builtins
import io
import os
import socket
import sys
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn

ROOT = Path(__file__).resolve().parents[1]
_artifact_parent = Path(os.getenv("TEST_ARTIFACTS_DIR") or tempfile.gettempdir())
_artifact_parent.mkdir(parents=True, exist_ok=True)
TEST_ARTIFACTS_DIR = Path(tempfile.mkdtemp(prefix="voice-unit-", dir=_artifact_parent))
TEST_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
TEST_LOG_FILE = os.getenv("TEST_LOG_FILE") or str(TEST_ARTIFACTS_DIR / "test.log")
os.environ["LOG_FILE"] = TEST_LOG_FILE
sys.dont_write_bytecode = True
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["LOG_LEVEL"] = "CRITICAL"
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
            "LANGCHAIN_",
            "LANGSMITH_",
        )
    ):
        os.environ.pop(key, None)
os.environ.update(
    ENCRYPTION_KEY="unit-only-encryption-key",
    OPENAI_API_KEY="synthetic-unit-key",
    ELEVENLABS_API_KEY="synthetic-unit-elevenlabs-key",
    ELEVENLABS_AGENT_ID="synthetic-unit-agent",
    TWILIO_ACCOUNT_SID="AC" + "0" * 32,
    TWILIO_AUTH_TOKEN="synthetic-unit-token",
    TWILIO_FROM_NUMBER="+15550100999",
    TWILIO_WHATSAPP_FROM_NUMBER="+15550100888",
)

test_db_url = (
    os.getenv("TEST_DATABASE_URL") or "postgresql://localhost/voice_service_test"
)
os.environ["DATABASE_URL"] = test_db_url

# Legacy config readers bypass portal.CONFIG_PATH. Redirect only these exact
# paths, including Path.open(), rather than mocking configuration/domain logic.
CONFIG_FILE = TEST_ARTIFACTS_DIR / "config.json"
PROMPT_FILE = TEST_ARTIFACTS_DIR / "system_prompt.txt"
PROMPT_FILE.write_bytes((ROOT / "serviceBot/system_prompt.txt").read_bytes())
_redirects = {
    str(ROOT / "serviceBot/config.json"): str(CONFIG_FILE),
    str(ROOT / "serviceBot/system_prompt.txt"): str(PROMPT_FILE),
}


def _mapped_path(path):
    if isinstance(path, (str, bytes, os.PathLike)):
        return _redirects.get(os.path.abspath(os.fsdecode(path)), path)
    return path


_original_open, _original_io_open, _original_exists = (
    builtins.open,
    io.open,
    os.path.exists,
)
_files = ExitStack()
_files.enter_context(
    patch(
        "builtins.open",
        lambda path, *args, **kwargs: _original_open(
            _mapped_path(path), *args, **kwargs
        ),
    )
)
_files.enter_context(
    patch(
        "io.open",
        lambda path, *args, **kwargs: _original_io_open(
            _mapped_path(path), *args, **kwargs
        ),
    )
)
_files.enter_context(
    patch("os.path.exists", lambda path: _original_exists(_mapped_path(path)))
)

# Redirect KB_DIR to writeable workspace scratch path
import serviceBot.api.portal as portal_mod

WORKSPACE_SCRATCH = str(TEST_ARTIFACTS_DIR / "kb_documents")
portal_mod.CONFIG_PATH = str(CONFIG_FILE)
portal_mod.SYSTEM_PROMPT_PATH = str(PROMPT_FILE)
portal_mod.KB_DIR = WORKSPACE_SCRATCH
os.makedirs(portal_mod.KB_DIR, exist_ok=True)
portal_mod.save_config(portal_mod.load_config())


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    """The supplied URL is connection configuration, never a reset target."""
    from serviceBot.db import connection

    params = parse_dsn(test_db_url)
    host = params.get("host", "localhost")
    if host not in {"localhost", "127.0.0.1", "::1"} or not params.get(
        "dbname", ""
    ).endswith("_test"):
        pytest.fail(
            "Use a loopback TEST_DATABASE_URL with a database name ending in _test"
        )
    params.update(host=host, hostaddr="127.0.0.1" if host == "localhost" else host)
    params.pop("service", None)
    params.pop("options", None)
    admin = psycopg2.connect(
        make_dsn(**{**params, "dbname": "postgres", "connect_timeout": "3"})
    )
    admin.autocommit = True
    database = "voice_unit_" + uuid.uuid4().hex + "_test"
    created = False
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(database)
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
        owned_dsn = f"postgresql://{authority}/{database}?{urlencode(extra)}"
        os.environ["TEST_DATABASE_URL"] = owned_dsn
        os.environ["DATABASE_URL"] = owned_dsn
        connection.close_db_pool()
        connection.init_db(force=True)
        from serviceBot.db.seed import seed_db

        seed_db(force=True)
        yield
    finally:
        connection.close_db_pool()
        if created:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(database)
                    )
                )
        admin.close()
        os.environ["TEST_DATABASE_URL"] = test_db_url
        os.environ["DATABASE_URL"] = test_db_url


@pytest.fixture(autouse=True)
def offline_sockets(monkeypatch):
    connect = socket.socket.connect

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise AssertionError("Unit tests block unmocked external sockets")
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_connect)


@pytest.fixture(autouse=True)
def mock_google_events():
    from unittest.mock import MagicMock, patch

    dummy_res = MagicMock()
    dummy_res.status_code = 200
    dummy_res.json.return_value = {}
    dummy_res.text = "{}"

    with (
        patch(
            "serviceBot.services.google_calendar.fetch_agent_events", return_value=[]
        ),
        patch("serviceBot.db.queries.fetch_agent_events", return_value=[]),
        patch(
            "serviceBot.services.google_calendar.create_agent_calendar_event",
            return_value=True,
        ),
        patch(
            "serviceBot.services.gmail.create_admin_calendar_event", return_value=True
        ),
        patch("serviceBot.services.gmail.send_booking_notification", return_value=True),
        patch("httpx.get", return_value=dummy_res),
        patch("httpx.post", return_value=dummy_res),
        patch("httpx.AsyncClient.get", return_value=dummy_res),
        patch("httpx.AsyncClient.post", return_value=dummy_res),
    ):
        yield


def pytest_sessionfinish(session, exitstatus):
    from serviceBot.db.connection import close_db_pool

    try:
        close_db_pool()
    finally:
        _files.close()


@pytest.fixture
def dummy_appointment_id():
    from serviceBot.db.connection import dict_cursor, get_db_connection

    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES ('Test Cust', '+15550199999') ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;"
        )
        cust_id = cursor.fetchone()["id"]
        cursor.execute(
            "SELECT id FROM vehicles WHERE customer_id = %s LIMIT 1;", (cust_id,)
        )
        row = cursor.fetchone()
        if row:
            veh_id = row["id"]
        else:
            cursor.execute(
                "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Toyota', 'Camry', 2020) RETURNING id;",
                (cust_id,),
            )
            veh_id = cursor.fetchone()["id"]
        cursor.execute(
            "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status, booking_time) VALUES (%s, %s, 'Oil Change', 'Routine oil change', 'pending', '2026-10-25 14:00:00') RETURNING id;",
            (cust_id, veh_id),
        )
        return cursor.fetchone()["id"]
