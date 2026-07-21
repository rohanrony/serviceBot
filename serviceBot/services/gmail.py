import os
import smtplib
import traceback
import time
import base64
import httpx
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from serviceBot.api.portal import load_config, save_config
from serviceBot.services.encryption import encrypt_key, decrypt_key
from serviceBot.db.connection import get_db_connection

def refresh_gmail_token() -> Optional[str]:
    """
    Exchanges the system's encrypted refresh token for a fresh access token using Google's OAuth API.
    Updates config.json with the new encrypted access token and expiry time.
    """
    config = load_config()
    encrypted_client_id = config.get("gmail_client_id", "")
    encrypted_client_secret = config.get("gmail_client_secret", "")
    encrypted_refresh_token = config.get("gmail_refresh_token", "")

    client_id = decrypt_key(encrypted_client_id)
    client_secret = decrypt_key(encrypted_client_secret)
    refresh_token = decrypt_key(encrypted_refresh_token)

    # Fallback to environment variables if not set in UI config
    if not client_id:
        client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID")
    if not client_secret:
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GMAIL_CLIENT_SECRET")

    if not client_id or not client_secret or not refresh_token:
        print("Gmail OAuth2 Error: Missing Client ID, Client Secret, or Refresh Token configurations.")
        return None

    try:
        url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        
        print("Requesting fresh Google OAuth2 access token...")
        response = httpx.post(url, data=payload, timeout=10.0)
        if response.status_code != 200:
            print(f"Failed to refresh Google token (HTTP {response.status_code}): {response.text}")
            return None
            
        data = response.json()
        new_access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        
        # Calculate secure expiry time (subtracting 60 seconds margin)
        expires_at = time.time() + expires_in - 60
        
        # Store encrypted
        config["gmail_access_token"] = encrypt_key(new_access_token)
        config["gmail_token_expires_at"] = expires_at
        save_config(config)
        
        print("Google OAuth2 access token refreshed successfully!")
        return new_access_token
    except Exception as e:
        print(f"Gmail OAuth2 Refresh Exception: {str(e)}")
        return None

def get_gmail_access_token() -> Optional[str]:
    """
    Retrieves the active system Gmail access token, auto-refreshing it if expired or missing.
    """
    config = load_config()
    encrypted_access_token = config.get("gmail_access_token", "")
    expires_at = config.get("gmail_token_expires_at", 0)

    # Check if existing token is valid
    if encrypted_access_token and expires_at > time.time():
        access_token = decrypt_key(encrypted_access_token)
        if access_token:
            return access_token
            
    # Token expired or missing, trigger refresh
    return refresh_gmail_token()

def send_gmail_api_email(sender: str, recipient: str, subject: str, html_body: str, plain_body: str = "") -> bool:
    """
    Sends a MIME email using Google's Gmail REST API endpoint with OAuth2 authentication.
    """
    access_token = get_gmail_access_token()
    if not access_token:
        raise Exception("No valid Google OAuth2 access token available. Please reconnect your account.")
        
    try:
        # Clean and format recipients list (supports comma-separated emails)
        recipients_list = [r.strip() for r in recipient.replace(';', ',').split(',') if r.strip()]
        recipient_str = ", ".join(recipients_list)

        # Construct MIME Message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"serviceBot Notification <{sender}>"
        msg['To'] = recipient_str

        if plain_body:
            msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # Base64url encode the raw message
        raw_bytes = msg.as_bytes()
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode('utf-8')

        # Send via Gmail API
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {"raw": raw_b64}
        
        print("Posting message to Gmail REST API...")
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        if response.status_code != 200:
            err_msg = f"Gmail REST API send failure (HTTP {response.status_code}): {response.text}"
            print(err_msg)
            raise Exception(err_msg)
            
        print("Gmail REST API email sent successfully!")
        return True
    except Exception as e:
        print(f"Gmail REST API Exception: {str(e)}")
        print(traceback.format_exc())
        raise e

