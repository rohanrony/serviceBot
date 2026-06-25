import os
import httpx
import json
from dotenv import load_dotenv

load_dotenv(".env")
api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

if not api_key or not agent_id:
    print("Error: Missing API key or Agent ID in .env")
    exit(1)

headers = {"xi-api-key": api_key}
url = f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}"

print(f"Fetching configuration for Agent ID: {agent_id}")
try:
    res = httpx.get(url, headers=headers)
    if res.status_code == 200:
        print("\nAgent Configuration:")
        print(json.dumps(res.json(), indent=2))
    else:
        print(f"Error fetching agent: {res.status_code} - {res.text}")
except Exception as e:
    print(f"Request failed: {e}")
