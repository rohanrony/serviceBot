import os
import sys
import json
import httpx
import datetime

env_path = "/Users/rohanroy/Coding/voiceService/.env"
env_vars = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip().strip("\"'")

headers = {"xi-api-key": env_vars["ELEVENLABS_API_KEY"]}

with httpx.Client(timeout=15.0) as client:
    r = client.get("https://api.elevenlabs.io/v1/convai/conversations", headers=headers, params={"page_size": 10})
    convs = r.json().get("conversations", [])
    print(f"Total conversations fetched: {len(convs)}")
    for c in convs:
        cid = c.get("conversation_id")
        dt = datetime.datetime.fromtimestamp(c.get("start_time_unix_secs", 0))
        print(f"\n=======================================================")
        print(f"Conv ID: {cid} | Start: {dt} (local) | Duration: {c.get('call_duration_secs')}s")
        d = client.get(f"https://api.elevenlabs.io/v1/convai/conversations/{cid}", headers=headers).json()
        transcript = d.get("transcript", [])
        for t in transcript:
            role = t.get("role")
            msg = t.get("message")
            tool_calls = t.get("tool_calls")
            print(f"  [{role}]: {msg}")
            if tool_calls:
                for tc in tool_calls:
                    print(f"    TOOL CALL: {tc.get('tool_name')} params={tc.get('params_as_json')}")
