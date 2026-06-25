import os
import httpx
import json
from dotenv import load_dotenv

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

if not api_key or not agent_id:
    print("Error: Missing ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID in .env")
    exit(1)

headers = {"xi-api-key": api_key}

print("=== 1. Workspace Webhooks ===")
try:
    res = httpx.get("https://api.elevenlabs.io/v1/workspace/webhooks", headers=headers)
    if res.status_code == 200:
        print(json.dumps(res.json(), indent=2))
    else:
        print(f"Failed to fetch webhooks: {res.status_code} - {res.text}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== 2. Agent Configuration ===")
try:
    res = httpx.get(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", headers=headers)
    if res.status_code == 200:
        data = res.json()
        print("Agent ID:", data.get("agent_id"))
        print("Name:", data.get("name"))
        print("Workspace Overrides:")
        print(json.dumps(data.get("workspace_overrides"), indent=2))
    else:
        print(f"Failed to fetch agent: {res.status_code} - {res.text}")
except Exception as e:
    print(f"Error: {e}")
