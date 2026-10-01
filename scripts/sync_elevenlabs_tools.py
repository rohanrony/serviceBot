#!/usr/bin/env python3
"""
Synchronizes all custom voice webhook tools and the latest system prompt
from serviceBot to both ElevenLabs production and development agents.
"""

import os
import json
import httpx

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_PATH = os.path.join(BASE_DIR, ".env")
PROMPT_PATH = os.path.join(BASE_DIR, "serviceBot", "system_prompt.txt")

# Load environment variables directly from .env
env_vars = {}
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip().strip("\"'")

api_key = env_vars.get("ELEVENLABS_API_KEY")
if not api_key:
    print("❌ Error: Missing ELEVENLABS_API_KEY in .env")
    exit(1)

# Default to production webhook URL on Render, or custom base URL
WEBHOOK_URL = os.environ.get("VOICE_WEBHOOK_URL", "https://servicebot-w6hm.onrender.com/api/v1/voice/tools")
headers = {"xi-api-key": api_key}

TARGET_AGENTS = [
    "agent_2501ktmjf3pee2as55y9vx3gdpge", # Production: Davidson Car Care Service Agent
    "agent_7801m3pyjmz4e6tt0mjpwydwreex", # Dev/Test: Local test agent
]

# Read system prompt
system_prompt_text = ""
if os.path.exists(PROMPT_PATH):
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt_text = f.read()

