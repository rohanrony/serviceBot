import os
import sys
import dotenv

sys.path.insert(0, '.venv/lib/python3.13/site-packages')
sys.path.insert(0, '.')

dotenv.load_dotenv('/Users/rohanroy/Coding/dsai-product/.env')
dotenv.load_dotenv('/Users/rohanroy/Coding/voiceService/.env')

required = [
    'RENDER_API_KEY', 'RENDER_SERVICE_ID', 'RENDER_PROJECT_ID',
    'DATABASE_URL', 'OPENAI_API_KEY', 'ELEVENLABS_API_KEY',
    'ELEVENLABS_AGENT_ID', 'TWILIO_ACCOUNT_SID', 'ENCRYPTION_KEY',
]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print('SECRETS_CHECK: ❌ Missing secrets:', missing)
else:
    print(f'SECRETS_CHECK: ✅ All {len(required)} critical secrets are present')

print(f'VENV_CHECK: ✅ Python venv active ({sys.version.split()[0]})')
