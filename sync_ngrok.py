import os
import re
import httpx
import json
from dotenv import load_dotenv

# Ensure local connection bypasses proxy
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"


# 1. Load env variables
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

if not api_key:
    print("Error: ELEVENLABS_API_KEY is not defined in .env")
    exit(1)

import subprocess

# 2. Query local ngrok API to find current public URL
new_ngrok_url = os.getenv("NGROK_URL")

if not new_ngrok_url:
    for port in [4040, 4041, 4042]:
        try:
            cmd = ["curl", "--noproxy", "*", "-s", f"http://127.0.0.1:{port}/api/tunnels"]
            res_text = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8")
            if res_text:
                data = json.loads(res_text)
                tunnels = data.get("tunnels", [])
                if tunnels:
                    new_ngrok_url = tunnels[0]["public_url"]
                    print(f"Detected active ngrok URL on port {port}: {new_ngrok_url}")
                    break
        except Exception as e:
            print(f"Port {port} check failed: {e}")
            continue

if not new_ngrok_url:
    print("Error: No active ngrok tunnels found on ports 4040, 4041, or 4042. Make sure ngrok is running.")
    exit(1)

# 3. Update the .env file with the new URLs
try:
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            env_content = f.read()

        # Replace all occurrences of any ngrok-free.app URL with the new URL
        updated_content = re.sub(
            r"https://[a-zA-Z0-9\-]+\.ngrok-free\.app",
            new_ngrok_url,
            env_content
        )
        with open(ENV_PATH, "w") as f:
            f.write(updated_content)
        print("Updated .env file references with new ngrok URL.")
except Exception as env_err:
    print(f"Warning: Could not write to .env file directly ({env_err}). Will attempt to continue syncing ElevenLabs webhooks.")

# 4. Sync ElevenLabs Webhook Tools
headers = {"xi-api-key": api_key}
print("\nFetching ElevenLabs Custom Webhook Tools...")
try:
    tools_res = httpx.get("https://api.elevenlabs.io/v1/convai/tools", headers=headers)
    if tools_res.status_code == 200:
        tools_data = tools_res.json()
        tools_list = tools_data if isinstance(tools_data, list) else tools_data.get("tools", [])
        
        for tool in tools_list:
            tool_id = tool.get("tool_id") or tool.get("id")
            name = tool.get("name") or tool.get("tool_config", {}).get("name")
            tool_config = tool.get("tool_config", {})
            
            if tool_config.get("type") == "webhook":
                api_schema = tool_config.get("api_schema", {})
                old_url = api_schema.get("url")
                if old_url and "ngrok-free.app" in old_url:
                    new_url = re.sub(
                        r"https://[a-zA-Z0-9\-]+\.ngrok-free\.app",
                        new_ngrok_url,
                        old_url
                    )
                    if new_url != old_url:
                        if not tool_id:
                            print(f"DEBUG: tool_id is None! Tool keys: {list(tool.keys())}")
                            if "tool_config" in tool:
                                print(f"DEBUG: tool_config keys: {list(tool['tool_config'].keys())}")
                        
                        print(f"Updating tool '{name}' ({tool_id}): {old_url} -> {new_url}")
                        
                        # Copy existing tool config and modify url
                        updated_config = json.loads(json.dumps(tool_config))
                        updated_config["api_schema"]["url"] = new_url
                        
                        # Update the tool
                        if tool_id:
                            patch_res = httpx.patch(
                                f"https://api.elevenlabs.io/v1/convai/tools/{tool_id}",
                                json={"tool_config": updated_config},
                                headers=headers
                            )
                            if patch_res.status_code == 200:
                                print(f"  Successfully updated tool '{name}'!")
                            else:
                                print(f"  Error updating tool '{name}': {patch_res.text}")
                        else:
                            print("  Skipping update because tool_id is missing.")
    else:
        print(f"Error fetching tools: {tools_res.status_code} - {tools_res.text}")
except Exception as e:
    print(f"Failed to sync tools: {e}")

