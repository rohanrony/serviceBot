import os
for k, v in os.environ.items():
    if "proxy" in k.lower() or "http" in k.lower():
        print(f"{k}={v}")
