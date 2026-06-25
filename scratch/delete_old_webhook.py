import os
import httpx
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
old_webhook_id = "4f50acb506204427ae9cc3f68cc82769"

print(f"Attempting to delete old webhook {old_webhook_id}...")
try:
    res = httpx.delete(f"https://api.elevenlabs.io/v1/workspace/webhooks/{old_webhook_id}", headers=headers)
    print("Status Code:", res.status_code)
    if res.status_code == 200:
        print("Success! Webhook deleted.")
    else:
        print("Failed:", res.text)
except Exception as e:
    print("Request failed:", e)
