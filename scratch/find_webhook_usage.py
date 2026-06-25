import os
import httpx
import json
from dotenv import load_dotenv

# Ensure local connection bypasses proxy
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
if not api_key:
    print("Error: Missing ELEVENLABS_API_KEY in .env")
    exit(1)

headers = {"xi-api-key": api_key}
target_webhook_id = "4f50acb506204427ae9cc3f68cc82769"

print("Searching for webhook usage across ElevenLabs resources...")

# 1. Fetch all agents
print("\n=== Fetching all agents ===")
try:
    res = httpx.get("https://api.elevenlabs.io/v1/convai/agents", headers=headers)
    if res.status_code == 200:
        agents_data = res.json()
        agents = agents_data.get("agents", [])
        print(f"Found {len(agents)} agents.")
        for agent in agents:
            agent_id = agent.get("agent_id")
            name = agent.get("name")
            # Fetch details for each agent to check its overrides
            detail_res = httpx.get(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", headers=headers)
            if detail_res.status_code == 200:
                agent_detail = detail_res.json()
                overrides = agent_detail.get("workspace_overrides") or {}
                webhooks = overrides.get("webhooks") or {}
                post_call_id = webhooks.get("post_call_webhook_id")
                if post_call_id == target_webhook_id:
                    print(f"-> Agent '{name}' ({agent_id}) is referencing this webhook in workspace_overrides!")
                elif post_call_id:
                    print(f"Agent '{name}' ({agent_id}) is referencing a different webhook: {post_call_id}")
            else:
                print(f"Failed to fetch details for agent {agent_id}")
    else:
        print("Failed to fetch agents:", res.text)
except Exception as e:
    print("Error fetching agents:", e)

# 2. Fetch phone numbers
print("\n=== Fetching phone numbers ===")
try:
    res = httpx.get("https://api.elevenlabs.io/v1/convai/phone-numbers", headers=headers)
    if res.status_code == 200:
        phone_data = res.json()
        phone_numbers = phone_data if isinstance(phone_data, list) else phone_data.get("phone_numbers", [])
        print(f"Found {len(phone_numbers)} phone numbers.")
        for pn in phone_numbers:
            pn_id = pn.get("phone_number_id")
            num = pn.get("phone_number")
            print(f"Phone number: {num} (ID: {pn_id})")
            print(json.dumps(pn, indent=2))
            if str(target_webhook_id) in json.dumps(pn):
                print(f"-> Phone number {num} references the target webhook!")
    else:
        print("Failed to fetch phone numbers:", res.status_code, res.text)
except Exception as e:
    print("Error fetching phone numbers:", e)

