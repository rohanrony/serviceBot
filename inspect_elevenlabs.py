import os
import httpx
import json
from dotenv import load_dotenv

# Ensure local connection bypasses proxy
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

# Force override to load the exact key from the .env file
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

headers = {"xi-api-key": api_key}

print("=== ELEVENLABS API INSPECTION ===")
print("Agent ID:", agent_id)
print("Using API Key ending in:", api_key[-8:] if api_key else "None")

print("\n--- Fetching /v1/convai/agents/{agent_id} ---")
try:
    r = httpx.get(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", headers=headers, trust_env=False)
    print("Status:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print("Agent Name:", data.get("name"))
        # Print tools
        conversation_config = data.get("conversation_config", {})
        tools = conversation_config.get("tools", [])
        print(f"Agent has {len(tools)} tools configured:")
        for t in tools:
            print(f" - Tool Name: {t.get('name')}, Type: {t.get('type')}")
            if t.get("type") == "webhook":
                print(f"   URL: {t.get('api_schema', {}).get('url')}")
    else:
        print("Response:", r.text)
except Exception as e:
    print("Error:", e)

print("\n--- Fetching /v1/convai/tools ---")
try:
    r = httpx.get("https://api.elevenlabs.io/v1/convai/tools", headers=headers, trust_env=False)
    print("Status:", r.status_code)
    print("Response:")
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print("Error:", e)
