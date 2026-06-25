import httpx
import json

# Ensure local connection bypasses proxy
import os
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

print("Fetching ngrok tunnel requests...")
for port in [4040, 4041, 4042]:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/requests/http?limit=20")
        if r.status_code == 200:
            data = r.json()
            requests = data.get("requests", [])
            print(f"\nRequests from ngrok on port {port} (found {len(requests)}):")
            for req in requests:
                print(f"- [{req.get('method')}] {req.get('path')} -> Status: {req.get('response', {}).get('status') or 'No Response'}")
            break
    except Exception as e:
        continue
