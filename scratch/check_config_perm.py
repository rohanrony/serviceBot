import os

config_path = "/Users/rohanroy/Coding/voiceService/serviceBot/config.json"
exists = os.path.exists(config_path)
print("File exists:", exists)
if exists:
    print("Readable:", os.access(config_path, os.R_OK))
    print("Writable:", os.access(config_path, os.W_OK))
    try:
        with open(config_path, "r") as f:
            content = f.read()
        print("Read success, length:", len(content))
        with open(config_path, "w") as f:
            f.write(content)
        print("Write success!")
    except Exception as e:
        print("Error reading/writing:", str(e))
