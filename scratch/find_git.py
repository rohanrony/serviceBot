import os

path = "/Users/rohanroy/Coding/voiceService/.agents/.git"
exists = os.path.exists(path)
is_dir = os.path.isdir(path)
is_file = os.path.isfile(path)

print(f"Path: {path}")
print(f"Exists: {exists}")
print(f"IsDir: {is_dir}")
print(f"IsFile: {is_file}")
