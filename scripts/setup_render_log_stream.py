#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import urllib.error

# Built-in .env parser (no third-party dependencies required)
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

RENDER_API_KEY = os.getenv("RENDER_API_KEY")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID", "srv-d98r46ucjfls73f5lsgg")
TARGET_LOG_ENDPOINT = "https://servicebot-w6hm.onrender.com/api/v1/render-logs"

if not RENDER_API_KEY:
    print("❌ RENDER_API_KEY missing in .env")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {RENDER_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def make_api_call(url, method="GET", body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            res_text = response.read().decode('utf-8')
            return json.loads(res_text) if res_text else {}
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.reason}")
        print(e.read().decode('utf-8'))
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def main():
    print("🔍 Fetching Render workspace owners...")
    owners = make_api_call("https://api.render.com/v1/owners?limit=10")
    if not owners:
        print("❌ Could not fetch owners.")
        sys.exit(1)

    print(f"Found {len(owners)} owner(s).")
    owner_id = None
    for o in owners:
        owner_obj = o.get("owner", {}) if isinstance(o, dict) and "owner" in o else o
        owner_id = owner_obj.get("id")
        owner_name = owner_obj.get("name")
        print(f"👤 Owner: {owner_name} (ID: {owner_id})")
        if owner_id:
            break

    if not owner_id:
        print("❌ No valid owner_id found.")
        sys.exit(1)

    print(f"\n⚙️ Configuring Log Stream for Owner {owner_id} to endpoint: {TARGET_LOG_ENDPOINT}")
    
    # Payload with required 'preview' setting ('send' or 'drop')
    payload = {
        "endpoint": TARGET_LOG_ENDPOINT,
        "preview": "send"
    }
    
    res = make_api_call(f"https://api.render.com/v1/logs/streams/owner/{owner_id}", method="PUT", body=payload)
    if res:
        print("\n🎉 SUCCESS! Render Log Stream enabled and configured successfully!")
        print(json.dumps(res, indent=2))
    else:
        # Fallback payload formats
        payload_alt = {
            "endpointUrl": TARGET_LOG_ENDPOINT,
            "preview": "send"
        }
        res_alt = make_api_call(f"https://api.render.com/v1/logs/streams/owner/{owner_id}", method="PUT", body=payload_alt)
        if res_alt:
            print("\n🎉 SUCCESS! Render Log Stream enabled!")
            print(json.dumps(res_alt, indent=2))

if __name__ == "__main__":
    main()
