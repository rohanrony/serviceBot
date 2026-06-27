import os
import pytest
import shutil
import sys

sys.dont_write_bytecode = True

# Force DATABASE_URL to use a separate database for tests
os.environ["DATABASE_URL"] = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Redirect KB_DIR to writeable scratch path
import serviceBot.api.portal as portal_mod
portal_mod.KB_DIR = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_kb_documents"
os.makedirs(portal_mod.KB_DIR, exist_ok=True)

@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    from serviceBot.db.connection import DB_PATH
    print(f"\n[TEST_DB_PATH_DIAGNOSTIC] DATABASE_URL env: {os.environ.get('DATABASE_URL')}")
    print(f"[TEST_DB_PATH_DIAGNOSTIC] connection.DB_PATH: {DB_PATH}")
    # Set up the database and seed it before any tests run
    from serviceBot.db.seed import seed_db
    seed_db()
    
    yield

    # Clean up the test database after the test session finishes
    test_db = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except OSError:
            pass

    # Clean up the test KB directory
    kb_dir = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_kb_documents"
    if os.path.exists(kb_dir):
        try:
            shutil.rmtree(kb_dir)
        except OSError:
            pass


