#!/usr/bin/env python3
import os
import sys

def load_env_file():
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip("'\"")

load_env_file()

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from serviceBot.db.connection import get_db_connection, dict_cursor

def fetch_logs(limit=50):
    print(f"📖 Querying last {limit} Render logs from Supabase database...\n")
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("""
                    SELECT id, service_id, instance_id, log_text, log_timestamp, created_at
                    FROM render_logs
                    ORDER BY id DESC
                    LIMIT %s;
                """, (limit,))
                rows = cur.fetchall()
                
                if not rows:
                    print("ℹ️ No logs stored in Supabase 'render_logs' table yet.")
                    return
                
                print(f"✅ Found {len(rows)} log entries:\n")
                print("=" * 80)
                for r in reversed(rows): # Print chronologically
                    ts = r.get('log_timestamp') or r.get('created_at')
                    print(f"[{ts}] {r.get('log_text')}")
                print("=" * 80)
    except Exception as e:
        print(f"❌ Error querying logs from Supabase: {e}")

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    fetch_logs(limit)