TOOL_DEFINITIONS = [
    {
        "type": "webhook",
        "name": "check_availability",
        "description": "Checks for available calendar slots for booking an appointment starting on or after a preferred date.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "properties": {
                    "preferred_date": {"type": "string", "description": "The date to check in YYYY-MM-DD format (or natural language date)"},
                    "preferred_time": {"type": "string", "description": "Optional specific time or time window to check (e.g. '09:00 AM', '10:00 AM', 'morning', 'afternoon')"},
                    "service_type": {"type": "string", "description": "The requested service"},
                    "booking_type": {"type": "string", "description": "Type of booking: 'appointment' or 'callback'"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "get_customer_appointments",
        "description": "Retrieve all existing upcoming and past scheduled appointments, advisor callbacks, and service requests for a customer using their 10-digit phone number.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["phone"],
                "properties": {
                    "phone": {"type": "string", "description": "The customer 10-digit phone number (e.g. 4242704893)"},
                    "caller_phone": {"type": "string", "description": "Optional calling number (Caller ID) to cross-reference if different from spoken phone"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "reschedule_appointment",
        "description": "Reschedule an existing appointment to a new date and time once verbal customer consent is confirmed.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["phone", "new_appointment_datetime"],
                "properties": {
                    "phone": {"type": "string", "description": "The customer 10-digit phone number"},
                    "caller_phone": {"type": "string", "description": "Optional calling number (Caller ID) to cross-reference"},
                    "new_appointment_datetime": {"type": "string", "description": "The new appointment date and time (YYYY-MM-DD HH:MM:SS format)"},
                    "appointment_id": {"type": "integer", "description": "Optional specific appointment ID to reschedule"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "consolidate_appointment_service",
        "description": "Consolidate an additional service or symptom into an existing upcoming appointment for the same vehicle, recalculating total duration.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["phone", "additional_issue"],
                "properties": {
                    "phone": {"type": "string", "description": "The customer 10-digit phone number"},
                    "additional_issue": {"type": "string", "description": "The new issue or symptom to add to the existing appointment"},
                    "additional_service_type": {"type": "string", "description": "Optional service type for the additional issue"},
                    "additional_duration_minutes": {"type": "integer", "description": "Estimated duration in minutes for the additional service (default 30)"},
                    "appointment_id": {"type": "integer", "description": "Optional specific appointment ID to consolidate into"},
                    "source_appointment_ids": {"type": "string", "description": "Optional comma-separated IDs of other appointments or callbacks being combined/cancelled into this one (e.g. '22, 26'). Those visits will be cancelled so they do not remain open duplicates."}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "book_appointment",
        "description": "Books an appointment slot for a customer at a specific datetime once intake details and schedule are explicitly confirmed.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["phone", "appointment_datetime", "service_type"],
                "properties": {
                    "phone": {"type": "string", "description": "The customer's phone number"},
                    "appointment_datetime": {"type": "string", "description": "The slot datetime in YYYY-MM-DD HH:MM:SS format"},
                    "service_type": {"type": "string", "description": "The type of service requested (e.g. Brake repair)"},
                    "customer_name": {"type": "string", "description": "Customer full name"},
                    "make": {"type": "string", "description": "Vehicle make"},
                    "model": {"type": "string", "description": "Vehicle model"},
                    "year": {"type": "integer", "description": "Vehicle year"},
                    "issue_description": {"type": "string", "description": "Detailed issue description"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "create_service_request",
        "description": "Registers a new vehicle service request ticket in the CRM database.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["customer_name", "phone", "make", "model", "year", "issue_description"],
                "properties": {
                    "customer_name": {"type": "string", "description": "The full name of the customer"},
                    "phone": {"type": "string", "description": "The customer's phone number"},
                    "caller_phone": {"type": "string", "description": "Optional calling number (Caller ID) from {{caller_phone}} if available"},
                    "make": {"type": "string", "description": "The make of the vehicle (e.g. Honda)"},
                    "model": {"type": "string", "description": "The model of the vehicle (e.g. Civic)"},
                    "year": {"type": "integer", "description": "The production year of the vehicle (e.g. 2020)"},
                    "issue_description": {"type": "string", "description": "The issue the customer wants resolved"},
                    "booking_type": {"type": "string", "enum": ["callback", "appointment"], "description": "Type of booking: 'callback' or 'appointment'"},
                    "booking_time": {"type": "string", "description": "Customer preferred callback time window or appointment datetime"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "request_callback",
        "description": "Arrange a callback request when the caller prefers an advisor to call back instead of booking an appointment.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["customer_name", "phone"],
                "properties": {
                    "customer_name": {"type": "string", "description": "Full name of the customer"},
                    "phone": {"type": "string", "description": "Customer 10-digit phone number"},
                    "make": {"type": "string", "description": "Vehicle make"},
                    "model": {"type": "string", "description": "Vehicle model"},
                    "year": {"type": "integer", "description": "Vehicle year"},
                    "preferred_time": {"type": "string", "description": "Preferred callback day or time window, e.g. Tomorrow morning"},
                    "issue_description": {"type": "string", "description": "Description of the vehicle issue or question"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "get_service_fields",
        "description": "Look up service details, price range, duration, and required intake fields for a specific service in the catalog.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["service_name"],
                "properties": {
                    "service_name": {"type": "string", "description": "Name of the service (e.g. Oil Change, Brake Inspection, Tire Rotation)"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "query_knowledge_base",
        "description": "Queries the local knowledge base to answer questions about business hours, pricing, policies, services, or locations.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "required": ["query_text"],
                "properties": {
                    "query_text": {"type": "string", "description": "The customer's question or search query"}
                }
            }
        }
    },
    {
        "type": "webhook",
        "name": "cba_webbook",
        "description": "Transfers the active call to a human customer service representative when the user asks or when resolving the issue becomes too complex.",
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "interruption_mode": "allow",
        "force_pre_tool_speech": False,
        "pre_tool_speech": "auto",
        "assignments": [],
        "execution_mode": "immediate",
        "api_schema": {
            "url": WEBHOOK_URL,
            "method": "POST",
            "request_headers": {},
            "request_body_schema": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Reason for transferring to a human agent"}
                }
            }
        }
    }
]

# Ensure every tool webhook URL includes ?name=<tool_name> for unambiguous routing in FastAPI
for _tool in TOOL_DEFINITIONS:
    _name = _tool["name"]
    _base_url = WEBHOOK_URL.split("?")[0]
    _tool["api_schema"]["url"] = f"{_base_url}?name={_name}"

def sync_agents():
    print(f"🚀 Synchronizing {len(TOOL_DEFINITIONS)} tools & prompt to ElevenLabs agents...")
    print(f"   Base Webhook URL: {WEBHOOK_URL}")

    for agent_id in TARGET_AGENTS:
        print(f"\n📡 Processing agent: {agent_id}...")
        url = f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}"
        resp = httpx.get(url, headers=headers, trust_env=False, timeout=30.0)
        if resp.status_code != 200:
            print(f"  ❌ Failed to fetch agent {agent_id}: {resp.status_code}")
            continue

        agent_data = resp.json()
        agent_name = agent_data.get("name", "Unknown")
        print(f"  Found agent '{agent_name}'")

        patch_payload = {
            "conversation_config": {
                "agent": {
                    "prompt": {
                        "tools": TOOL_DEFINITIONS
                    }
                }
            }
        }
        if system_prompt_text:
            patch_payload["conversation_config"]["agent"]["prompt"]["prompt"] = system_prompt_text

        patch_res = httpx.patch(url, json=patch_payload, headers=headers, trust_env=False, timeout=30.0)
        if patch_res.status_code == 200:
            print(f"  ✅ Successfully synced all 10 tools & prompt to {agent_id}!")
        else:
            print(f"  ❌ Error updating agent {agent_id}: {patch_res.status_code} - {patch_res.text}")

if __name__ == "__main__":
    sync_agents()
