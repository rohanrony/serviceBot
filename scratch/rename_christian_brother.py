import os
import re
import json
import httpx
import asyncio
from dotenv import load_dotenv

# Path setups
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

CONFIG_PATH = os.path.join(BASE_DIR, "serviceBot", "config.json")

def replace_terms(text: str) -> str:
    if not text:
        return text
    # Pattern to match "Christian Brothers Automotive" / "Christian Brothers" / "Christian Brother" case-insensitively
    pattern = re.compile(r"Christian\s+Brothers?\s+Automotive|Christian\s+Brothers?|christian\s+brothers?\s+automotive|christian\s+brothers?", re.IGNORECASE)
    return pattern.sub("Test", text)

def update_file(filepath: str):
    if not os.path.exists(filepath):
        print(f"Skipping (not found): {filepath}")
        return
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    new_content = replace_terms(content)
    
    if content != new_content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated: {filepath}")
    else:
        print(f"No changes needed for: {filepath}")

async def sync_to_elevenlabs():
    # Load settings from config.json
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    prompts = config.get("prompts", {})
    first_message = config.get("first_message", "")
    
    combined_prompt = f"""You are an advanced voice assistant for Test.

### Core Router instructions:
{prompts.get('router', '')}

### Service Request Intake instructions:
{prompts.get('service_request', '')}

### Appointment Booking instructions:
{prompts.get('appointment', '')}

### FAQ instructions:
{prompts.get('faq', '')}

### Handoff instructions:
{prompts.get('handoff', '')}

### Delay Prevention (Filler Messages Guidelines):
When you need to execute any tool or perform any database/server lookup (such as querying the knowledge base, checking availability, fetching required service fields, booking/rescheduling, or transferring a call), you MUST immediately say a quick, conversational, and natural filler response before calling the tool. Do NOT remain silent while the tool runs. Customize the response dynamically to the situation to avoid repetition:
- When checking server/FAQ: "Let me get that info for you...", "Please wait a moment while I check that for you...", "Checking our guidelines on that, one moment..."
- When checking calendar availability: "Let me check our schedule for you...", "Checking our calendar for open slots...", "Let's see what we have available on that date..."
- When retrieving appointment/customer record: "Let me pull up your booking details...", "Let me find your appointment record, just a moment..."
- When booking/saving a request: "Sure, let me get that booked for you...", "Perfect, saving those details now..."
- When transferring: "Let me get a service advisor on the line for you...", "Transferring you now, please hold a moment..."
Make sure the filler message sounds like a normal part of the conversation and is uttered right as you trigger the tool."""

    api_key = os.getenv("ELEVENLABS_API_KEY")
    agent_id = os.getenv("ELEVENLABS_AGENT_ID")
    
    if not api_key or not agent_id:
        print("Error: Missing ElevenLabs API Key or Agent ID in env.")
        return
        
    print(f"Syncing to ElevenLabs Agent: {agent_id}")
    
    headers = {"xi-api-key": api_key}
    
    # We update the agent name to "Test Service Agent", prompt, and first_message
    payload = {
        "name": "Test Service Agent",
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": combined_prompt
                },
                "first_message": first_message
            }
        }
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.patch(
                f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
                json=payload,
                headers=headers
            )
            print(f"ElevenLabs status code: {r.status_code}")
            if r.status_code == 200:
                print("ElevenLabs Agent updated successfully!")
                print(r.json())
            else:
                print(f"Error updating ElevenLabs: {r.text}")
        except Exception as e:
            print(f"ElevenLabs request exception: {str(e)}")

def main():
    # Update local files
    files_to_update = [
        os.path.join(BASE_DIR, "serviceBot", "config.json"),
        os.path.join(BASE_DIR, "serviceBot", "api", "portal.py"),
        os.path.join(BASE_DIR, "serviceBot", "api", "telephony.py"),
        os.path.join(BASE_DIR, "serviceBot", "services", "gmail.py"),
        os.path.join(BASE_DIR, "serviceBot", "db", "seed.py"),
        os.path.join(BASE_DIR, "serviceBot", "static", "index.html"),
        os.path.join(BASE_DIR, "serviceBot", "static", "app.js"),
        os.path.join(BASE_DIR, "serviceBot", "seed_cba_services.py"),
        os.path.join(BASE_DIR, "serviceBot", "index_cba_faqs.py"),
        os.path.join(BASE_DIR, "tests", "test_portal_api.py"),
        os.path.join(BASE_DIR, "scratch", "sync_prompts_direct.py"),
        # KB documents
        os.path.join(BASE_DIR, "kb_documents", "cba_faq_warranty.txt"),
        os.path.join(BASE_DIR, "kb_documents", "cba_faq_shuttle_inspection.txt"),
        os.path.join(BASE_DIR, "kb_documents", "cba_faq_hours_locations.txt"),
        os.path.join(BASE_DIR, "kb_documents", "cba_faq_about_company.txt"),
    ]
    
    print("Renaming 'Christian Brother' / 'Christian Brothers' / 'Christian Brothers Automotive' to 'Test'...")
    for filepath in files_to_update:
        update_file(filepath)
        
    print("\nTriggering ElevenLabs sync...")
    asyncio.run(sync_to_elevenlabs())

if __name__ == "__main__":
    main()
