import asyncio
import os
import json
from dotenv import load_dotenv

# Load root .env file and override existing env vars
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

# Force the database URL to be voice_service.db for this test
os.environ["DATABASE_URL"] = "voice_service.db"

# Import our webhook handler
from serviceBot.api.telephony import post_call_webhook

# Simulate a post-call payload from ElevenLabs with possible None/null values
mock_payload = {
    "type": "post_call_transcription",
    "event_timestamp": 1781800000,
    "data": {
        "conversation_id": "conv_mock_test_999",
        "agent_id": "agent_2501ktmjf3pee2as55y9vx3gdpge",
        "analysis": {
            "summary": "Customer booked an appointment for AC repair on 2026-06-18 14:00:00."
        },
        "metadata": None,  # Test null safety explicitly!
        "transcript": [
            {
                "role": "user",
                "message": "I need to book an appointment for AC repair."
            },
            {
                "role": "agent",
                "message": "Sure, let's schedule that."
            }
        ]
    }
}

async def run_test():
    print("Running webhook direct integration test against voice_service.db...")
    try:
        res = await post_call_webhook(mock_payload)
        print("Webhook response:", res)
        
        # Verify from database
        import sqlite3
        conn = sqlite3.connect("voice_service.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM crm_notes WHERE call_id = 'conv_mock_test_999';")
        note = cursor.fetchone()
        if note:
            print("\nSuccess! CRM Note was created in the database:")
            print("  ID:", note["id"])
            print("  Call ID:", note["call_id"])
            print("  Summary:", note["summary"])
            print("  Transcript length:", len(note["transcript"]))
            
            # Clean up the test record
            cursor.execute("DELETE FROM crm_notes WHERE call_id = 'conv_mock_test_999';")
            conn.commit()
            print("Cleaned up mock test note from database.")
        else:
            print("\nError: CRM Note was not found in the database.")
            
        conn.close()
    except Exception as e:
        print(f"\nIntegration test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
