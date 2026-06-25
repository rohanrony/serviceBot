import os
import httpx
import json
from dotenv import load_dotenv

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

headers = {"xi-api-key": api_key}
url = f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}"

# Let's target the exact new webhook ID
new_webhook_id = "437845f4b2244191b6590150ba553a69"

payload = {
    "conversation_config": {
        "workspace_overrides": {
            "webhooks": {
                "post_call_webhook_id": new_webhook_id,
                "events": ["transcript"],
                "transcript_format": "json",
                "send_audio": False
            }
        }
    }
}

print(f"Sending PATCH request to {url}...")
try:
    res = httpx.patch(url, json=payload, headers=headers)
    print("Status Code:", res.status_code)
    print("Response JSON:")
    print(json.dumps(res.json(), indent=2))
except Exception as e:
    print(f"Request failed: {e}")