def send_gmail_via_api(agent_id: int, recipient: str, subject: str, html_body: str, plain_body: str = "") -> bool:
    """
    Sends an email using the Gmail REST API for the connected agent.
    Returns True if successfully sent, False otherwise.
    """
    try:
        from serviceBot.services.google_calendar import get_user_google_credentials
        creds = get_user_google_credentials(agent_id)
        scopes = creds["granted_scopes"]
        if "https://www.googleapis.com/auth/gmail.send" not in scopes:
            print(f"Agent {agent_id} Gmail: Insufficient scope to send email. Granted: {scopes}")
            return False

        # Clean and format recipients list (supports comma-separated emails)
        recipients_list = [r.strip() for r in recipient.replace(';', ',').split(',') if r.strip()]
        recipient_str = ", ".join(recipients_list)

        # Construct MIME Message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"serviceBot Notification <{creds['email']}>"
        msg['To'] = recipient_str

        if plain_body:
            msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # Base64url encode the raw message
        raw_bytes = msg.as_bytes()
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode('utf-8')

        # Send via Gmail API
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {creds['access_token']}",
            "Content-Type": "application/json"
        }
        payload = {"raw": raw_b64}
        
        print(f"Posting message to Gmail REST API for agent {agent_id}...")
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        if response.status_code == 403:
            print(f"Agent {agent_id} Gmail forbidden (403): Workspace admin block or scope disabled.")
            return False
        elif response.status_code != 200:
            print(f"Gmail REST API send failure for agent {agent_id} (HTTP {response.status_code}): {response.text}")
            return False
            
        print("Gmail REST API email sent successfully!")
        return True
    except Exception as e:
        print(f"Gmail REST API Exception for agent {agent_id}: {str(e)}")
        print(traceback.format_exc())
        return False

def send_smtp_email(sender: str, encrypted_password: str, recipient: str, server: str, port: int, subject: str, html_body: str, plain_body: str = "") -> bool:
    """
    Sends an email using standard SMTP with STARTTLS. Decrypts the password securely before connecting.
    """
    if not sender or not encrypted_password or not recipient:
        print("Gmail SMTP Notification Error: Missing sender, password, or recipient configurations.")
        return False
        
    try:
        decrypted_password = decrypt_key(encrypted_password)
        if not decrypted_password:
            print("Gmail SMTP Notification Error: Failed to decrypt email password.")
            return False

        # Clean and format recipients list (supports comma-separated emails)
        recipients_list = [r.strip() for r in recipient.replace(';', ',').split(',') if r.strip()]
        recipient_str = ", ".join(recipients_list)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"serviceBot Notification <{sender}>"
        msg['To'] = recipient_str

        if plain_body:
            msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        print(f"Connecting to SMTP server {server}:{port}...")
        smtp = smtplib.SMTP(server, port, timeout=10)
        smtp.ehlo()
        
        if port == 587:
            smtp.starttls()
            smtp.ehlo()
            
        print("SMTP Connection established, authenticating...")
        smtp.login(sender, decrypted_password)
        
        print("Sending email...")
        smtp.sendmail(sender, recipients_list, msg.as_string())
        smtp.quit()
        print("SMTP email notification sent successfully!")
        return True
    except Exception as e:
        print(f"SMTP Email Send Failed: {str(e)}")
        print(traceback.format_exc())
        return False

