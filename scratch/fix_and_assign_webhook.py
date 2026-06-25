import os
import httpx
import json
import re
from dotenv import load_dotenv

# Ensure local connection bypasses proxy
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

if not api_key or not agent_id:
    print("Error: Missing ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID in .env")
    exit(1)

headers = {"xi-api-key": api_key}

# 1. Get current ngrok URL
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

target_webhook_url = f"{new_ngrok_url}/api/v1/telephony/webhook"
print(f"Target Webhook URL: {target_webhook_url}")

# 2. Fetch existing webhooks
print("\nFetching existing workspace webhooks...")
webhooks_res = httpx.get("https://api.elevenlabs.io/v1/workspace/webhooks", headers=headers)
if webhooks_res.status_code != 200:
    print(f"Error fetching webhooks: {webhooks_res.status_code} - {webhooks_res.text}")
    exit(1)

webhooks = webhooks_res.json().get("webhooks", [])
print(f"Found {len(webhooks)} workspace webhooks.")

# Filter webhooks that match our endpoint (name 'post call record' or URL matching telephony webhook)
matching_webhooks = []
for wh in webhooks:
    wh_id = wh.get("webhook_id")
    wh_name = wh.get("name")
    wh_url = wh.get("url") or wh.get("webhook_url")
    if wh_name == "post call record" or (wh_url and "/api/v1/telephony/webhook" in wh_url):
        matching_webhooks.append(wh)
        print(f"Matching webhook: ID={wh_id}, Name='{wh_name}', URL='{wh_url}', Disabled={wh.get('is_disabled')}")

# Determine if we already have a matching webhook with the CORRECT url
correct_webhook_id = None
webhooks_to_delete = []

for wh in matching_webhooks:
    wh_id = wh.get("webhook_id")
    wh_url = wh.get("url") or wh.get("webhook_url")
    if wh_url == target_webhook_url and not wh.get("is_disabled") and not correct_webhook_id:
        # Keep the first active webhook with the correct URL
        correct_webhook_id = wh_id
        print(f"Keeping valid active webhook: {wh_id}")
    else:
        # Mark all others for deletion (duplicates or outdated URLs or disabled ones)
        webhooks_to_delete.append(wh_id)

# 3. Create a new webhook if we don't have one with the correct URL
if not correct_webhook_id:
    print("\nNo matching active webhook found for the current ngrok URL. Creating a new one...")
    create_payload = {
        "settings": {
            "name": "post call record",
            "webhookUrl": target_webhook_url,
            "authType": "hmac"
        }
    }
    create_res = httpx.post("https://api.elevenlabs.io/v1/workspace/webhooks", json=create_payload, headers=headers)
    if create_res.status_code in [200, 201]:
        correct_webhook_id = create_res.json().get("webhook_id")
        print(f"Successfully created new webhook! ID: {correct_webhook_id}")
    else:
        print(f"Failed to create webhook: {create_res.status_code} - {create_res.text}")
        exit(1)

# 4. Assign the correct webhook to the agent's root workspace overrides
print(f"\nAssigning webhook {correct_webhook_id} to Agent {agent_id} at ROOT workspace_overrides...")
agent_patch_payload = {
    "workspace_overrides": {
        "webhooks": {
            "post_call_webhook_id": correct_webhook_id,
            "events": ["transcript"],
            "transcript_format": "json",
            "send_audio": False
        }
    }
}

patch_res = httpx.patch(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", json=agent_patch_payload, headers=headers)
if patch_res.status_code == 200:
    print("Agent patched successfully!")
else:
    print(f"Failed to patch agent: {patch_res.status_code} - {patch_res.text}")

# 5. Clean up old/duplicate webhooks
for wh_id in webhooks_to_delete:
    print(f"\nDeleting duplicate/outdated webhook {wh_id}...")
    del_res = httpx.delete(f"https://api.elevenlabs.io/v1/workspace/webhooks/{wh_id}", headers=headers)
    if del_res.status_code == 200:
        print(f"Successfully deleted webhook {wh_id}")
    else:
        print(f"Failed to delete webhook {wh_id}: {del_res.status_code} - {del_res.text}")

# 6. Verify agent's configuration
print("\nVerifying updated agent configuration overrides...")
verify_res = httpx.get(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", headers=headers)
if verify_res.status_code == 200:
    verify_data = verify_res.json()
    print("Updated Workspace Overrides:")
    print(json.dumps(verify_data.get("workspace_overrides"), indent=2))
else:
    print(f"Failed to fetch verification info: {verify_res.status_code} - {verify_res.text}")
