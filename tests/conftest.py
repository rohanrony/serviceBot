import os
import pytest
import shutil
import sys

sys.dont_write_bytecode = True

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

test_db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or "postgresql://localhost/voice_service_test"
os.environ["DATABASE_URL"] = test_db_url
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Redirect KB_DIR to writeable workspace scratch path
import serviceBot.api.portal as portal_mod
WORKSPACE_SCRATCH = os.getenv("TEST_KB_DIR") or "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_kb_documents"
portal_mod.KB_DIR = WORKSPACE_SCRATCH
try:
    os.makedirs(portal_mod.KB_DIR, exist_ok=True)
except Exception as e:
    print(f"Warning: could not create KB_DIR {portal_mod.KB_DIR}: {e}")

@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    from serviceBot.db.connection import get_db_url
    print(f"\n[TEST_DB_PATH_DIAGNOSTIC] DATABASE_URL env: {os.environ.get('DATABASE_URL')}")
    print(f"[TEST_DB_PATH_DIAGNOSTIC] connection.get_db_url(): {get_db_url()}")
    try:
        from serviceBot.db.connection import init_db
        from serviceBot.db.seed import seed_db
        init_db()
        seed_db()
    except Exception as e:
        print(f"[conftest] Warning: Database seeding skipped or failed ({e}). Tests will proceed with mocked fixtures.")
    
    yield

    # Clean up the test KB directory
    if os.path.exists(WORKSPACE_SCRATCH):
        try:
            shutil.rmtree(WORKSPACE_SCRATCH)
        except OSError:
            pass


@pytest.fixture
def dummy_appointment_id():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Test Cust', '+15550199999') ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;")
            cust_id = cursor.fetchone()["id"]
            cursor.execute("SELECT id FROM vehicles WHERE customer_id = %s LIMIT 1;", (cust_id,))
            row = cursor.fetchone()
            if row:
                veh_id = row["id"]
            else:
                cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Toyota', 'Camry', 2020) RETURNING id;", (cust_id,))
                veh_id = cursor.fetchone()["id"]

            cursor.execute(
                "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status, booking_time) VALUES (%s, %s, 'Oil Change', 'Routine oil change', 'pending', '2026-10-25 14:00:00') RETURNING id;",
                (cust_id, veh_id)
            )
            return cursor.fetchone()["id"]


