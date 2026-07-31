import sys
import os
import dotenv

sys.path.insert(0, '.')
dotenv.load_dotenv('/Users/rohanroy/Coding/voiceService/.env')

from fastapi.testclient import TestClient
from serviceBot.api.portal import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router, prefix="/api/v1/portal")

client = TestClient(app)

print("--- Testing /api/v1/portal/agents ---")
try:
    res = client.get("/api/v1/portal/agents")
    print("Status:", res.status_code)
    print("Response:", res.json() if res.status_code == 200 else res.text)
except Exception as e:
    print("EXCEPTION:", e)

print("\n--- Testing /api/v1/portal/config ---")
try:
    res = client.get("/api/v1/portal/config")
    print("Status:", res.status_code)
    print("Response:", res.json() if res.status_code == 200 else res.text)
except Exception as e:
    print("EXCEPTION:", e)

print("\n--- Testing /api/v1/portal/agents/1/google/status ---")
try:
    res = client.get("/api/v1/portal/agents/1/google/status")
    print("Status:", res.status_code)
    print("Response:", res.json() if res.status_code == 200 else res.text)
except Exception as e:
    print("EXCEPTION:", e)

print("\n--- Testing /api/v1/portal/agents/1/calendar ---")
try:
    res = client.get("/api/v1/portal/agents/1/calendar")
    print("Status:", res.status_code)
    print("Response:", res.json() if res.status_code == 200 else res.text)
except Exception as e:
    print("EXCEPTION:", e)
