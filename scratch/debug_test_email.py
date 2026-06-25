import sys
import os
import traceback

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.api.portal import load_config, test_gmail_config, GmailConfigPayload

# Create a payload mimicking the frontend test email payload
payload = GmailConfigPayload(
    gmail_enabled=False,
    gmail_auth_type="oauth2",
    gmail_sender="rohanrony@gmail.com",
    gmail_recipient="rohan.roy@edvenswainc.com",
    gmail_smtp_server="smtp.gmail.com",
    gmail_smtp_port=587,
    gmail_client_id="",
    gmail_client_secret=""
)

try:
    print("Testing gmail config via API test endpoint...")
    import asyncio
    
    async def run():
        res = await test_gmail_config(payload)
        print("Success:", res)
        
    asyncio.run(run())
except Exception as e:
    print("ERROR:")
    print(traceback.format_exc())