# 5. Sync Workspace/Agent Webhooks
print("\nFetching ElevenLabs Workspace Webhooks...")
try:
    webhooks_res = httpx.get("https://api.elevenlabs.io/v1/workspace/webhooks", headers=headers)
    if webhooks_res.status_code == 200:
        webhooks_data = webhooks_res.json()
        webhooks_list = webhooks_data if isinstance(webhooks_data, list) else webhooks_data.get("webhooks", [])
        
        webhooks_to_delete = []
        webhook_target_url = f"{new_ngrok_url}/api/v1/telephony/webhook"
        
        for webhook in webhooks_list:
            webhook_id = webhook.get("webhook_id")
            name = webhook.get("name", "Unnamed")
            old_url = webhook.get("url") or webhook.get("webhook_url")
            if name == "post call record" or (old_url and "/api/v1/telephony/webhook" in old_url):
                if old_url != webhook_target_url:
                    print(f"Found old webhook to replace: '{name}' (ID: {webhook_id}, URL: {old_url})")
                    webhooks_to_delete.append(webhook_id)
        
        active_webhook_id = None
        # Check if we have an active, correct webhook already
        for webhook in webhooks_list:
            wh_id = webhook.get("webhook_id")
            wh_name = webhook.get("name", "Unnamed")
            wh_url = webhook.get("url") or webhook.get("webhook_url")
            wh_disabled = webhook.get("is_disabled", False)
            if (wh_name == "post call record" or (wh_url and "/api/v1/telephony/webhook" in wh_url)) and wh_url == webhook_target_url and not wh_disabled:
                active_webhook_id = wh_id
                print(f"Found active webhook matching current ngrok URL: {active_webhook_id}")
                break

        if not active_webhook_id:
            # Create a new workspace webhook
            print("Creating new workspace webhook pointing to the current ngrok URL...")
            create_payload = {
                "settings": {
                    "name": "post call record",
                    "webhookUrl": webhook_target_url,
                    "authType": "hmac"
                }
            }
            create_res = httpx.post("https://api.elevenlabs.io/v1/workspace/webhooks", json=create_payload, headers=headers)
            if create_res.status_code in [200, 201]:
                active_webhook_id = create_res.json().get("webhook_id")
                print(f"  Successfully created new webhook! ID: {active_webhook_id}")
            else:
                print(f"  Error creating webhook: {create_res.status_code} - {create_res.text}")

        if active_webhook_id:
            # Update global workspace ConvAI settings with the active webhook ID
            print(f"  Updating workspace ConvAI settings default webhook to {active_webhook_id}...")
            workspace_patch_payload = {
                "webhooks": {
                    "post_call_webhook_id": active_webhook_id,
                    "events": ["transcript"],
                    "transcript_format": "json",
                    "send_audio": False
                }
            }
            ws_patch_res = httpx.patch("https://api.elevenlabs.io/v1/convai/settings", json=workspace_patch_payload, headers=headers)
            if ws_patch_res.status_code == 200:
                print("  Successfully updated workspace default webhook!")
            else:
                print(f"  Error updating workspace settings: {ws_patch_res.status_code} - {ws_patch_res.text}")

            # Clear/update agent workspace overrides so it inherits or uses the correct settings
            print(f"  Assigning webhook {active_webhook_id} to Agent {agent_id} overrides...")
            agent_patch_payload = {
                "workspace_overrides": {
                    "webhooks": {
                        "post_call_webhook_id": active_webhook_id,
                        "events": ["transcript"],
                        "transcript_format": "json",
                        "send_audio": False
                    }
                }
            }
            patch_res = httpx.patch(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", json=agent_patch_payload, headers=headers)
            if patch_res.status_code == 200:
                print("  Successfully updated agent workspace overrides!")
            else:
                print(f"  Error updating agent overrides: {patch_res.status_code} - {patch_res.text}")

            # Clean up old/outdated/duplicate webhooks
            for old_id in webhooks_to_delete:
                if old_id != active_webhook_id:
                    print(f"  Deleting old webhook {old_id}...")
                    try:
                        httpx.delete(f"https://api.elevenlabs.io/v1/workspace/webhooks/{old_id}", headers=headers)
                    except Exception as e:
                        print(f"  Failed to delete old webhook {old_id}: {e}")
        else:
            print("Failed to ensure an active webhook is set.")
    else:
        print(f"Error fetching workspace webhooks: {webhooks_res.status_code} - {webhooks_res.text}")
except Exception as e:
    print(f"Failed to sync workspace webhooks: {e}")

# 6. Sync Agent-Specific Webhook Tools (inside the agent configuration itself)
print("\nFetching ElevenLabs Agent specific tools...")
try:
    agent_res = httpx.get(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", headers=headers)
    if agent_res.status_code == 200:
        agent_data = agent_res.json()
        conv_config = agent_data.get("conversation_config", {})
        agent_tools = conv_config.get("tools", [])
        
        tools_updated = False
        updated_agent_tools = []
        for tool in agent_tools:
            tool_copy = json.loads(json.dumps(tool))
            if tool_copy.get("type") == "webhook":
                api_schema = tool_copy.get("api_schema", {})
                old_url = api_schema.get("url")
                if old_url and "ngrok-free.app" in old_url:
                    new_url = re.sub(
                        r"https://[a-zA-Z0-9\-]+\.ngrok-free\.app",
                        new_ngrok_url,
                        old_url
                    )
                    if new_url != old_url:
                        print(f"Updating agent-level tool '{tool_copy.get('name')}': {old_url} -> {new_url}")
                        tool_copy["api_schema"]["url"] = new_url
                        tools_updated = True
            updated_agent_tools.append(tool_copy)
            
        if tools_updated:
            agent_patch_payload = {
                "conversation_config": {
                    "tools": updated_agent_tools
                }
            }
            patch_res = httpx.patch(f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}", json=agent_patch_payload, headers=headers)
            if patch_res.status_code == 200:
                print("  Successfully updated Agent-specific tools URL!")
            else:
                print(f"  Error updating Agent-specific tools: {patch_res.text}")
        else:
            print("  No Agent-specific tools required updating.")
    else:
        print(f"Error fetching agent data: {agent_res.status_code} - {agent_res.text}")
except Exception as e:
    print(f"Failed to sync agent-specific tools: {e}")

print("\nSync complete! Your active ngrok tunnels, .env file, and ElevenLabs integrations are updated.")
print("Remember to manually update your Twilio number voice webhook in the Twilio Console if you dial in via phone.")
