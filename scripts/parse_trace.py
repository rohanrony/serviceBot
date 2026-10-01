#!/usr/bin/env python3
import json

def main():
    with open("scripts/last_call_dump.json") as f:
        d = json.load(f)

    for idx, t in enumerate(d.get("transcript", [])):
        time_s = t.get("time_in_call_secs")
        role = t.get("role")
        msg = t.get("message")
        tool_calls = t.get("tool_calls")
        tool_results = t.get("tool_results")
        if tool_calls:
            for tc in tool_calls:
                name = tc.get("tool_name")
                params = tc.get("params_as_json")
                print(f"[{time_s}s] >>> TOOL CALL: {name} -> {params}")
        if tool_results:
            for tr in tool_results:
                name = tr.get("tool_name")
                val = tr.get("result_value", "")
                print(f"[{time_s}s] <<< TOOL RESULT: {name} -> {val[:300]}")
        if msg and msg != "None":
            print(f"[{time_s}s] {role}: {msg}")

if __name__ == "__main__":
    main()
