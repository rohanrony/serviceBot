import urllib.request
import json
import os

# Clear proxies to force direct connection to localhost
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

try:
    print("Fetching stats...")
    stats_data = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/portal/stats").read()
    print("STATS:", json.loads(stats_data))
    
    print("Fetching calls...")
    calls_data = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/portal/calls").read()
    print("CALLS count:", len(json.loads(calls_data)))
    
    print("Fetching service requests...")
    reqs_data = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/portal/service-requests").read()
    print("REQUESTS count:", len(json.loads(reqs_data)))
except Exception as e:
    print("Error:", e)
