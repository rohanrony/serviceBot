import asyncio
import os
import sys

# Ensure serviceBot is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.api.portal import load_config, sync_prompt_to_elevenlabs

async def sync():
    config = load_config()
    system_prompt = config.get("system_prompt", "")
    print("Syncing single system prompt to ElevenLabs...")
    await sync_prompt_to_elevenlabs(system_prompt, config.get("first_message"))
    print("Sync complete!")

if __name__ == "__main__":
    asyncio.run(sync())
