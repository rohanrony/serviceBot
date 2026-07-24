import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.db.connection import get_db_connection, dict_cursor

with get_db_connection() as conn:
    with dict_cursor(conn) as cursor:
        cursor.execute("SELECT id, name, role, email FROM staff_agents;")
        print("=== STAFF AGENTS ===")
        for r in cursor.fetchall():
            print(dict(r))
        
        cursor.execute("SELECT agent_id, provider, email, granted_scopes FROM user_google_accounts;")
        print("=== USER GOOGLE ACCOUNTS ===")
        for r in cursor.fetchall():
            print(dict(r))
