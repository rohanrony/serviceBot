"""
Fix stuck ElevenLabs webhook (4f50acb506204427ae9cc3f68cc82769).

Steps:
1. Inspect all workspace webhooks and identify the stuck one.
2. Find which agents/phone numbers reference it.
3. Detach it from all agents (clear workspace_overrides.webhooks).
4. Delete the webhook via the API.
5. Create a new webhook and attach it to the agent.
"""

import os
import sys
import httpx
import json
from dotenv import load_dotenv

# Ensure local connection bypasses proxy
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

# Load root .env
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("ELEVENLABS_API_KEY")
agent_id = os.getenv("ELEVENLABS_AGENT_ID")

if not api_key:
    print("Error: Missing ELEVENLABS_API_KEY in .env")
    sys.exit(1)

headers = {"xi-api-key": api_key}
STUCK_WEBHOOK_ID = "4f50acb506204427ae9cc3f68cc82769"
BASE = "https://api.elevenlabs.io/v1"


def step(n, title):
    print(f"\n{'='*60}")
    print(f"  STEP {n}: {title}")
    print(f"{'='*60}")


# ── STEP 1: Inspect all workspace webhooks ──────────────────
step(1, "Inspect workspace webhooks")
webhooks = []
try:
    res = httpx.get(f"{BASE}/workspace/webhooks", headers=headers, trust_env=False)
    if res.status_code == 200:
        webhooks = res.json() if isinstance(res.json(), list) else res.json().get("webhooks", [])
        print(f"Found {len(webhooks)} workspace webhook(s):")
        for wh in webhooks:
            wh_id = wh.get("webhook_id") or wh.get("id")
            is_stuck = " ⚠️  <-- THIS IS THE STUCK ONE" if wh_id == STUCK_WEBHOOK_ID else ""
            print(f"  • {wh_id} → {wh.get('url', 'N/A')}{is_stuck}")
            print(f"    Events: {wh.get('events', 'N/A')}, Active: {wh.get('is_active', 'N/A')}")
    else:
        print(f"Failed to fetch webhooks: {res.status_code} - {res.text}")
except Exception as e:
    print(f"Error: {e}")

# ── STEP 2: Find agents referencing the stuck webhook ───────
step(2, "Find agents referencing the stuck webhook")
agents_using_stuck = []
try:
    res = httpx.get(f"{BASE}/convai/agents", headers=headers, trust_env=False)
    if res.status_code == 200:
        agents_data = res.json()
        agents = agents_data.get("agents", [])
        print(f"Found {len(agents)} agent(s). Checking each...")
        for agent in agents:
            aid = agent.get("agent_id")
            name = agent.get("name")
            detail_res = httpx.get(f"{BASE}/convai/agents/{aid}", headers=headers, trust_env=False)
            if detail_res.status_code == 200:
                detail = detail_res.json()
                overrides = detail.get("workspace_overrides") or {}
                wh_config = overrides.get("webhooks") or {}
                post_call_id = wh_config.get("post_call_webhook_id")
                if post_call_id == STUCK_WEBHOOK_ID:
                    print(f"  ⚠️  Agent '{name}' ({aid}) → uses STUCK webhook!")
                    agents_using_stuck.append(aid)
                elif post_call_id:
                    print(f"  ✓ Agent '{name}' ({aid}) → uses webhook {post_call_id}")
                else:
                    print(f"  - Agent '{name}' ({aid}) → no post_call webhook set")
    else:
        print(f"Failed: {res.text}")
except Exception as e:
    print(f"Error: {e}")

