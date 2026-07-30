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
                    os.environ.setdefault(key.strip(), val.strip().strip("'\""))

load_env_file()

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from serviceBot.db.connection import get_db_connection

def create_table():
    print("🚀 Creating 'render_logs' table in Supabase database...")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS render_logs (
                        id SERIAL PRIMARY KEY,
                        service_id VARCHAR(100) DEFAULT NULL,
                        instance_id VARCHAR(100) DEFAULT NULL,
                        log_text TEXT NOT NULL,
                        log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        payload JSONB DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_render_logs_timestamp ON render_logs(log_timestamp);
                    CREATE INDEX IF NOT EXISTS idx_render_logs_service ON render_logs(service_id);
                """)
                conn.commit()
        print("🎉 SUCCESS! 'render_logs' table has been created in your Supabase database!")
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_table()
