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
url = f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}"

# New Webhook ID we want to point the agent to
new_webhook_id = "7f79bf5d35d64c0fb2ef49b1efdc3756"

# Root level payload
payload = {
    "workspace_overrides": {
        "webhooks": {
            "post_call_webhook_id": new_webhook_id,
            "events": ["transcript"],
            "transcript_format": "json",
            "send_audio": False
        }
    }
}

print(f"Sending PATCH request to {url} with root-level workspace_overrides...")
print(json.dumps(payload, indent=2))

try:
    res = httpx.patch(url, json=payload, headers=headers)
    print("Status Code:", res.status_code)
    if res.status_code == 200:
        print("Success! Response JSON:")
        print(json.dumps(res.json().get("workspace_overrides", {}), indent=2))
    else:
        print(f"Failed: {res.text}")
except Exception as e:
    print(f"Request failed: {e}")
