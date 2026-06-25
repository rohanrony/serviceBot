import os
import httpx
from dotenv import load_dotenv

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
old_webhook_id = "4f50acb506204427ae9cc3f68cc82769"

headers = {"xi-api-key": api_key}
url = f"https://api.elevenlabs.io/v1/workspace/webhooks/{old_webhook_id}"

print(f"Sending DELETE request to {url}...")
try:
    res = httpx.delete(url, headers=headers)
    print("Status Code:", res.status_code)
    print("Response Text:", res.text)
except Exception as e:
    print(f"Request failed: {e}")
