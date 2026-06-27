import sys
from serviceBot.main import app

for key in sys.modules:
    if "telephony" in key:
        print("MODULE KEY:", key)
