import httpx

for port in [4040, 4041, 4042]:
    try:
        res = httpx.get(f"http://127.0.0.1:{port}/api/tunnels")
        print(f"Port {port} Status: {res.status_code}")
        print(f"Port {port} Text: {res.text[:200]}")
    except Exception as e:
        print(f"Port {port} Error: {e}")
