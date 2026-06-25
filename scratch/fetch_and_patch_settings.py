import os
import httpx
import json
from dotenv import load_dotenv

# Ensure local connection bypasses proxy
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

if not api_key:
    print("Error: Missing ELEVENLABS_API_KEY in .env")
    exit(1)

headers = {"xi-api-key": api_key}

print("=== Fetching Workspace ConvAI Settings ===")
try:
    res = httpx.get("https://api.elevenlabs.io/v1/convai/settings", headers=headers)
    print("Status Code:", res.status_code)
    if res.status_code == 200:
        settings_data = res.json()
        print("Settings JSON:")
        print(json.dumps(settings_data, indent=2))
    else:
        print("Failed:", res.text)
except Exception as e:
    print("Request failed:", e)

print("\n=== Fetching Agent Workspace Overrides ===")
try:
    res = httpx.get(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", headers=headers)
    if res.status_code == 200:
        data = res.json()
        print("Agent ID:", data.get("agent_id"))
        print("Agent Name:", data.get("name"))
        print("Workspace Overrides:")
        print(json.dumps(data.get("workspace_overrides"), indent=2))
    else:
        print(f"Failed: {res.status_code} - {res.text}")
except Exception as e:
    print("Error:", e)
