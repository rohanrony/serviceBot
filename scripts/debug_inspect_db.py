import os
import sys
import json

def load_env_file():
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    k = key.strip()
                    if k != "LOG_FILE":
                        os.environ[k] = val.strip().strip("'\"")
    os.environ.pop("LOG_FILE", None)

load_env_file()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from serviceBot.db.connection import get_db_connection, dict_cursor

def inspect_db():
    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name;
            """)
            tables = [r['table_name'] for r in cur.fetchall()]
            print("Tables found:", tables)

            for t in ["appointment_reservations", "service_requests", "service_request_audit_log", "mock_calendar_slots", "webhook_events", "customers", "outbox_notifications"]:
                if t in tables:
                    cur.execute(f"SELECT COUNT(*) as count FROM {t};")
                    cnt = cur.fetchone()['count']
                    print(f"Table '{t}' count: {cnt}")
                    if cnt > 0:
                        cur.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 3;")
                        rows = cur.fetchall()
                        print(f"--- Recent rows in {t} ---")
                        for r in rows:
                            cleaned = {k: str(v) if v is not None else None for k, v in r.items()}
                            print(json.dumps(cleaned, indent=2))

if __name__ == "__main__":
    inspect_db()