# ── STEP 3: Detach the stuck webhook from all agents ────────
step(3, "Detach stuck webhook from agents")
if agents_using_stuck:
    for aid in agents_using_stuck:
        print(f"  Clearing workspace_overrides.webhooks on agent {aid}...")
        # Set post_call_webhook_id to empty string / null to detach
        patch_payload = {
            "workspace_overrides": {
                "webhooks": {
                    "post_call_webhook_id": ""
                }
            }
        }
        try:
            res = httpx.patch(f"{BASE}/convai/agents/{aid}", json=patch_payload, headers=headers, trust_env=False)
            if res.status_code == 200:
                print(f"  ✓ Detached from agent {aid}")
            else:
                print(f"  ✗ Failed ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
else:
    print("  No agents are using the stuck webhook. Skipping.")

# ── STEP 4: Delete the stuck webhook via API ────────────────
step(4, f"Delete stuck webhook {STUCK_WEBHOOK_ID}")
try:
    res = httpx.delete(f"{BASE}/workspace/webhooks/{STUCK_WEBHOOK_ID}", headers=headers, trust_env=False)
    print(f"  Status: {res.status_code}")
    if res.status_code in (200, 204):
        print(f"  ✓ Webhook deleted successfully!")
    elif res.status_code == 404:
        print(f"  ℹ Webhook not found (already deleted or invalid ID)")
    elif res.status_code == 409:
        print(f"  ⚠️  Conflict — webhook is still attached somewhere.")
        print(f"  Response: {res.text}")
        print(f"  Try the force-detach approach below...")
    else:
        print(f"  ✗ Failed: {res.text}")
        # Try alternative endpoints
        print("  Trying alternative delete endpoint...")
        alt_res = httpx.delete(f"{BASE}/convai/webhooks/{STUCK_WEBHOOK_ID}", headers=headers, trust_env=False)
        print(f"  Alt status: {alt_res.status_code} - {alt_res.text}")
except Exception as e:
    print(f"  ✗ Error: {e}")

# ── STEP 5: Create a new webhook and attach to agent ────────
step(5, "Verify / create correct webhook and attach to agent")

# First check what webhooks remain
print("\n  Checking remaining webhooks...")
try:
    res = httpx.get(f"{BASE}/workspace/webhooks", headers=headers, trust_env=False)
    if res.status_code == 200:
        remaining = res.json() if isinstance(res.json(), list) else res.json().get("webhooks", [])
        print(f"  Remaining webhooks: {len(remaining)}")
        for wh in remaining:
            wh_id = wh.get("webhook_id") or wh.get("id")
            print(f"    • {wh_id} → {wh.get('url', 'N/A')}")
    else:
        print(f"  Could not list webhooks: {res.status_code}")
except Exception as e:
    print(f"  Error: {e}")

# Check what webhook the agent should use (from .env or deployed URL)
app_url = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("BASE_URL")
if app_url:
    webhook_url = f"{app_url}/api/webhook"
    print(f"\n  Your app webhook URL should be: {webhook_url}")
    print(f"  If no working webhook exists, create one pointing to this URL in the ElevenLabs dashboard.")
else:
    print("\n  ⚠ Could not determine your app URL from env. Check APP_URL / RENDER_EXTERNAL_URL.")

# If the agent has no webhook now, suggest the fix
if agent_id:
    print(f"\n  Checking current agent ({agent_id}) webhook state...")
    try:
        res = httpx.get(f"{BASE}/convai/agents/{agent_id}", headers=headers, trust_env=False)
        if res.status_code == 200:
            overrides = res.json().get("workspace_overrides") or {}
            wh_config = overrides.get("webhooks") or {}
            current = wh_config.get("post_call_webhook_id")
            if current and current != STUCK_WEBHOOK_ID:
                print(f"  ✓ Agent is using webhook: {current}")
            elif not current or current == "":
                print(f"  ⚠️  Agent has NO post-call webhook! Call history won't reach your app.")
                print(f"  → You need to create a new webhook in the ElevenLabs dashboard and attach it.")
                print(f"  → Or provide a webhook ID to attach:")
                print(f"     python scratch/patch_agent_workspace_overrides.py")
        else:
            print(f"  Failed to fetch agent: {res.status_code}")
    except Exception as e:
        print(f"  Error: {e}")

print(f"\n{'='*60}")
print("  DONE")
print(f"{'='*60}")
