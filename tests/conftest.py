import os
import pytest
import shutil
import sys

sys.dont_write_bytecode = True

# Force DATABASE_URL to use a separate database for tests if available, fallback to DATABASE_URL
if not os.environ.get("DATABASE_URL") or not os.environ["DATABASE_URL"].startswith("postgresql"):
    os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or "postgresql://localhost/voice_service_test"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Redirect KB_DIR to writeable workspace scratch path
import serviceBot.api.portal as portal_mod
WORKSPACE_SCRATCH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scratch", "test_kb_documents")
portal_mod.KB_DIR = WORKSPACE_SCRATCH
os.makedirs(portal_mod.KB_DIR, exist_ok=True)

@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    from serviceBot.db.connection import get_db_url
    print(f"\n[TEST_DB_PATH_DIAGNOSTIC] DATABASE_URL env: {os.environ.get('DATABASE_URL')}")
    print(f"[TEST_DB_PATH_DIAGNOSTIC] connection.get_db_url(): {get_db_url()}")
    # Set up the database and seed it before any tests run
    try:
        from serviceBot.db.seed import seed_db
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

