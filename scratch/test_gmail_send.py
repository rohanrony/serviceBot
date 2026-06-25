import sys
import os
import traceback

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.services.gmail import send_gmail_api_email

try:
    print("Testing send_gmail_api_email...")
    success = send_gmail_api_email(
        sender="rohanrony@gmail.com",
        recipient="rohan.roy@edvenswainc.com",
        subject="scratch test",
        html_body="<b>scratch test body</b>",
        plain_body="scratch test body"
    )
    print("SUCCESS STATUS:", success)
except Exception as e:
    print("ERROR:")
    print(traceback.format_exc())
