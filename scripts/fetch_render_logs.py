#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

RENDER_API_KEY = os.getenv("RENDER_API_KEY")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID")
RENDER_PROJECT_ID = os.getenv("RENDER_PROJECT_ID")

if not RENDER_API_KEY:
    print("❌ Error: RENDER_API_KEY is not set in .env")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {RENDER_API_KEY}",
    "Accept": "application/json"
}

def make_request(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.reason}")
        err_body = e.read().decode('utf-8')
        print(err_body)
        return None
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return None

def main():
    print("🔍 Connecting to Render API...")
    print(f"ℹ️ Using Service ID: {RENDER_SERVICE_ID}")

    # Fetch Service Info
    service_info = make_request(f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}")
    if service_info:
        svc_data = service_info.get("service", {}) if "service" in service_info else service_info
        print(f"\n📌 Service Name: {svc_data.get('name')}")
        print(f"🌐 Service URL: {svc_data.get('url') or 'N/A'}")
        print(f"⚡ Type: {svc_data.get('type')} | Auto Deploy: {svc_data.get('autoDeploy')}")
        print(f"🟢 Status: {svc_data.get('suspended') == 'suspended' and 'SUSPENDED' or 'ACTIVE'}")

    # Fetch Recent Deploys
    print("\n🚀 Recent Deployments:")
    deploys = make_request(f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys?limit=5")
    if deploys:
        for d in deploys:
            deploy = d.get("deploy", {}) if "deploy" in d else d
            print(f"  • ID: {deploy.get('id')} | Status: {deploy.get('status')} | Trigger: {deploy.get('trigger')} | Created At: {deploy.get('createdAt')}")

    print("\n💡 Note: Live application runtime logs (stdout/stderr) are streamed directly in the Render Dashboard under the Logs tab.")


if __name__ == "__main__":
    main()

