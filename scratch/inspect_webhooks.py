import os
import httpx
import json
from dotenv import load_dotenv

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")

if not api_key:
    print("Error: Missing API key in .env")
    exit(1)

headers = {"xi-api-key": api_key}
url = "https://api.elevenlabs.io/v1/workspace/webhooks"

print("Fetching ElevenLabs workspace webhooks...")
try:
    res = httpx.get(url, headers=headers)
    if res.status_code == 200:
        print("\nWebhooks:")
        print(json.dumps(res.json(), indent=2))
    else:
        print(f"Error fetching webhooks: {res.status_code} - {res.text}")
except Exception as e:
    print(f"Request failed: {e}")
