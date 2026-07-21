#!/usr/bin/env python3
"""
demo_conversation.py
==============================================================================
Interactive and Automated Local Conversation Testing Demo for serviceBot.

Usage:
  python demo_conversation.py [--scenario <booking|callback|faq|handoff|all>] [--interactive]

Examples:
  python demo_conversation.py --scenario booking
  python demo_conversation.py --scenario all
  python demo_conversation.py --interactive
==============================================================================
"""

import sys
import os
import argparse
import json
from serviceBot.conversation_simulator import ConversationSimulator

# Terminal formatting colors
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
RED = "\033[0;31m"
BOLD = "\033[1m"
NC = "\033[0m"

SCENARIOS = {
    "booking": {
        "title": "Scenario 1: Noisy STT & Lazy Caller Appointment Booking Flow",
        "description": "Tests AI reliability with phonetic STT transcriptions, lazy responses, vocal fillers, and misspellings during service intake.",
        "turns": [
            "hey uh i need service for my car i guess",
            "alex... alex smith",
            "five five five... one two three... four five six seven",
            "twenty twenty one toy yota camry",
            "oil chang and like a weird squeaking noise when i stop",
            "check wednesday june 10 open times",
            "yeah 10 am works book it for me"
        ]
    },
    "callback": {
        "title": "Scenario 2: Indecisive Caller & STT Errors (Callback Switch)",
        "description": "Tests AI handling when a caller provides noisy STT info and changes their mind mid-conversation from booking to callback.",
        "turns": [
            "um hi my 20 19 honda civik has grinding brakes when stopping",
            "sarah connor 555 987 6543",
            "actually wait... don't book an appointment right now, just have a manager call me back tomorrow morning instead"
        ]
    },
    "faq": {
        "title": "Scenario 3: Noisy Inquiry with Filler Words & STT Artifacts",
        "description": "Tests AI extraction when caller uses filler words ('like', 'um', 'you guys') and STT transcription artifacts.",
        "turns": [
            "um yeah do you guys have like loaner cars or shuttle service when my car is in the shop?",
            "what time do you guys close on friday?"
        ]
    },
    "handoff": {
        "title": "Scenario 4: Frustrated / Uncooperative Caller (Human Escalation)",
        "description": "Tests immediate human escalation when caller refuses AI and demands a real manager.",
        "turns": [
            "look i don't want to talk to an ai robot, get me a real person or service manager right now!"
        ]
    }
}

def print_banner():
    print(f"\n{BOLD}{CYAN}========================================================================{NC}")
    print(f"{BOLD}{CYAN}             serviceBot Conversation Simulator & Demo                  {NC}")
    print(f"{BOLD}{CYAN}========================================================================{NC}\n")

def print_turn_log(turn_info: dict):
    turn_num = turn_info.get("turn", 0)
    user_text = turn_info.get("user_text")
    assistant_resp = turn_info.get("assistant_response", "")
    tool_calls = turn_info.get("tool_calls", [])

    if user_text:
        print(f"{BOLD}{GREEN}[CALLER (Turn {turn_num})]:{NC} {user_text}")

    if tool_calls:
        print(f"  {BOLD}{YELLOW}🛠️  [TOOL CALLS EXECUTED]:{NC}")
        for tc in tool_calls:
            tool_name = tc.get("tool_name")
            args = tc.get("arguments", {})
            res = tc.get("result", {})
            print(f"    - Function: {BOLD}{tool_name}{NC}")
            print(f"      Arguments: {json.dumps(args)}")
            print(f"      Result: {json.dumps(res)}")

    print(f"{BOLD}{BLUE}[RACHEL (AI Voice Assistant)]:{NC} {assistant_resp}\n")

def run_automated_scenario(sim: ConversationSimulator, scenario_key: str):
    sc_data = SCENARIOS.get(scenario_key)
    if not sc_data:
        print(f"{RED}Unknown scenario key '{scenario_key}'. Available: {list(SCENARIOS.keys())}{NC}")
        return

    print(f"{BOLD}{YELLOW}>>> Executing {sc_data['title']} <<<{NC}")
    print(f"Description: {sc_data['description']}\n")

    sim.reset()
    print(f"{BOLD}{BLUE}[RACHEL (AI Voice Assistant)]:{NC} {sim.first_message}\n")

    for user_turn in sc_data["turns"]:
        turn_result = sim.run_turn(user_turn)
        print_turn_log(turn_result)

    print(f"{BOLD}{GREEN}✓ Completed scenario '{scenario_key}' successfully!{NC}\n")
    print("-" * 75 + "\n")

def run_interactive_session(sim: ConversationSimulator):
    print(f"{BOLD}{YELLOW}>>> Starting Interactive Terminal Chat Session <<<{NC}")
    print("Type your message as the caller and press Enter. Type 'exit' or 'quit' to end.\n")

    sim.reset()
    print(f"{BOLD}{BLUE}[RACHEL (AI Voice Assistant)]:{NC} {sim.first_message}\n")

    while True:
        try:
            user_input = input(f"{BOLD}{GREEN}[YOU (Caller)]:{NC} ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                print(f"\n{BOLD}Ending conversation demo. Goodbye!{NC}")
                break

            turn_result = sim.run_turn(user_input)
            print_turn_log(turn_result)
        except KeyboardInterrupt:
            print(f"\n{BOLD}Session interrupted. Exiting.{NC}")
            break

def load_env_file():
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'").strip('"')
                        if k and k not in os.environ:
                            os.environ[k] = v

def main():
    load_env_file()

    parser = argparse.ArgumentParser(description="serviceBot Local Conversation Simulator & Demo")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()) + ["all"], help="Run pre-scripted dialog test scenario")
    parser.add_argument("--interactive", action="store_true", help="Start interactive CLI conversation session")
    parser.add_argument("--mock", action="store_true", help="Force offline mock mode instead of calling live LLM API")
    parser.add_argument("--model", default="gpt-5.4-nano", help="LLM model to use (default: gpt-5.4-nano)")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default="medium", help="Reasoning effort level for GPT-5/nano models (default: medium)")

    args = parser.parse_args()
    print_banner()

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    use_mock = args.mock or not api_key

    if not use_mock:
        print(f"{BOLD}{GREEN}🤖 Mode: LIVE LLM ({args.model} | reasoning_effort={args.reasoning_effort}){NC}")
        print(f"{YELLOW}Using ElevenLabs System Prompt from config.json with Function Calling & Backend Tools.{NC}\n")
    else:
        print(f"{BOLD}{YELLOW}🧪 Mode: MOCK SIMULATOR ENGINE{NC}")
        print(f"{YELLOW}Running in stateful offline simulation mode.{NC}\n")

    sim = ConversationSimulator(model_name=args.model, reasoning_effort=args.reasoning_effort, use_mock=use_mock)

    if args.interactive:
        run_interactive_session(sim)
    elif args.scenario:
        if args.scenario == "all":
            for sc_key in SCENARIOS:
                run_automated_scenario(sim, sc_key)
        else:
            run_automated_scenario(sim, args.scenario)
    else:
        # Default behavior: run all scenarios automatically
        print("Running all sample dialogue scenarios automatically...\n")
        for sc_key in SCENARIOS:
            run_automated_scenario(sim, sc_key)

if __name__ == "__main__":
    main()
