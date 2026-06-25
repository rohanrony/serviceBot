import os
import httpx
import json
import re
from dotenv import load_dotenv

# 1. Load env variables
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

if not api_key or not agent_id:
    print("Error: Missing ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID in .env")
    exit(1)

headers = {"xi-api-key": api_key}

# 2. Find current ngrok public URL from local tunnels
new_ngrok_url = None
for port in [4040, 4041, 4042]:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/tunnels")
        if r.status_code == 200:
            data = r.json()
            tunnels = data.get("tunnels", [])
            if tunnels:
                new_ngrok_url = tunnels[0]["public_url"]
                print(f"Detected active ngrok URL on port {port}: {new_ngrok_url}")
                break
    except Exception:
        continue

if not new_ngrok_url:
    print("Error: No active ngrok tunnels found. Is ngrok running?")
    exit(1)

webhook_target_url = f"{new_ngrok_url}/api/v1/telephony/webhook"
print(f"Target webhook URL will be: {webhook_target_url}")

# 3. Fetch current workspace webhooks to find existing one to delete
print("\nFetching existing workspace webhooks...")
webhooks_to_delete = []
try:
    r = httpx.get("https://api.elevenlabs.io/v1/workspace/webhooks", headers=headers)
    if r.status_code == 200:
        webhooks_data = r.json()
        webhooks_list = webhooks_data.get("webhooks", [])
        for wh in webhooks_list:
            # We identify the old hook either by name or URL
            wh_name = wh.get("name")
            wh_id = wh.get("webhook_id")
            wh_url = wh.get("webhook_url") or wh.get("url")
            if wh_name == "post call record" or (wh_url and "/api/v1/telephony/webhook" in wh_url):
                print(f"Found old webhook to delete: '{wh_name}' (ID: {wh_id}, URL: {wh_url})")
                webhooks_to_delete.append(wh_id)
except Exception as e:
    print(f"Failed to fetch workspace webhooks: {e}")

# 4. Create a new workspace webhook
print("\nCreating new workspace webhook...")
new_webhook_id = None
create_payload = {
    "settings": {
        "name": "post call record",
        "webhookUrl": webhook_target_url,
        "authType": "hmac"
    }
}
try:
    r = httpx.post("https://api.elevenlabs.io/v1/workspace/webhooks", json=create_payload, headers=headers)
    if r.status_code in [200, 201]:
        res_data = r.json()
        new_webhook_id = res_data.get("webhook_id")
        print(f"Successfully created new webhook! ID: {new_webhook_id}")
    else:
        print(f"Error creating webhook: {r.status_code} - {r.text}")
        exit(1)
except Exception as e:
    print(f"Request failed: {e}")
    exit(1)

# 5. Assign new webhook to the agent's workspace overrides
print(f"\nAssigning new webhook {new_webhook_id} to Agent {agent_id}...")
agent_patch_payload = {
    "conversation_config": {
        "workspace_overrides": {
            "webhooks": {
                "post_call_webhook_id": new_webhook_id,
                "events": ["transcript"],
                "transcript_format": "json",
                "send_audio": False
            }
        }
    }
}
try:
    r = httpx.patch(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", json=agent_patch_payload, headers=headers)
    if r.status_code == 200:
        print("Successfully updated agent overrides with the new webhook ID!")
    else:
        print(f"Error updating agent: {r.status_code} - {r.text}")
except Exception as e:
    print(f"Request failed: {e}")

# 6. Clean up old webhooks
for old_id in webhooks_to_delete:
    print(f"\nDeleting old webhook {old_id}...")
    try:
        r = httpx.delete(f"https://api.elevenlabs.io/v1/workspace/webhooks/{old_id}", headers=headers)
        if r.status_code == 200:
            print("Successfully deleted old webhook!")
        else:
            print(f"Error deleting old webhook: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"Request failed to delete webhook: {e}")

print("\nWebhook sync and assignment completed successfully!")
