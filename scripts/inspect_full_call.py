#!/usr/bin/env python3
import os
import json
import httpx

def main():
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
        r = client.get("https://api.elevenlabs.io/v1/convai/conversations", headers=headers, params={"page_size": 3})
        convs = r.json().get("conversations", [])
        if not convs:
            print("No conversations found")
            return
        last_c = convs[0]
        conv_id = last_c.get("conversation_id")
        print(f"Most recent conversation ID: {conv_id} at {last_c.get('start_time_unix_secs')}")
        d = client.get(f"https://api.elevenlabs.io/v1/convai/conversations/{conv_id}", headers=headers).json()
        with open("scripts/last_call_dump.json", "w") as out:
            json.dump(d, out, indent=2)
        print("Dumped conversation to scripts/last_call_dump.json")
        print("Metadata:", json.dumps(d.get("metadata", {}), indent=2))
        print("Analysis:", json.dumps(d.get("analysis", {}), indent=2))
        transcript = d.get("transcript", [])
        print("Transcript lines:", len(transcript))
        for t in transcript:
            role = t.get('role')
            msg = t.get('message')
            time = t.get('time_in_call_secs')
            tool_calls = t.get('tool_calls')
            tool_results = t.get('tool_results')
            print(f"[{time}s] {role}: {msg}")
            if tool_calls:
                print(f"   TOOL CALLS: {json.dumps(tool_calls, indent=2)}")
            if tool_results:
                print(f"   TOOL RESULTS: {json.dumps(tool_results, indent=2)}")

if __name__ == "__main__":
    main()
