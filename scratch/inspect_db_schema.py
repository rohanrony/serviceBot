import os
import sys

# Add root folder to sys.path so we can import serviceBot
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Force test database URL
os.environ["DATABASE_URL"] = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"

from serviceBot.db.connection import init_db, get_db_connection
import sqlite3

# Initialize
init_db()

db_path = os.environ["DATABASE_URL"]
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(service_requests);")
columns = [row[1] for row in cursor.fetchall()]
print("service_requests columns:", columns)

cursor.execute("PRAGMA table_info(staff_agents);")
columns_sa = [row[1] for row in cursor.fetchall()]
print("staff_agents columns:", columns_sa)

cursor.execute("PRAGMA table_info(user_google_accounts);")
columns_uga = [row[1] for row in cursor.fetchall()]
print("user_google_accounts columns:", columns_uga)

conn.close()

# Cleanup
if os.path.exists(db_path):
    os.remove(db_path)
