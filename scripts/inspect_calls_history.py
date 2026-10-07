#!/usr/bin/env python3
"""
scripts/inspect_calls_history.py
==============================================================================
Inspects and evaluates recent ElevenLabs Conversational AI calls.
Fetches conversation transcripts, tool calls, latencies, and evaluates
intake & booking criteria.

Usage:
    .venv/bin/python scripts/inspect_calls_history.py --limit 5
    .venv/bin/python scripts/inspect_calls_history.py --limit 3 --evaluate
    .venv/bin/python scripts/inspect_calls_history.py --limit 5 --export scratch/calls.json
==============================================================================
"""

import os
import sys
import argparse
import json
import datetime
from pathlib import Path
import httpx

REPO_ROOT = Path(__file__).parent.parent.resolve()
env_path = REPO_ROOT / ".env"

env_vars = {}
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip().strip("\"'")

api_key = env_vars.get("ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_API_KEY", "")
if not api_key:
    print("❌ Error: ELEVENLABS_API_KEY not found in environment or .env file.")
    sys.exit(1)

headers = {"xi-api-key": api_key}


def evaluate_conversation(transcript: list, tool_calls_log: list) -> dict:
    """Evaluates conversation against key intake and booking criteria."""
    eval_result = {
        "intake_fields_detected": [],
        "tools_called": [tc.get("tool_name") for tc in tool_calls_log],
        "called_check_availability": False,
        "called_book_appointment": False,
        "called_create_service_request": False,
        "score": 0,
        "max_score": 4,
        "notes": []
    }

    full_text = " ".join([str(t.get("message") or "") for t in transcript]).lower()

    # Heuristic vehicle/customer field detection
    common_makes = [
        "honda", "toyota", "ford", "chevrolet", "chevy", "nissan", "bmw", "audi",
        "subaru", "lexus", "acura", "infiniti", "hyundai", "kia", "mazda", "jeep",
        "ram", "dodge", "gmc", "volkswagen", "volvo", "mercedes"
    ]
    if any(k in full_text for k in common_makes):
        eval_result["intake_fields_detected"].append("vehicle_make")
    if any(k in full_text for k in ["201", "202"]):
        eval_result["intake_fields_detected"].append("vehicle_year")
    if any(k in full_text for k in ["oil", "brake", "tire", "battery", "noise", "leak", "inspection", "engine", "diagnostic"]):
        eval_result["intake_fields_detected"].append("issue_description")

    # Tool checks
    tool_names = eval_result["tools_called"]
    if "check_availability" in tool_names:
        eval_result["called_check_availability"] = True
        eval_result["score"] += 1
    else:
        eval_result["notes"].append("Missed check_availability call")

    if "book_appointment" in tool_names:
        eval_result["called_book_appointment"] = True
        eval_result["score"] += 2
    elif "create_service_request" in tool_names:
        eval_result["called_create_service_request"] = True
        eval_result["score"] += 1
    else:
        eval_result["notes"].append("No booking or service request tool called")

    if len(eval_result["intake_fields_detected"]) >= 2:
        eval_result["score"] += 1
    else:
        eval_result["notes"].append("Incomplete vehicle intake details in dialogue")

    return eval_result


def main():
    parser = argparse.ArgumentParser(description="ElevenLabs Conversation Inspector & Evaluator")
    parser.add_argument("--limit", type=int, default=5, help="Number of recent conversations to fetch (default: 5)")
    parser.add_argument("--evaluate", action="store_true", help="Run automated evaluation rubric on transcripts")
    parser.add_argument("--export", type=str, default="", help="Optional JSON file path to export fetched call details")
    args = parser.parse_args()

    print(f"📡 Fetching last {args.limit} conversations from ElevenLabs ConvAI...")

    with httpx.Client(timeout=20.0) as client:
        r = client.get("https://api.elevenlabs.io/v1/convai/conversations", headers=headers, params={"page_size": args.limit})
        if r.status_code != 200:
            print(f"❌ Failed to fetch conversations: {r.status_code} {r.text}")
            sys.exit(1)

        convs = r.json().get("conversations", [])
        print(f"✅ Found {len(convs)} conversation(s).\n")

        detailed_records = []

        for idx, c in enumerate(convs, 1):
            cid = c.get("conversation_id")
            dt = datetime.datetime.fromtimestamp(c.get("start_time_unix_secs", 0))
            duration = c.get("call_duration_secs", 0)

            print("=" * 70)
            print(f"📞 CALL #{idx} | ID: {cid}")
            print(f"   Timestamp: {dt} | Duration: {duration}s | Status: {c.get('status', 'N/A')}")
            print("-" * 70)

            detail_res = client.get(f"https://api.elevenlabs.io/v1/convai/conversations/{cid}", headers=headers)
            if detail_res.status_code != 200:
                print(f"   ⚠️ Could not fetch details: {detail_res.status_code}")
                continue

            d = detail_res.json()
            transcript = d.get("transcript", [])
            tool_calls = []

            for t in transcript:
                role = t.get("role", "unknown")
                msg = (t.get("message") or "").strip()
                t_tools = t.get("tool_calls") or []

                prefix = "🤖 [Agent]" if role == "agent" else ("👤 [User]" if role == "user" else f"[{role}]")
                if msg:
                    print(f"  {prefix}: {msg}")

                if t_tools:
                    for tc in t_tools:
                        tool_calls.append(tc)
                        t_name = tc.get("tool_name")
                        t_params = tc.get("params_as_json")
                        print(f"     ⚙️ TOOL: {t_name} -> {t_params}")

            if args.evaluate:
                ev = evaluate_conversation(transcript, tool_calls)
                print("\n  📊 EVALUATION SCORECARD:")
                print(f"     Score: {ev['score']}/{ev['max_score']}")
                print(f"     Tools Invoked: {', '.join(ev['tools_called']) or 'None'}")
                print(f"     Intake Fields: {', '.join(ev['intake_fields_detected']) or 'None'}")
                if ev["notes"]:
                    print(f"     Audit Notes: {'; '.join(ev['notes'])}")

            d["_evaluated"] = evaluate_conversation(transcript, tool_calls) if args.evaluate else None
            detailed_records.append(d)
            print()

        if args.export:
            export_path = Path(args.export)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(detailed_records, f, indent=2)
            print(f"💾 Exported {len(detailed_records)} call records to {export_path}")


if __name__ == "__main__":
    main()