def send_booking_notification(booking_type: str, details: dict, agent_email: Optional[str] = None) -> bool:
    """
    Constructs and sends a premium formatted HTML email for a booking event.
    Enforces direct Gmail REST API sending scoped to the connected agent's credentials first,
    falling back to SMTP or system-level configuration if disconnected.
    """
    config = load_config()
    if not config.get("gmail_enabled"):
        print("Gmail Notifications: disabled in settings.")
        return False

    sender = config.get("gmail_sender", "")
    recipient = agent_email or config.get("gmail_recipient", "")

    if not sender or not recipient:
        print("Gmail Notifications: configured incorrectly; missing sender or recipient address.")
        return False

    # Format booking type header/colors
    if booking_type == "appointment":
        color = "#10b981"  # Emerald Success
        type_title = "New Appointment Scheduled"
        time_label = "Appointment Date & Time"
    elif booking_type == "reschedule":
        color = "#3b82f6"  # Blue Info
        type_title = "Appointment Rescheduled"
        time_label = "New Date & Time"
    else:
        color = "#f59e0b"  # Amber Warning
        type_title = "New Callback Requested"
        time_label = "Preferred Callback Time"

    subject = f"[serviceBot] {type_title} - {details.get('customer_name', 'Unknown')}"

    # Build HTML email body
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background-color: #f3f4f6;
                color: #1f2937;
                margin: 0;
                padding: 20px;
            }}
            .card {{
                max-width: 600px;
                margin: 0 auto;
                background: #ffffff;
                border-radius: 12px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                border-top: 8px solid {color};
                overflow: hidden;
            }}
            .header {{
                padding: 24px;
                text-align: center;
                background-color: #fdfdfd;
                border-bottom: 1px solid #f3f4f6;
            }}
            .header h1 {{
                font-size: 20px;
                font-weight: 700;
                color: #111827;
                margin: 0;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .content {{
                padding: 24px;
            }}
            .table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 12px;
            }}
            .table th, .table td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #f3f4f6;
                font-size: 14px;
            }}
            .table th {{
                color: #6b7280;
                font-weight: 500;
                width: 35%;
            }}
            .table td {{
                color: #111827;
                font-weight: 600;
            }}
            .badge {{
                display: inline-block;
                padding: 4px 8px;
                border-radius: 9999px;
                font-size: 12px;
                font-weight: 600;
                background-color: rgba(94, 106, 210, 0.1);
                color: #5e6ad2;
            }}
            .footer {{
                padding: 16px;
                text-align: center;
                background-color: #f9fafb;
                font-size: 11px;
                color: #9ca3af;
                border-top: 1px solid #f3f4f6;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <h1>{type_title}</h1>
            </div>
            <div class="content">
                <table class="table">
                    <tr>
                        <th>Customer Name</th>
                        <td>{details.get('customer_name', 'N/A')}</td>
                    </tr>
                    <tr>
                        <th>Phone Number</th>
                        <td>{details.get('phone', 'N/A')}</td>
                    </tr>
                    <tr>
                        <th>Vehicle Details</th>
                        <td>{details.get('vehicle', 'N/A')}</td>
                    </tr>
                    <tr>
                        <th>Service Type</th>
                        <td><span class="badge">{details.get('service_type', 'N/A')}</span></td>
                    </tr>
                    <tr>
                        <th>{time_label}</th>
                        <td><strong style="color: {color};">{details.get('time', 'N/A')}</strong></td>
                    </tr>
                    {"<tr><th>Issue Description</th><td>" + details.get('issue') + "</td></tr>" if details.get('issue') else ""}
                </table>
            </div>
            <div class="footer">
                Sent automatically by Test serviceBot.
            </div>
        </div>
    </body>
    </html>
    """

    plain_body = f"""
    === {type_title} ===
    Customer: {details.get('customer_name', 'N/A')}
    Phone: {details.get('phone', 'N/A')}
    Vehicle: {details.get('vehicle', 'N/A')}
    Service Type: {details.get('service_type', 'N/A')}
    {time_label}: {details.get('time', 'N/A')}
    {"Issue: " + details.get('issue') if details.get('issue') else ""}
    """

    # 1. Attempt to resolve agent_id and send via agent's Gmail OAuth integration
    agent_id = None
    if agent_email:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT sa.id FROM staff_agents sa
                    LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                    WHERE sa.email = %s OR uga.email = %s;
                """, (agent_email, agent_email))
                row = cursor.fetchone()
                if row:
                    agent_id = row["id"]
        except Exception as e:
            print(f"Error looking up agent ID for email {agent_email}: {e}")

    if agent_id:
        success = send_gmail_via_api(
            agent_id=agent_id,
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body
        )
        if success:
            return True
        print(f"Failed or missing credentials to send via agent {agent_id} Google account. Falling back to system settings...")

    # 2. Fallback to system-level email sending
    auth_type = config.get("gmail_auth_type", "app_password")
    if auth_type == "oauth2":
        return send_gmail_api_email(
            sender=sender,
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body
        )
    else:
        encrypted_pw = config.get("gmail_password", "")
        server = config.get("gmail_smtp_server", "smtp.gmail.com")
        port = int(config.get("gmail_smtp_port", 587))
        return send_smtp_email(
            sender=sender,
            encrypted_password=encrypted_pw,
            recipient=recipient,
            server=server,
            port=port,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body
        )
