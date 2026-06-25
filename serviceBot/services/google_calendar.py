import httpx
import time
import traceback
import zoneinfo
from datetime import datetime, timedelta
from typing import Optional

from serviceBot.db.connection import get_db_connection
from serviceBot.services.encryption import encrypt_key, decrypt_key
from serviceBot.api.portal import load_config

class GoogleAuthException(Exception):
    """Custom exception for expired, invalid, revoked, or insufficient Google credentials."""
    pass

def get_user_google_credentials(agent_id: int) -> dict:
    """
    Loads, checks, and automatically refreshes Google credentials for a staff agent from `user_google_accounts`.
    Returns a dictionary containing:
      - access_token: fresh valid access token
      - refresh_token: decrypted refresh token
      - granted_scopes: set of scopes currently granted
      - email: google account email
      - google_account_id: unique google sub ID
    Raises GoogleAuthException if credentials cannot be loaded, refreshed, or if authorization has been revoked.
    """
    import os
    config = load_config()
    client_id = decrypt_key(config.get("gmail_client_id", ""))
    client_secret = decrypt_key(config.get("gmail_client_secret", ""))
    
    # Fallback to environment variables if not set in UI config
    if not client_id:
        client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID")
    if not client_secret:
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GMAIL_CLIENT_SECRET")
        
    if not client_id or not client_secret:
        raise GoogleAuthException("Google App Client ID or Secret is not configured. Please save it in Gmail Settings or set GOOGLE_CLIENT_ID in your .env file.")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT access_token, refresh_token, expires_at, granted_scopes, email, google_account_id FROM user_google_accounts WHERE agent_id = ?;",
            (agent_id,)
        )
        row = cursor.fetchone()

    if not row or not row["access_token"]:
        raise GoogleAuthException(f"Google account is not connected for agent {agent_id}.")

    access_token = decrypt_key(row["access_token"])
    refresh_token = decrypt_key(row["refresh_token"]) if row["refresh_token"] else None
    expires_at = row["expires_at"] or 0
    email = row["email"]
    google_account_id = row["google_account_id"]
    granted_scopes_str = row["granted_scopes"] or ""
    scopes = set(granted_scopes_str.split())

    # Refresh 60 seconds before actual expiration
    if expires_at - 60 < time.time():
        if not refresh_token:
            raise GoogleAuthException("Google access token is expired and refresh token is missing. Please reconnect.")

        try:
            url = "https://oauth2.googleapis.com/token"
            payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }
            print(f"Refreshing Google access token for agent {agent_id}...")
            response = httpx.post(url, data=payload, timeout=10.0)
            if response.status_code != 200:
                # Common errors: invalid_grant (revoked refresh token)
                try:
                    err_data = response.json()
                    err_desc = err_data.get("error_description", response.text)
                except Exception:
                    err_desc = response.text
                raise GoogleAuthException(f"Failed to refresh Google token (HTTP {response.status_code}): {err_desc}")

            data = response.json()
            new_access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
            new_expires_at = time.time() + expires_in
            new_refresh_token = data.get("refresh_token")

            # Preserves existing refresh token if a new one isn't returned
            with get_db_connection() as conn:
                cursor = conn.cursor()
                if new_refresh_token:
                    cursor.execute(
                        "UPDATE user_google_accounts SET access_token = ?, refresh_token = ?, expires_at = ?, last_refresh_time = ? WHERE agent_id = ?;",
                        (encrypt_key(new_access_token), encrypt_key(new_refresh_token), new_expires_at, time.time(), agent_id)
                    )
                    refresh_token = new_refresh_token
                else:
                    cursor.execute(
                        "UPDATE user_google_accounts SET access_token = ?, expires_at = ?, last_refresh_time = ? WHERE agent_id = ?;",
                        (encrypt_key(new_access_token), new_expires_at, time.time(), agent_id)
                    )
                conn.commit()

            access_token = new_access_token
            expires_at = new_expires_at
            print(f"Google access token for agent {agent_id} refreshed successfully.")
        except GoogleAuthException:
            raise
        except Exception as e:
            raise GoogleAuthException(f"Exception refreshing Google token: {str(e)}")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "granted_scopes": scopes,
        "email": email,
        "google_account_id": google_account_id
    }

