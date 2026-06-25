import asyncio
import os
import sys

# Ensure serviceBot is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.api.portal import load_config, sync_prompt_to_elevenlabs

async def sync():
    config = load_config()
    prompts = config.get("prompts", {})
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
    print("Syncing prompts to ElevenLabs...")
    await sync_prompt_to_elevenlabs(combined_prompt, config.get("first_message"))
    print("Sync complete!")

if __name__ == "__main__":
    asyncio.run(sync())
