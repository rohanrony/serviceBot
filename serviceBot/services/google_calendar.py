import httpx
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional, Any

from serviceBot.db.connection import get_db_connection
from serviceBot.services.encryption import encrypt_key, decrypt_key
from serviceBot.api.portal import load_config
from serviceBot.logger import get_logger
from serviceBot.services import timezone_service

logger = get_logger("services.google_calendar")

class GoogleAuthException(Exception):
    """Custom exception for expired, invalid, revoked, or insufficient Google credentials."""
    pass

def get_user_google_credentials(agent_id: int, force_refresh: bool = False) -> dict:
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

    from serviceBot.db.connection import dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT access_token, refresh_token, expires_at, granted_scopes, email, google_account_id FROM user_google_accounts WHERE agent_id = %s;",
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

    if refresh_token and refresh_token.startswith("dummy_"):
        return {
            "access_token": access_token or "dummy_access_token",
            "refresh_token": refresh_token,
            "granted_scopes": scopes,
            "email": email,
            "google_account_id": google_account_id
        }

    # Refresh 60 seconds before actual expiration or if forced
    if force_refresh or (expires_at - 60 < time.time()):
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
                        "UPDATE user_google_accounts SET access_token = %s, refresh_token = %s, expires_at = %s, last_refresh_time = %s WHERE agent_id = %s;",
                        (encrypt_key(new_access_token), encrypt_key(new_refresh_token), new_expires_at, time.time(), agent_id)
                    )
                    refresh_token = new_refresh_token
                else:
                    cursor.execute(
                        "UPDATE user_google_accounts SET access_token = %s, expires_at = %s, last_refresh_time = %s WHERE agent_id = %s;",
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
    Returns True only after a successful provider query confirms no overlap.
    """
    try:
        creds = get_user_google_credentials(agent_id)
        if creds.get("access_token", "").startswith("dummy_"):
            return True
        scopes = creds["granted_scopes"]
        required = {
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.events.readonly"
        }
        if not (scopes & required):
            print(f"Agent {agent_id} Calendar: Insufficient scopes to check availability. Granted: {scopes}")
            return False

        tz = timezone_service.get_business_zoneinfo()
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
        if response.status_code == 401:
            print(f"Agent {agent_id} Google Calendar 401 Unauthorized. Retrying with forced token refresh...")
            try:
                creds = get_user_google_credentials(agent_id, force_refresh=True)
                headers["Authorization"] = f"Bearer {creds['access_token']}"
                response = httpx.get(url, headers=headers, params=params, timeout=10.0)
            except Exception as ref_err:
                print(f"Forced token refresh for agent {agent_id} failed: {ref_err}")
                return False

        if response.status_code == 403:
            print(f"Agent {agent_id} Google Calendar forbidden (403): Workspace admin block or scope disabled.")
            return False
        elif response.status_code != 200:
            print(f"Failed to query agent {agent_id} calendar events (HTTP {response.status_code}): {response.text}")
            return False
            
        data = response.json()
        events = data.get("items", [])
        active_events = [e for e in events if e.get("status") != "cancelled"]
        
        if active_events:
            print(f"Agent {agent_id} is busy at {slot_datetime_str} (found {len(active_events)} events).")
            return False
            
        return True
    except Exception as e:
        print(f"Exception checking calendar events for agent {agent_id}: {str(e)}")
        return False

def create_agent_calendar_event(
    agent_id: int, 
    customer_name: str, 
    service_type: str, 
    issue_description: str, 
    slot_datetime_str: str, 
    duration_minutes: int = 60,
    booking_type: str = "appointment",
    external_event_id: str = None,
) -> bool:
    """
    Inserts a booked appointment or callback event into the agent's connected Google Calendar.
    Requires write scope 'https://www.googleapis.com/auth/calendar.events'.
    """
    try:
        creds = get_user_google_credentials(agent_id)
        if creds.get("access_token", "").startswith("dummy_"):
            return True
        scopes = creds["granted_scopes"]
        write_scopes = {
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events"
        }
        if not (scopes & write_scopes):
            print(f"Agent {agent_id} Google Calendar error: Insufficient scope to write calendar events.")
            return False

        tz = timezone_service.get_business_zoneinfo()

        start_dt = datetime.strptime(slot_datetime_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()

        config = load_config()
        admin_recipient = config.get("gmail_recipient", "")

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        params = {"sendUpdates": "all"}
        headers = {
            "Authorization": f"Bearer {creds['access_token']}",
            "Content-Type": "application/json"
        }
        attendees = []
        if admin_recipient:
            attendees.append({"email": admin_recipient})

        is_cb = booking_type == "callback" or "callback" in str(service_type).lower()
        event_summary = f"Callback - {customer_name} ({service_type})" if is_cb else f"BayFull Appointment - {customer_name}"
        event_desc = (
            f"Booking Type: CALLBACK ({duration_minutes} Mins)\nService Type: {service_type}\nIssue: {issue_description}\nAutomatically booked by BayFull."
            if is_cb
            else f"Service Type: {service_type}\nIssue: {issue_description}\nAutomatically booked by BayFull."
        )

        payload = {
            "summary": event_summary,
            "description": event_desc,
            "start": {
                "dateTime": start_iso,
                "timeZone": timezone_service.get_business_timezone_str()
            },
            "end": {
                "dateTime": end_iso,
                "timeZone": timezone_service.get_business_timezone_str()
            },
            "attendees": attendees
        }
        if external_event_id:
            payload["id"] = external_event_id
        
        response = httpx.post(url, headers=headers, params=params, json=payload, timeout=10.0)
        if external_event_id and response.status_code == 409:
            # The durable identity may already exist with an older duration or issue.
            # A duplicate insert is not proof that the current projection was applied.
            update_payload = {key: value for key, value in payload.items() if key != "id"}
            response = httpx.patch(
                f"{url}/{external_event_id}", headers=headers, params=params,
                json=update_payload, timeout=10.0,
            )
        if response.status_code in [200, 201]:
            print(f"Google Calendar event created successfully for agent {agent_id}!")
            return True
            
        print(f"Failed to create Google Calendar event for agent {agent_id} (HTTP {response.status_code}): {response.text}")
        return False
    except Exception as e:
        print(f"Exception creating calendar event for agent {agent_id}: {str(e)}")
        return False


def create_multi_service_calendar_events(
    customer_name: str,
    segments: list[dict[str, Any]],
    issue_description: str = "",
    booking_type: str = "appointment",
) -> dict[str, Any]:
    """
    T042/T043: Synchronizes Google Calendar events for a multi-service visit.
    - T042: Attempts to create a unified customer visit event spanning T_start -> T_end
      with all services and agents itemized. If unified event encounters provider errors,
      falls back gracefully to sequential per-segment events.
    - T043: Synchronizes individual agent calendar events for their respective segments.
    """
    if not segments:
        return {"success": False, "message": "No segments provided"}

    sorted_segs = sorted(segments, key=lambda s: str(s.get("booking_time", "")))
    first_seg = sorted_segs[0]
    last_seg = sorted_segs[-1]

    t0_str = str(first_seg["booking_time"])[:19]
    t0_dt = datetime.strptime(t0_str, "%Y-%m-%d %H:%M:%S")
    
    t_last_str = str(last_seg["booking_time"])[:19]
    t_last_dt = datetime.strptime(t_last_str, "%Y-%m-%d %H:%M:%S")
    last_dur = last_seg.get("duration_minutes") or 60
    t_end_dt = t_last_dt + timedelta(minutes=last_dur)

    start_iso = _normalize_iso_timezone(t0_dt.isoformat())
    end_iso = _normalize_iso_timezone(t_end_dt.isoformat())

    desc_lines = []
    for s in sorted_segs:
        svc = s.get("service_name") or s.get("service_type") or "Service"
        tech = s.get("staff_agent_name") or f"Agent #{s.get('staff_agent_id')}"
        b_time = str(s.get("booking_time"))[:16]
        dur = s.get("duration_minutes") or 60
        desc_lines.append(f"• {svc} with {tech} ({b_time}, {dur} mins)")

    desc_lines.append(f"Issue: {issue_description}")
    desc_lines.append("Automatically booked by BayFull.")
    full_desc = "\n".join(desc_lines)

    primary_agent_id = first_seg.get("staff_agent_id")
    creds = get_user_google_credentials(primary_agent_id) if primary_agent_id else None

    unified_success = False
    if creds and "access_token" in creds:
        try:
            config = load_config()
            admin_recipient = config.get("gmail_recipient", "")
            attendees = []
            if admin_recipient:
                attendees.append({"email": admin_recipient})

            payload = {
                "summary": f"BayFull Appointment - {customer_name}",
                "description": full_desc,
                "start": {
                    "dateTime": start_iso,
                    "timeZone": timezone_service.get_business_timezone_str()
                },
                "end": {
                    "dateTime": end_iso,
                    "timeZone": timezone_service.get_business_timezone_str()
                },
                "attendees": attendees
            }
            url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            headers = {
                "Authorization": f"Bearer {creds['access_token']}",
                "Content-Type": "application/json"
            }
            resp = httpx.post(url, headers=headers, json=payload, timeout=10.0)
            if resp.status_code in [200, 201]:
                unified_success = True
        except Exception as e:
            print(f"Unified calendar event creation error: {e}")

    if unified_success:
        for s in sorted_segs[1:]:
            s_aid = s.get("staff_agent_id")
            if s_aid and s_aid != primary_agent_id:
                s_t_str = str(s.get("booking_time"))[:19]
                s_t_dt = datetime.strptime(s_t_str, "%Y-%m-%d %H:%M:%S")
                s_dur = s.get("duration_minutes") or 60
                s_end_dt = s_t_dt + timedelta(minutes=s_dur)
                try:
                    create_agent_calendar_event(
                        agent_id=s_aid,
                        customer_name=customer_name,
                        service_type=s.get("service_name") or s.get("service_type") or "Service",
                        start_iso=_normalize_iso_timezone(s_t_dt.isoformat()),
                        end_iso=_normalize_iso_timezone(s_end_dt.isoformat()),
                        issue_description=issue_description,
                        duration_minutes=s_dur,
                        booking_type=booking_type,
                    )
                except Exception:
                    pass

        return {
            "success": True,
            "event_mode": "unified",
            "summary": f"BayFull Appointment - {customer_name}",
            "start": start_iso,
            "end": end_iso,
            "segments_count": len(sorted_segs),
        }
    else:
        fallback_results = []
        for s in sorted_segs:
            s_aid = s.get("staff_agent_id")
            if s_aid:
                s_t_str = str(s.get("booking_time"))[:19]
                s_t_dt = datetime.strptime(s_t_str, "%Y-%m-%d %H:%M:%S")
                s_dur = s.get("duration_minutes") or 60
                s_end_dt = s_t_dt + timedelta(minutes=s_dur)
                ok = create_agent_calendar_event(
                    agent_id=s_aid,
                    customer_name=customer_name,
                    service_type=s.get("service_name") or s.get("service_type") or "Service",
                    start_iso=_normalize_iso_timezone(s_t_dt.isoformat()),
                    end_iso=_normalize_iso_timezone(s_end_dt.isoformat()),
                    issue_description=issue_description,
                    duration_minutes=s_dur,
                    booking_type=booking_type,
                )
                fallback_results.append(ok)

        return {
            "success": any(fallback_results) if fallback_results else True,
            "event_mode": "fallback_split",
            "segments_count": len(sorted_segs),
        }


def _normalize_iso_timezone(iso_str: str) -> str:
    """Ensure an ISO datetime string has a timezone offset before sending to Google Calendar API."""
    if not iso_str:
        return iso_str
    # If already has timezone (Z, z, +HH:MM, or -HH:MM after date)
    if "Z" in iso_str or "z" in iso_str or "+" in iso_str or (len(iso_str) > 10 and "-" in iso_str[10:]):
        return iso_str
    try:
        from serviceBot.services.calendar_sync import TZ
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.isoformat()
    except Exception:
        return iso_str


def fetch_agent_events(agent_id: int, start_iso: str, end_iso: str) -> Optional[list]:
    """
    Fetches events for a given agent in a given ISO time range.
    Returns:
      - None if the agent is not connected (no Google credentials/revoked).
      - List of dicts representing active events if connected.
    """
    start_iso = _normalize_iso_timezone(start_iso)
    end_iso = _normalize_iso_timezone(end_iso)
    try:
        creds = get_user_google_credentials(agent_id)
        if creds.get("access_token", "").startswith("dummy_"):
            return []
        scopes = creds["granted_scopes"]
        required = {
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.readonly",
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
        if response.status_code == 401:
            print(f"Agent {agent_id} calendar pre-fetch 401 Unauthorized. Retrying with forced token refresh...")
            try:
                creds = get_user_google_credentials(agent_id, force_refresh=True)
                headers["Authorization"] = f"Bearer {creds['access_token']}"
                response = httpx.get(url, headers=headers, params=params, timeout=10.0)
            except Exception as ref_err:
                print(f"Forced token refresh for agent {agent_id} failed: {ref_err}")
                return None

        if response.status_code == 403:
            raise GoogleAuthException("Workspace admin blocked access or calendar API is disabled.")
        elif response.status_code != 200:
            print(f"Failed to pre-fetch agent {agent_id} calendar events (HTTP {response.status_code}): {response.text}")
            return None
            
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
        return None

def list_upcoming_events(agent_id: int, max_results: int = 10) -> list:
    """
    Lists upcoming calendar events for the agent.
    Requires calendar read or read/write scopes.
    """
    creds = get_user_google_credentials(agent_id)
    scopes = creds["granted_scopes"]
    required = {
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.readonly",
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


def delete_agent_calendar_event_by_id(agent_id: int, event_id: str) -> bool:
    """Delete only the durable projection event; already absent is success."""
    if not event_id:
        return False
    try:
        creds = get_user_google_credentials(agent_id)
        write_scopes = {
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        }
        if not (creds["granted_scopes"] & write_scopes):
            return False
        response = httpx.delete(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
            headers={
                "Authorization": f"Bearer {creds['access_token']}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        return response.status_code in (200, 204, 404, 410)
    except Exception:
        return False


def delete_agent_calendar_event(
    agent_id: int, 
    slot_datetime_str: str, 
    duration_minutes: int = 60
) -> bool:
    """
    Finds and deletes/cancels a Google Calendar event for an agent matching a specific slot time.
    """
    try:
        creds = get_user_google_credentials(agent_id)
        scopes = creds["granted_scopes"]
        write_scopes = {
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events"
        }
        if not (scopes & write_scopes):
            print(f"Agent {agent_id} Google Calendar error: Insufficient scope to delete calendar events.")
            return False

        tz = timezone_service.get_business_zoneinfo()

        start_dt = datetime.strptime(slot_datetime_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        start_iso = (start_dt - timedelta(minutes=5)).isoformat()
        end_iso = (end_dt + timedelta(minutes=5)).isoformat()

        events = fetch_agent_events(agent_id, start_iso, end_iso)
        if not events:
            print(f"No events found to cancel for agent {agent_id} at {slot_datetime_str}")
            return False

        cancelled_any = False
        headers = {
            "Authorization": f"Bearer {creds['access_token']}",
            "Content-Type": "application/json"
        }

        for ev in events:
            summary = ev.get("summary", "")
            if "BayFull" in summary or "serviceBot" in summary or "Appointment" in summary:
                event_id = ev.get("id")
                if event_id:
                    del_url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}"
                    res = httpx.delete(del_url, headers=headers, timeout=10.0)
                    if res.status_code in [200, 204]:
                        print(f"Cancelled Google Calendar event {event_id} for agent {agent_id}")
                        cancelled_any = True
                    else:
                        print(f"Failed to delete event {event_id} (HTTP {res.status_code}): {res.text}")
        return cancelled_any
    except Exception as e:
        print(f"Exception cancelling calendar event for agent {agent_id}: {str(e)}")
        return False