def get_agent_google_access_token(agent_id: int) -> Optional[str]:
    """
    Exposes a legacy accessor method for compatibility.
    """
    try:
        creds = get_user_google_credentials(agent_id)
        return creds["access_token"]
    except Exception:
        return None

def is_agent_free(agent_id: int, slot_datetime_str: str, duration_minutes: int = 60) -> bool:
    """
    Queries the agent's Google Calendar to see if they have overlapping events at the given slot time.
    Returns True if free (or not connected to Google Calendar/insufficient scopes), False if busy.
    """
    try:
        creds = get_user_google_credentials(agent_id)
        scopes = creds["granted_scopes"]
        required = {
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.events.readonly"
        }
        if not (scopes & required):
            print(f"Agent {agent_id} Calendar: Insufficient scopes to check availability. Granted: {scopes}")
            return True

        tz = zoneinfo.ZoneInfo("America/New_York")
        start_dt = datetime.strptime(slot_datetime_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        headers = {
            "Authorization": f"Bearer {creds['access_token']}",
            "Content-Type": "application/json"
        }
        params = {
            "timeMin": start_iso,
            "timeMax": end_iso,
            "singleEvents": "true",
            "maxResults": 10
        }
        
        response = httpx.get(url, headers=headers, params=params, timeout=10.0)
        if response.status_code == 403:
            print(f"Agent {agent_id} Google Calendar forbidden (403): Workspace admin block or scope disabled.")
            return True
        elif response.status_code != 200:
            print(f"Failed to query agent {agent_id} calendar events (HTTP {response.status_code}): {response.text}")
            return True
            
        data = response.json()
        events = data.get("items", [])
        active_events = [e for e in events if e.get("status") != "cancelled"]
        
        if active_events:
            print(f"Agent {agent_id} is busy at {slot_datetime_str} (found {len(active_events)} events).")
            return False
            
        return True
    except Exception as e:
        print(f"Exception checking calendar events for agent {agent_id}: {str(e)}")
        return True

def create_agent_calendar_event(
    agent_id: int, 
    customer_name: str, 
    service_type: str, 
    issue_description: str, 
    slot_datetime_str: str, 
    duration_minutes: int = 60
) -> bool:
    """
    Inserts a booked appointment event into the agent's connected Google Calendar.
    Requires write scope 'https://www.googleapis.com/auth/calendar.events'.
    """
    try:
        creds = get_user_google_credentials(agent_id)
        scopes = creds["granted_scopes"]
        if "https://www.googleapis.com/auth/calendar.events" not in scopes:
            print(f"Agent {agent_id} Google Calendar error: Insufficient scope to write calendar events.")
            return False

        tz = zoneinfo.ZoneInfo("America/New_York")
        start_dt = datetime.strptime(slot_datetime_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        headers = {
            "Authorization": f"Bearer {creds['access_token']}",
            "Content-Type": "application/json"
        }
        payload = {
            "summary": f"serviceBot Appointment - {customer_name}",
            "description": f"Service Type: {service_type}\nIssue: {issue_description}\nAutomatically booked by serviceBot.",
            "start": {
                "dateTime": start_iso,
                "timeZone": "America/New_York"
            },
            "end": {
                "dateTime": end_iso,
                "timeZone": "America/New_York"
            }
        }
        
        response = httpx.post(url, headers=headers, json=payload, timeout=10.0)
        if response.status_code in [200, 201]:
            print(f"Google Calendar event created successfully for agent {agent_id}!")
            return True
            
        print(f"Failed to create Google Calendar event for agent {agent_id} (HTTP {response.status_code}): {response.text}")
        return False
    except Exception as e:
        print(f"Exception creating calendar event for agent {agent_id}: {str(e)}")
        return False

def fetch_agent_events(agent_id: int, start_iso: str, end_iso: str) -> Optional[list]:
    """
    Fetches events for a given agent in a given ISO time range.
    Returns:
      - None if the agent is not connected (no Google credentials/revoked).
      - List of dicts representing active events if connected.
    """
    try:
        creds = get_user_google_credentials(agent_id)
        scopes = creds["granted_scopes"]
        required = {
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.events.readonly"
        }
        if not (scopes & required):
            print(f"Agent {agent_id} Google Calendar: Insufficient scopes for pre-fetching.")
            return None

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        headers = {
            "Authorization": f"Bearer {creds['access_token']}",
            "Content-Type": "application/json"
        }
        params = {
            "timeMin": start_iso,
            "timeMax": end_iso,
            "singleEvents": "true",
            "maxResults": 100
        }
        
        print(f"Pre-fetching Google Calendar events for agent {agent_id} from {start_iso} to {end_iso}...")
        response = httpx.get(url, headers=headers, params=params, timeout=10.0)
        if response.status_code == 403:
            raise GoogleAuthException("Workspace admin blocked access or calendar API is disabled.")
        elif response.status_code != 200:
            print(f"Failed to pre-fetch agent {agent_id} calendar events (HTTP {response.status_code}): {response.text}")
            return []
            
        data = response.json()
        events = data.get("items", [])
        active_events = [e for e in events if e.get("status") != "cancelled"]
        return active_events
    except GoogleAuthException as e:
        print(f"Auth error pre-fetching calendar events for agent {agent_id}: {str(e)}")
        return None
    except Exception as e:
        print(f"Exception pre-fetching calendar events for agent {agent_id}: {str(e)}")
        print(traceback.format_exc())
        return []

def list_upcoming_events(agent_id: int, max_results: int = 10) -> list:
    """
    Lists upcoming calendar events for the agent.
    Requires calendar read or read/write scopes.
    """
    creds = get_user_google_credentials(agent_id)
    scopes = creds["granted_scopes"]
    required = {
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.events.readonly"
    }
    if not (scopes & required):
        raise GoogleAuthException("Insufficient scope for reading calendar events.")
        
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    headers = {
        "Authorization": f"Bearer {creds['access_token']}",
        "Content-Type": "application/json"
    }
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": datetime.utcnow().isoformat() + "Z",
        "maxResults": max_results
    }
    
    response = httpx.get(url, headers=headers, params=params, timeout=10.0)
    if response.status_code == 403:
        raise GoogleAuthException("Workspace admin blocked app/scopes or calendar access is forbidden.")
    elif response.status_code != 200:
        raise GoogleAuthException(f"Failed to fetch calendar events (HTTP {response.status_code}): {response.text}")
        
    return response.json().get("items", [])

def parse_google_datetime(dt_dict: dict, tz) -> Optional[datetime]:
    """
    Parses Google Calendar event start/end dictionary into a localized datetime object.
    Handles both dateTime (timestamp with timezone offset) and date (all-day event).
    """
    if not dt_dict:
        return None
    if "dateTime" in dt_dict:
        val = dt_dict["dateTime"]
        try:
            return datetime.fromisoformat(val).astimezone(tz)
        except Exception:
            # Fallback if there are formatting quirks
            cleaned = val.split(".")[0]
            if "+" in cleaned:
                cleaned = cleaned.split("+")[0]
            elif "-" in cleaned and cleaned.count("-") == 3:
                parts = cleaned.rsplit("-", 1)
                cleaned = parts[0]
            return datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tz)
    elif "date" in dt_dict:
        val = dt_dict["date"]
        return datetime.strptime(val, "%Y-%m-%d").replace(tzinfo=tz)
    return None
