import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.api.portal import get_gmail_config
import asyncio

async def run():
    res = await get_gmail_config()
    print("CONFIG RESP:", res)

asyncio.run(run())
