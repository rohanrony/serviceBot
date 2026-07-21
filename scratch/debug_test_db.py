import os
import sys
import sqlite3
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"

from serviceBot.db.connection import get_db_connection, DB_PATH
from serviceBot.db.seed import seed_db

print("DB_PATH:", DB_PATH)
seed_db()

with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM mock_calendar_slots;")
    print("Slots count:", cursor.fetchone()[0])
    
    cursor.execute("SELECT * FROM staff_agents;")
    print("Agents:", [dict(r) for r in cursor.fetchall()])
    
    cursor.execute("SELECT COUNT(*) FROM mock_calendar_slots WHERE staff_agent_id = 1;")
    print("Agent 1 slots count:", cursor.fetchone()[0])
