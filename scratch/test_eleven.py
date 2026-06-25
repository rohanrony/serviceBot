import os
import httpx
import traceback
from dotenv import load_dotenv

ENV_PATH = "/Users/rohanroy/Coding/voiceService/.env"
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

headers = {"xi-api-key": api_key}
print(f"API Key start: {api_key[:10]}...")
print(f"Agent ID: {agent_id}")

try:
    res = httpx.get("https://api.elevenlabs.io/v1/convai/tools", headers=headers)
    print("Tools Status:", res.status_code)
    print("Tools Response:", res.text)
except Exception as e:
    print("Error type:", type(e))
    print("Error message:", str(e))
    traceback.print_exc()
