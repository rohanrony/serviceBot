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

try:
    res = httpx.get(url, headers=headers)
    if res.status_code == 200:
        print(json.dumps(res.json(), indent=2))
    else:
        print(f"Error: {res.status_code} - {res.text}")
except Exception as e:
    print(f"Failed: {e}")
