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
if not api_key:
    print("Error: Missing ELEVENLABS_API_KEY in .env")
    exit(1)

headers = {"xi-api-key": api_key}

# ID of the new valid active webhook
webhook_id = "7c3ca23c1ad4499b8a36b92cc1abf8ce"

payload = {
    "webhooks": {
        "post_call_webhook_id": webhook_id,
        "events": ["transcript"],
        "transcript_format": "json",
        "send_audio": False
    }
}

print(f"Sending PATCH request to /v1/convai/settings with webhook {webhook_id}...")
try:
    res = httpx.patch("https://api.elevenlabs.io/v1/convai/settings", json=payload, headers=headers)
    print("Status Code:", res.status_code)
    if res.status_code == 200:
        print("Success! Updated Workspace settings response:")
        print(json.dumps(res.json(), indent=2))
    else:
        print("Failed:", res.text)
except Exception as e:
    print("Request failed:", e)
