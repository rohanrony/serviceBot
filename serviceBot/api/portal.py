import os
import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])

KB_DIR = "kb_documents"

class AgentUpdatePayload(BaseModel):
    voice_id: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None

@router.get("/elevenlabs/voices")
async def get_elevenlabs_voices():
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    headers = {}
    if api_key:
        headers["xi-api-key"] = api_key
        
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://api.elevenlabs.io/v1/voices", headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to fetch voices from ElevenLabs")
            return response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"HTTP request failed: {str(e)}")

@router.patch("/elevenlabs/agent")
async def update_elevenlabs_agent(payload: AgentUpdatePayload):
    import sys
    if not any(x in sys.modules for x in ["pytest", "unittest"]):
        load_dotenv(override=True)
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")
    
    if not agent_id:
        raise HTTPException(status_code=400, detail="ELEVENLABS_AGENT_ID is not configured in the environment")
        
    headers = {}
    if api_key:
        headers["xi-api-key"] = api_key
        
    # Construct ElevenLabs Conversational AI dynamic configuration update payload
    el_payload = {"conversation_config": {}}
    
    if payload.model:
        el_payload["conversation_config"]["agent"] = {
            "language_model_settings": {
                "model": payload.model
            }
        }
        
    if payload.voice_id:
        el_payload["conversation_config"]["tts"] = {
            "voice_id": payload.voice_id
        }

    if payload.prompt:
        if "agent" not in el_payload["conversation_config"]:
            el_payload["conversation_config"]["agent"] = {}
        el_payload["conversation_config"]["agent"]["prompt"] = {
            "prompt": payload.prompt
        }
        
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(
                f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
                json=el_payload,
                headers=headers
            )
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to update agent settings in ElevenLabs")
            return {"success": True, "data": response.json()}
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"HTTP request failed: {str(e)}")

class StaffAgentCreate(BaseModel):
    name: str
    role: Optional[str] = "Service Advisor"
    email: Optional[str] = None

class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price_range: Optional[str] = None
    duration_minutes: Optional[int] = None
    req_customer_name: Optional[bool] = True
    req_phone_number: Optional[bool] = True
    req_vehicle_details: Optional[bool] = True
    req_issue_description: Optional[bool] = True
    req_location: Optional[bool] = True

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "system_prompt.txt")

def load_config():
    import json
    defaults = {
        "handoff_phone_number": "+14242704893",
        "required_fields": {
            "customer_name": True,
            "phone_number": True,
            "vehicle_details": True,
            "issue_description": True,
            "location": True
        },
        "prompts": {
            "router": "You are Rachel, the voice assistant for Test. Start by introducing yourself. Your task is to understand the caller's intent and classify it:\n- 'new_customer_service_request': Caller wants to request service, reports a vehicle issue, or needs a courtesy inspection.\n- 'appointment_booking': Caller wants to schedule, book, or set up a service/repair appointment.\n- 'appointment_reschedule': Caller wants to change, reschedule, or cancel an existing appointment.\n- 'faq_business_knowledge': Caller has general questions about business hours (M-F 7am-6pm, closed weekends), location, warranty, shuttle service, or inspections.\n- 'human_handoff': Caller explicitly asks for a human agent, manager, or service advisor.\n- 'greeting': General greeting.\n- 'other': Any other queries.",
            "service_request": "You are a helpful service advisor intake assistant. Under our 'Nice Difference' policy, we gather details for a courtesy inspection and service request...",
            "appointment": "You are a scheduling assistant. Help the caller book or reschedule an appointment...",
            "faq": "You are a friendly customer service FAQ assistant for Test...",
            "handoff": "You are a human handoff assistant. Compile a clear summary of the conversation..."
        },
        "first_message": "Hello! Thank you for calling Test. I am Rachel, AI voice Assistant. How can I help you today?",
        "gmail_enabled": False,
        "gmail_sender": "",
        "gmail_password": "",
        "gmail_recipient": "",
        "gmail_smtp_server": "smtp.gmail.com",
        "gmail_smtp_port": 587,
        "gmail_auth_type": "app_password",
        "gmail_client_id": "",
        "gmail_client_secret": "",
        "gmail_access_token": "",
        "gmail_refresh_token": "",
        "gmail_token_expires_at": 0
    }
    if not os.path.exists(CONFIG_PATH):
        data = defaults.copy()
    else:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        # Merge defaults for any missing keys
        for k, v in defaults.items():
            if k not in data:
                data[k] = v

    # Also load system_prompt from system_prompt.txt
    system_prompt = ""
    if os.path.exists(SYSTEM_PROMPT_PATH):
        try:
            with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except Exception as e:
            print(f"Error loading system_prompt.txt: {e}")

    if not system_prompt:
        prompts = data.get("prompts", {})
        system_prompt = f"You are Rachel, an AI voice assistant for Test Automotive.\n\n### Core Router:\n{prompts.get('router', '')}\n\n### Service Request:\n{prompts.get('service_request', '')}\n\n### Appointment:\n{prompts.get('appointment', '')}\n\n### FAQ:\n{prompts.get('faq', '')}\n\n### Handoff:\n{prompts.get('handoff', '')}"
        
    data["system_prompt"] = system_prompt
    return data

def save_config(config_data):
    import json
    system_prompt = config_data.pop("system_prompt", None)
    if system_prompt is not None:
        try:
            with open(SYSTEM_PROMPT_PATH, "w", encoding="utf-8") as f:
                f.write(system_prompt)
        except Exception as e:
            print(f"Error saving system_prompt.txt: {e}")

    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=2)

def sync_services_to_kb():
    from serviceBot.db.connection import get_db_connection
    from serviceBot.services.rag import FAQService
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, description, price_range, duration_minutes FROM services")
        rows = cursor.fetchall()
        
    lines = ["# Auto Service Catalog and Offerings"]
    for row in rows:
        lines.append(f"## {row['name']}")
        lines.append(f"Description: {row['description'] or 'No description available'}")
        lines.append(f"Price Range: {row['price_range'] or 'TBD'}")
        lines.append(f"Duration: {row['duration_minutes'] or 'TBD'} minutes")
        lines.append("")
        
    catalog_text = "\n".join(lines)
    
    os.makedirs(KB_DIR, exist_ok=True)
    filename = "auto_services_catalog.txt"
    file_path = os.path.join(KB_DIR, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(catalog_text)
        
    service = FAQService()
    service.delete_file(filename)
    service.index_text(catalog_text, filename)

async def sync_prompt_to_elevenlabs(prompt_text: str, first_message: str = None):
    import sys
    if not any(x in sys.modules for x in ["pytest", "unittest"]):
        load_dotenv(override=True)
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")
    
    log_file = os.path.join(os.path.dirname(CONFIG_PATH), "elevenlabs_sync.log")
    
    try:
        with open(log_file, "a") as lf:
            lf.write(f"\n--- Sync Attempt ---\n")
            lf.write(f"Agent ID: {agent_id}\n")
            lf.write(f"API Key configured: {bool(api_key)}\n")
    except Exception:
        pass
        
    if not api_key or not agent_id:
        try:
            with open(log_file, "a") as lf:
                lf.write("Error: Missing API Key or Agent ID\n")
        except Exception:
            pass
        return
        
    headers = {"xi-api-key": api_key}
    el_payload = {
        "name": "Test Service Agent",
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": prompt_text
                }
            }
        }
    }
    if first_message:
        el_payload["conversation_config"]["agent"]["first_message"] = first_message
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(
                f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
                json=el_payload,
                headers=headers
            )
            try:
                with open(log_file, "a") as lf:
                    lf.write(f"Status Code: {response.status_code}\n")
                    lf.write(f"Response: {response.text}\n")
            except Exception:
                pass
            if response.status_code != 200:
                print(f"ElevenLabs prompt sync returned status code {response.status_code}: {response.text}")
        except Exception as e:
            try:
                with open(log_file, "a") as lf:
                    lf.write(f"Exception: {str(e)}\n")
            except Exception:
                pass
            print(f"Failed to sync prompt to ElevenLabs: {str(e)}")

class ConfigUpdatePayload(BaseModel):
    required_fields: dict
    prompts: Optional[dict] = None
    system_prompt: Optional[str] = None
    first_message: Optional[str] = None
    handoff_phone_number: Optional[str] = None

@router.get("/config")
async def get_config():
    return load_config()

@router.post("/config")
async def update_config(payload: ConfigUpdatePayload):
    config_data = {
        "handoff_phone_number": payload.handoff_phone_number or "+14242704893",
        "required_fields": payload.required_fields,
        "prompts": payload.prompts or {},
        "first_message": payload.first_message,
        "system_prompt": payload.system_prompt
    }
    save_config(config_data)
    
    prompt_to_sync = payload.system_prompt
    if not prompt_to_sync:
        prompts = payload.prompts or {}
        prompt_to_sync = f"""You are an advanced voice assistant for Test.

### Core Router instructions:
{prompts.get('router', '')}

### Service Request Intake instructions:
{prompts.get('service_request', '')}

### Appointment Booking instructions:
{prompts.get('appointment', '')}

### FAQ instructions:
{prompts.get('faq', '')}

### Handoff instructions:
{prompts.get('handoff', '')}

### Delay Prevention (Filler Messages Guidelines):
When you need to execute any tool or perform any database/server lookup (such as querying the knowledge base, checking availability, fetching required service fields, booking/rescheduling, or transferring a call), you MUST immediately say a quick, conversational, and natural filler response before calling the tool. Do NOT remain silent while the tool runs. Customize the response dynamically to the situation to avoid repetition:
- When checking server/FAQ: "Let me get that info for you...", "Please wait a moment while I check that for you...", "Checking our guidelines on that, one moment..."
- When checking calendar availability: "Let me check our schedule for you...", "Checking our calendar for open slots...", "Let's see what we have available on that date..."
- When retrieving appointment/customer record: "Let me pull up your booking details...", "Let me find your appointment record, just a moment..."
- When booking/saving a request: "Sure, let me get that booked for you...", "Perfect, saving those details now..."
- When transferring: "Let me get a service advisor on the line for you...", "Transferring you now, please hold a moment..."
Make sure the filler message sounds like a normal part of the conversation and is uttered right as you trigger the tool."""

    await sync_prompt_to_elevenlabs(prompt_to_sync, payload.first_message)
    
    return {"success": True}

@router.get("/services")
async def get_services():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Deduplicate existing services by name, keeping the one with the lowest ID
            cursor.execute("""
                DELETE FROM services 
                WHERE id NOT IN (
                    SELECT MIN(id) 
                    FROM services 
                    GROUP BY name
                )
            """)
            conn.commit()
            
            cursor.execute("SELECT COUNT(*) AS count FROM services")
            if cursor.fetchone()["count"] == 0:
                cursor.execute(
                    "INSERT INTO services (name, description, price_range, duration_minutes, req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location) VALUES (%s, %s, %s, %s, TRUE, TRUE, TRUE, TRUE, TRUE)",
                    ("Oil Change", "Full synthetic oil change, premium filter replacement, fluid top-off, and courtesy inspection", "$79-119", 45)
                )
                conn.commit()
                try:
                    sync_services_to_kb()
                except Exception:
                    pass
            
            cursor.execute("SELECT id, name, description, price_range, duration_minutes, req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location FROM services")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

@router.post("/services", status_code=201)
async def create_service(payload: ServiceCreate):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check if service with same name already exists
            cursor.execute("SELECT id FROM services WHERE name = %s", (payload.name,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="Service with this name already exists in the catalog")
                
            cursor.execute(
                "INSERT INTO services (name, description, price_range, duration_minutes, req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (payload.name, payload.description, payload.price_range, payload.duration_minutes,
                 bool(payload.req_customer_name), bool(payload.req_phone_number),
                 bool(payload.req_vehicle_details), bool(payload.req_issue_description),
                 bool(payload.req_location))
            )
            conn.commit()
            new_id = cursor.fetchone()["id"]
            try:
                sync_services_to_kb()
            except Exception:
                pass
            return {"id": new_id, "name": payload.name, "success": True}

@router.put("/services/{service_id}")
async def update_service(service_id: int, payload: ServiceCreate):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM services WHERE id = %s", (service_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Service not found")
            cursor.execute(
                "UPDATE services SET name = %s, description = %s, price_range = %s, duration_minutes = %s, req_customer_name = %s, req_phone_number = %s, req_vehicle_details = %s, req_issue_description = %s, req_location = %s WHERE id = %s",
                (payload.name, payload.description, payload.price_range, payload.duration_minutes,
                 bool(payload.req_customer_name), bool(payload.req_phone_number),
                 bool(payload.req_vehicle_details), bool(payload.req_issue_description),
                 bool(payload.req_location),
                 service_id)
            )
            conn.commit()
            try:
                sync_services_to_kb()
            except Exception:
                pass
            return {"id": service_id, "name": payload.name, "success": True}

@router.delete("/services/{service_id}")
async def delete_service(service_id: int):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM services WHERE id = %s", (service_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Service not found")
            cursor.execute("DELETE FROM services WHERE id = %s", (service_id,))
            conn.commit()
            try:
                sync_services_to_kb()
            except Exception:
                pass
            return {"id": service_id, "success": True}


class CalendarSlotCreate(BaseModel):
    slot_datetime: str
    is_booked: bool = False

class CalendarSlotUpdate(BaseModel):
    is_booked: Optional[bool] = None
    slot_datetime: Optional[str] = None

@router.get("/agents")
async def get_staff_agents():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sa.id, sa.name, sa.role, sa.email AS db_email, uga.email AS google_email
                FROM staff_agents sa
                LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id;
            """)
            rows = cursor.fetchall()
            agents = []
            for row in rows:
                d = {
                    "id": row["id"],
                    "name": row["name"],
                    "role": row["role"],
                    "email": row["google_email"] or row["db_email"],
                    "is_connected": bool(row["google_email"])
                }
                agents.append(d)
            return agents

@router.post("/agents", status_code=201)
async def create_staff_agent(payload: StaffAgentCreate):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO staff_agents (name, role, email) VALUES (%s, %s, %s) RETURNING id;",
                (payload.name, payload.role, payload.email)
            )
            conn.commit()
            new_id = cursor.fetchone()["id"]
            return {"id": new_id, "name": payload.name, "success": True}

@router.delete("/agents/{agent_id}")
async def delete_staff_agent(agent_id: int):
    import traceback
    from serviceBot.db.connection import get_db_connection, dict_cursor
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                # Verify agent exists
                cursor.execute("SELECT id FROM staff_agents WHERE id = %s;", (agent_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Agent not found")
                    
                cursor.execute("DELETE FROM staff_agents WHERE id = %s;", (agent_id,))
                conn.commit()
        return {"success": True}
    except Exception as e:
        print(f"Error deleting staff agent {agent_id}: {e}")
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/agents/{agent_id}/google/auth-url")
async def get_agent_google_auth_url(agent_id: int, request: Request, action: str = "calendar"):
    if action not in ["calendar", "gmail"]:
        raise HTTPException(status_code=400, detail="Invalid action type.")
        
    from serviceBot.services.encryption import decrypt_key
    from serviceBot.db.connection import get_db_connection, dict_cursor
    import secrets
    
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents WHERE id = %s;", (agent_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Agent not found")
            
    config = load_config()
    client_id = decrypt_key(config.get("gmail_client_id", ""))
    if not client_id:
        client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=400, detail="Google Client ID is not configured. Please save it in Gmail Settings or set GOOGLE_CLIENT_ID in your .env file.")
        
    # Determine scopes
    if action == "gmail":
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("SELECT granted_scopes FROM user_google_accounts WHERE agent_id = %s;", (agent_id,))
                row = cursor.fetchone()
        existing_scopes = row["granted_scopes"] if row else ""
        scopes_set = {"openid", "email", "profile", "https://www.googleapis.com/auth/gmail.send"}
        if "https://www.googleapis.com/auth/calendar.events" in existing_scopes:
            scopes_set.add("https://www.googleapis.com/auth/calendar.events")
        scope = " ".join(scopes_set)
    else:
        scope = "openid email profile https://www.googleapis.com/auth/calendar.events"
        
    state = secrets.token_urlsafe(16)
    
    # Save state for CSRF protection
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("INSERT INTO oauth_states (state, agent_id, action_type) VALUES (%s, %s, %s);", (state, agent_id, action))
            conn.commit()
        
    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/v1/portal/gmail/oauth/callback"
    
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "response_type=code&"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"scope={scope}&"
        f"state={state}&"
        "access_type=offline&"
        "prompt=consent"
    )
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}

@router.get("/agents/{agent_id}/oauth-url")
async def get_agent_oauth_url(agent_id: int, request: Request):
    # Backward compatibility endpoint
    return await get_agent_google_auth_url(agent_id, request, action="calendar")

@router.get("/agents/{agent_id}/google/status")
async def get_agent_google_status(agent_id: int):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents WHERE id = %s;", (agent_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Agent not found")
                
            cursor.execute("SELECT email, granted_scopes FROM user_google_accounts WHERE agent_id = %s;", (agent_id,))
            row = cursor.fetchone()
        
    if not row:
        return {"is_connected": False, "email": None, "scopes": []}
        
    scopes = row["granted_scopes"].split() if row["granted_scopes"] else []
    return {
        "is_connected": True,
        "email": row["email"],
        "scopes": scopes
    }

@router.post("/agents/{agent_id}/google/disconnect")
async def disconnect_agent_google(agent_id: int):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents WHERE id = %s;", (agent_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Agent not found")
                
            cursor.execute("DELETE FROM user_google_accounts WHERE agent_id = %s;", (agent_id,))
            conn.commit()
    return {"success": True}

@router.post("/agents/{agent_id}/disconnect")
async def disconnect_agent_calendar(agent_id: int):
    # Backward compatibility endpoint
    return await disconnect_agent_google(agent_id)

@router.get("/agents/{agent_id}/calendar")
async def get_agent_calendar(agent_id: int):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Verify agent exists
            cursor.execute("SELECT id FROM staff_agents WHERE id = %s", (agent_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Agent not found")
            
            cursor.execute(
                "SELECT id, slot_datetime, is_booked, staff_agent_id FROM mock_calendar_slots "
                "WHERE staff_agent_id = %s ORDER BY slot_datetime ASC",
                (agent_id,)
            )
            rows = cursor.fetchall()
            # PostgreSQL returns datetime objects for slot_datetime, serialize to string for JSON API
            res = []
            for row in rows:
                r = dict(row)
                if not isinstance(r["slot_datetime"], str):
                    r["slot_datetime"] = r["slot_datetime"].strftime("%Y-%m-%d %H:%M:%S")
                res.append(r)
            return res

@router.post("/agents/{agent_id}/calendar", status_code=201)
async def create_agent_slot(agent_id: int, payload: CalendarSlotCreate):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Verify agent exists
            cursor.execute("SELECT id FROM staff_agents WHERE id = %s", (agent_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Agent not found")
            
            # Verify slot doesn't already exist for this agent
            cursor.execute(
                "SELECT id FROM mock_calendar_slots WHERE slot_datetime = CAST(%s AS TIMESTAMP) AND staff_agent_id = %s",
                (payload.slot_datetime, agent_id)
            )
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="Time slot already exists for this agent")
                
            cursor.execute(
                "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (%s, %s, %s) RETURNING id",
                (payload.slot_datetime, bool(payload.is_booked), agent_id)
            )
            conn.commit()
            new_id = cursor.fetchone()["id"]
            return {"id": new_id, "slot_datetime": payload.slot_datetime, "success": True}

@router.patch("/calendar/{slot_id}")
async def update_calendar_slot(slot_id: int, payload: CalendarSlotUpdate):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Verify slot exists
            cursor.execute("SELECT id, slot_datetime, is_booked, staff_agent_id FROM mock_calendar_slots WHERE id = %s", (slot_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Calendar slot not found")
            
            current_data = dict(row)
            new_datetime = payload.slot_datetime if payload.slot_datetime is not None else current_data["slot_datetime"]
            new_is_booked = bool(payload.is_booked if payload.is_booked is not None else current_data["is_booked"])
            
            # Update
            cursor.execute(
                "UPDATE mock_calendar_slots SET slot_datetime = %s, is_booked = %s WHERE id = %s",
                (new_datetime, new_is_booked, slot_id)
            )
            conn.commit()
            if not isinstance(new_datetime, str):
                new_datetime = new_datetime.strftime("%Y-%m-%d %H:%M:%S")
            return {"id": slot_id, "slot_datetime": new_datetime, "is_booked": new_is_booked, "success": True}

@router.delete("/calendar/{slot_id}")
async def delete_calendar_slot(slot_id: int):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM mock_calendar_slots WHERE id = %s", (slot_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Calendar slot not found")
                
            cursor.execute("DELETE FROM mock_calendar_slots WHERE id = %s", (slot_id,))
            conn.commit()
            return {"id": slot_id, "success": True}


class PopulateSlotsPayload(BaseModel):
    days: Optional[int] = 30
    hours: Optional[list] = None  # e.g. [9, 11, 14, 16] — defaults to business hours if None

@router.post("/agents/{agent_id}/calendar/populate")
async def populate_agent_slots(agent_id: int, payload: PopulateSlotsPayload = None):
    """
    Generates Mon–Fri business-hour availability slots for the next N days (default 30).
    For agents with Google Calendar connected, live free/busy data is checked and busy
    slots are automatically marked as booked so the voice bot won't offer them.
    Skips slots that were already booked by the system.
    """
    from serviceBot.db.connection import get_db_connection
    from serviceBot.services.calendar_sync import sync_agent_slots

    if payload is None:
        payload = PopulateSlotsPayload()

    days = max(1, min(payload.days or 30, 365))
    hours = payload.hours if payload.hours else None  # None → calendar_sync uses default [9,11,14,16]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM staff_agents WHERE id = ?", (agent_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

    try:
        result = sync_agent_slots(agent_id=agent_id, days=days, hours=hours)
        return {
            "success": True,
            "agent_id": agent_id,
            "slots_created": result["created"],
            "slots_blocked_by_calendar": result["blocked"],
            "total_candidates": result["total"],
            "free_estimate": result["free_estimate"],
            "message": (
                f"Created {result['created']} new slots. "
                f"{result['blocked']} marked busy from live Google Calendar. "
                f"~{result['free_estimate']} slots available for booking."
            ),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Slot sync failed: {str(exc)}")


@router.post("/calendar/sync-all")
async def sync_all_calendar_slots(days: int = 30):
    """
    Triggers an immediate live Google Calendar → DB sync for ALL connected agents.
    Useful as a manual "Refresh Now" action from the portal UI.
    """
    from serviceBot.services.calendar_sync import sync_all_connected_agents
    try:
        results = sync_all_connected_agents(days=days)
        total_new = sum(r.get("created", 0) for r in results.values() if isinstance(r, dict))
        return {
            "success": True,
            "agents_synced": list(results.keys()),
            "total_new_slots": total_new,
            "details": results,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(exc)}")


@router.get("/calls")
async def get_calls():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT cn.id, cn.call_id, c.name AS customer_name, c.phone, cn.summary, cn.transcript, cn.created_at,
                       STRING_AGG(CONCAT(v.year, ' ', v.make, ' ', v.model), ', ') AS vehicle
                FROM crm_notes cn
                JOIN customers c ON cn.customer_id = c.id
                LEFT JOIN vehicles v ON v.customer_id = c.id
                GROUP BY cn.id, c.name, c.phone, cn.call_id, cn.summary, cn.transcript, cn.created_at
                ORDER BY cn.created_at DESC
            """)
            rows = cursor.fetchall()
            res = []
            for row in rows:
                r = dict(row)
                if not isinstance(r["created_at"], str) and r["created_at"]:
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                res.append(r)
            return res

@router.get("/appointments")
async def get_appointments():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sr.id, sr.booking_time AS appointment_datetime, sr.service_type, sr.status, sr.created_at, c.name AS customer_name, c.phone,
                       v.make, v.model, v.year
                FROM service_requests sr
                LEFT JOIN customers c ON sr.customer_id = c.id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                WHERE sr.booking_type = 'appointment'
                ORDER BY sr.booking_time DESC
            """)
            rows = cursor.fetchall()
            res = []
            for row in rows:
                r = dict(row)
                if not isinstance(r["created_at"], str) and r["created_at"]:
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                res.append(r)
            return res

@router.get("/service-requests")
async def get_service_requests():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sr.id, sr.service_type, sr.issue_description, sr.status, sr.time_slot, sr.created_at,
                       sr.booking_type, sr.booking_time,
                       c.name AS customer_name, c.phone,
                       v.make, v.model, v.year
                FROM service_requests sr
                LEFT JOIN customers c ON sr.customer_id = c.id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                ORDER BY sr.updated_at DESC
            """)
            rows = cursor.fetchall()
            res = []
            for row in rows:
                r = dict(row)
                if not isinstance(r["created_at"], str) and r["created_at"]:
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                res.append(r)
            return res

@router.get("/callbacks")
async def get_callbacks():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sr.id, sr.status, sr.created_at, sr.booking_time AS preferred_time, c.name AS customer_name, c.phone, sr.service_type, sr.issue_description,
                       v.make, v.model, v.year
                FROM service_requests sr
                LEFT JOIN customers c ON sr.customer_id = c.id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                WHERE sr.booking_type = 'callback'
                ORDER BY sr.updated_at DESC
            """)
            rows = cursor.fetchall()
            res = []
            for row in rows:
                r = dict(row)
                if not isinstance(r["created_at"], str) and r["created_at"]:
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                res.append(r)
            return res

@router.get("/stats")
async def get_stats():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Total Calls
            cursor.execute("SELECT COUNT(*) AS count FROM crm_notes")
            total_calls = cursor.fetchone()["count"]
            
            # Booked Appointments
            cursor.execute("SELECT COUNT(*) AS count FROM service_requests WHERE booking_type = 'appointment'")
            total_appointments = cursor.fetchone()["count"]
            
            # Service Requests
            cursor.execute("SELECT COUNT(*) AS count FROM service_requests")
            total_requests = cursor.fetchone()["count"]
            
            # Open Slots
            cursor.execute("SELECT COUNT(*) AS count FROM mock_calendar_slots WHERE is_booked = FALSE")
            open_slots = cursor.fetchone()["count"]
            
            # Callbacks
            cursor.execute("SELECT COUNT(*) AS count FROM service_requests WHERE booking_type = 'callback'")
            total_callbacks = cursor.fetchone()["count"]
                
            return {
                "total_calls": total_calls,
                "total_appointments": total_appointments,
                "total_requests": total_requests,
                "open_slots": open_slots,
                "total_callbacks": total_callbacks
            }


@router.post("/kb/upload")
async def upload_kb_file(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        text = contents.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 encoded text files are supported in the MVP")
        
    os.makedirs(KB_DIR, exist_ok=True)
    file_path = os.path.join(KB_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(contents)
        
    from serviceBot.services.rag import FAQService
    service = FAQService()
    # Delete first to allow clean overwrite in ChromaDB
    service.delete_file(file.filename)
    chunk_count = service.index_text(text, file.filename)
    
    return {
        "file_id": f"kb_doc_{file.filename}",
        "filename": file.filename,
        "chunk_count": chunk_count,
        "success": True
    }

@router.get("/kb")
async def get_kb_files():
    os.makedirs(KB_DIR, exist_ok=True)
    files = []
    for filename in os.listdir(KB_DIR):
        file_path = os.path.join(KB_DIR, filename)
        if os.path.isfile(file_path):
            stat = os.stat(file_path)
            files.append({
                "filename": filename,
                "size_bytes": stat.st_size
            })
    return files

@router.get("/kb/download/{filename}")
async def download_kb_file(filename: str):
    from fastapi.responses import FileResponse
    file_path = os.path.join(KB_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type="application/octet-stream", filename=filename)

@router.get("/kb/view/{filename}")
async def view_kb_file(filename: str):
    file_path = os.path.join(KB_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"filename": filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")

@router.delete("/kb/{filename}")
async def delete_kb_file(filename: str):
    file_path = os.path.join(KB_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        os.remove(file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")
        
    from serviceBot.services.rag import FAQService
    service = FAQService()
    service.delete_file(filename)
    
    return {"filename": filename, "success": True}

class GmailConfigPayload(BaseModel):
    gmail_enabled: bool
    gmail_auth_type: str
    gmail_sender: str
    gmail_password: Optional[str] = None
    gmail_recipient: str
    gmail_smtp_server: Optional[str] = "smtp.gmail.com"
    gmail_smtp_port: Optional[int] = 587
    gmail_client_id: Optional[str] = None
    gmail_client_secret: Optional[str] = None

@router.get("/gmail-config")
async def get_gmail_config():
    config = load_config()
    from serviceBot.services.encryption import decrypt_key
    
    client_id_decrypted = decrypt_key(config.get("gmail_client_id", ""))
    if not client_id_decrypted:
        client_id_decrypted = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID") or ""
        
    has_client_secret = bool(config.get("gmail_client_secret")) or bool(os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GMAIL_CLIENT_SECRET"))
    has_password = bool(config.get("gmail_password"))
    is_connected = bool(config.get("gmail_refresh_token"))
    
    return {
        "gmail_enabled": config.get("gmail_enabled", False),
        "gmail_auth_type": config.get("gmail_auth_type", "app_password"),
        "gmail_sender": config.get("gmail_sender", ""),
        "gmail_recipient": config.get("gmail_recipient", ""),
        "gmail_smtp_server": config.get("gmail_smtp_server", "smtp.gmail.com"),
        "gmail_smtp_port": config.get("gmail_smtp_port", 587),
        "has_password": has_password,
        "gmail_client_id": client_id_decrypted,
        "has_client_secret": has_client_secret,
        "is_connected": is_connected
    }

@router.post("/gmail-config")
async def update_gmail_config(payload: GmailConfigPayload):
    from serviceBot.services.encryption import encrypt_key
    config = load_config()
    
    config["gmail_enabled"] = payload.gmail_enabled
    config["gmail_auth_type"] = payload.gmail_auth_type
    if payload.gmail_sender or payload.gmail_auth_type != "oauth2":
        config["gmail_sender"] = payload.gmail_sender
    config["gmail_recipient"] = payload.gmail_recipient
    config["gmail_smtp_server"] = payload.gmail_smtp_server or "smtp.gmail.com"
    config["gmail_smtp_port"] = payload.gmail_smtp_port or 587
    
    if payload.gmail_password and payload.gmail_password != "••••••••••••••••":
        config["gmail_password"] = encrypt_key(payload.gmail_password)
        
    if payload.gmail_client_id:
        config["gmail_client_id"] = encrypt_key(payload.gmail_client_id)
        
    if payload.gmail_client_secret and payload.gmail_client_secret != "••••••••••••••••":
        config["gmail_client_secret"] = encrypt_key(payload.gmail_client_secret)
        
    save_config(config)
    return {"success": True}

@router.get("/gmail/oauth/auth-url")
async def get_gmail_oauth_url(request: Request):
    from serviceBot.services.encryption import decrypt_key
    config = load_config()
    
    client_id = decrypt_key(config.get("gmail_client_id", ""))
    if not client_id:
        client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=400, detail="Google Client ID is not configured. Please save it in Gmail Settings or set GOOGLE_CLIENT_ID in your .env file.")
        
    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/v1/portal/gmail/oauth/callback"
    scope = "https://www.googleapis.com/auth/gmail.send"
    
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "response_type=code&"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"scope={scope}&"
        "access_type=offline&"
        "prompt=consent"
    )
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}

@router.get("/gmail/oauth/callback")
async def gmail_oauth_callback(request: Request, code: str = None, error: str = None, state: Optional[str] = None):
    from fastapi.responses import HTMLResponse
    import time
    
    if error:
        return HTMLResponse(content=f"""
        <html>
        <body style="font-family: sans-serif; background-color: #0c0d0e; color: #ef4444; padding: 50px; text-align: center;">
            <h2>Authentication Failed</h2>
            <p>{error}</p>
            <button onclick="window.close()" style="padding: 10px 20px; background: #5e6ad2; color: white; border: none; border-radius: 6px; cursor: pointer; margin-top: 20px;">Close Window</button>
        </body>
        </html>
        """)
        
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code is missing.")
        
    # Verify state for CSRF protection
    agent_id = None
    action_type = "calendar"
    
    if state:
        from serviceBot.db.connection import get_db_connection, dict_cursor
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                # Clean up states older than 15 minutes
                cursor.execute("DELETE FROM oauth_states WHERE created_at < NOW() - INTERVAL '15 minutes';")
                cursor.execute("SELECT agent_id, action_type FROM oauth_states WHERE state = %s;", (state,))
                state_row = cursor.fetchone()
                if state_row:
                    agent_id = state_row["agent_id"]
                    action_type = state_row["action_type"]
                    cursor.execute("DELETE FROM oauth_states WHERE state = %s;", (state,))
                    conn.commit()
                elif state.startswith("agent_"):
                    try:
                        agent_id = int(state.split("_")[1])
                        action_type = "calendar"
                    except ValueError:
                        pass
                else:
                    return HTMLResponse(content="""
                    <html>
                    <body style="font-family: sans-serif; background-color: #0c0d0e; color: #ef4444; padding: 50px; text-align: center;">
                        <h2>Authentication Failed</h2>
                        <p>Invalid or expired state parameter. Please request connection again.</p>
                        <button onclick="window.close()" style="padding: 10px 20px; background: #5e6ad2; color: white; border: none; border-radius: 6px; cursor: pointer; margin-top: 20px;">Close Window</button>
                    </body>
                    </html>
                    """)
        
    from serviceBot.services.encryption import decrypt_key, encrypt_key
    config = load_config()
    
    client_id = decrypt_key(config.get("gmail_client_id", ""))
    client_secret = decrypt_key(config.get("gmail_client_secret", ""))
    
    if not client_id:
        client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID")
    if not client_secret:
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GMAIL_CLIENT_SECRET")
        
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="OAuth credentials (ID/Secret) are missing in server config or .env file.")
        
    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/v1/portal/gmail/oauth/callback"
    
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    try:
        response = httpx.post(token_url, data=payload, timeout=10.0)
        if response.status_code != 200:
            return HTMLResponse(content=f"""
            <html>
            <body style="font-family: sans-serif; background-color: #0c0d0e; color: #ef4444; padding: 50px; text-align: center;">
                <h2>Token Exchange Failed</h2>
                <p>{response.text}</p>
                <button onclick="window.close()" style="padding: 10px 20px; background: #5e6ad2; color: white; border: none; border-radius: 6px; cursor: pointer; margin-top: 20px;">Close Window</button>
            </body>
            </html>
            """)
            
        data = response.json()
        access_token = data["access_token"]
        refresh_token = data.get("refresh_token")
        expires_in = int(data.get("expires_in", 3600))
        expires_at = time.time() + expires_in - 60
 
        if agent_id is not None:
            # Query user email and account info from Google
            userinfo_url = "https://openidconnect.googleapis.com/v1/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            res = httpx.get(userinfo_url, headers=headers, timeout=10.0)
            google_account_id = None
            email = None
            google_name = None
            if res.status_code == 200:
                u_data = res.json()
                google_account_id = u_data.get("sub")
                email = u_data.get("email")
                google_name = u_data.get("name")
 
            granted_scopes = data.get("scope", "")
 
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    # Update staff agent name and email dynamically to match connected Google account
                    if google_name:
                        cursor.execute("UPDATE staff_agents SET name = %s WHERE id = %s;", (google_name, agent_id))
                    if email:
                        cursor.execute("UPDATE staff_agents SET email = %s WHERE id = %s;", (email, agent_id))
                    
                    # Enforce refresh token preservation if missing in current response
                    cursor.execute("SELECT refresh_token FROM user_google_accounts WHERE agent_id = %s;", (agent_id,))
                    existing_row = cursor.fetchone()
                    
                    db_refresh_token = None
                    if refresh_token:
                        db_refresh_token = encrypt_key(refresh_token)
                    elif existing_row and existing_row["refresh_token"]:
                        db_refresh_token = existing_row["refresh_token"]
 
                    # UPSERT user_google_accounts
                    cursor.execute("""
                        INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes, last_refresh_time)
                        VALUES (%s, 'google', %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(agent_id) DO UPDATE SET
                            google_account_id = excluded.google_account_id,
                            email = excluded.email,
                            access_token = excluded.access_token,
                            refresh_token = COALESCE(excluded.refresh_token, user_google_accounts.refresh_token),
                            expires_at = excluded.expires_at,
                            granted_scopes = excluded.granted_scopes,
                            last_refresh_time = excluded.last_refresh_time;
                    """, (
                        agent_id,
                        google_account_id,
                        email,
                        encrypt_key(access_token),
                        db_refresh_token,
                        expires_at,
                        granted_scopes,
                        time.time()
                    ))
                    cursor.execute("SELECT name FROM staff_agents WHERE id = %s;", (agent_id,))
                    agent_row = cursor.fetchone()
                    agent_name = agent_row["name"] if agent_row else f"Agent {agent_id}"
                    conn.commit()


            message_type = "agent-auth-success" if action_type == "calendar" else "gmail-auth-success"
            title_text = "Calendar Connected!" if action_type == "calendar" else "Gmail Connected!"
            body_text = f"Google Calendar authorized successfully for <strong>{agent_name}</strong> ({email or 'N/A'}). You can close this window now." if action_type == "calendar" else f"Gmail sending integration authorized successfully for <strong>{agent_name}</strong> ({email or 'N/A'}). You can close this window now."

            return HTMLResponse(content=f"""
            <html>
            <body style="font-family: sans-serif; background-color: #0c0d0e; color: #f3f4f6; padding: 50px; text-align: center; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 80vh;">
                <div style="background-color: #121315; border: 1px solid rgba(255,255,255,0.06); padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border-top: 4px solid #10b981; max-width: 400px;">
                    <h2 style="color: #10b981; margin-bottom: 10px;">{title_text}</h2>
                    <p style="color: #8e939e; margin-bottom: 20px; font-size: 14px;">{body_text}</p>
                    <button onclick="window.close()" style="padding: 10px 24px; background: #5e6ad2; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 500; font-size: 13.5px;">Close Window</button>
                </div>
                <script>
                    try {{
                        if (window.opener) {{
                            window.opener.postMessage('{message_type}', '*');
                        }}
                    }} catch(e) {{}}
                    setTimeout(function() {{ window.close(); }}, 2000);
                </script>
            </body>
            </html>
            """)
            
        # Default behavior: system level configuration
        config["gmail_access_token"] = encrypt_key(access_token)
        config["gmail_token_expires_at"] = expires_at
        
        if refresh_token:
            config["gmail_refresh_token"] = encrypt_key(refresh_token)
            
        # Automatically fetch the authorized email address from Google OpenID API
        userinfo_url = "https://openidconnect.googleapis.com/v1/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            res = httpx.get(userinfo_url, headers=headers, timeout=10.0)
            if res.status_code == 200:
                u_data = res.json()
                email = u_data.get("email")
                if email:
                    config["gmail_sender"] = email
                    print(f"[gmail_oauth] Automatically set system Gmail sender to: {email}")
        except Exception as exc:
            print(f"[gmail_oauth] Failed to retrieve system Google account email: {exc}")
            
        save_config(config)
        
        return HTMLResponse(content="""
        <html>
        <body style="font-family: sans-serif; background-color: #0c0d0e; color: #f3f4f6; padding: 50px; text-align: center; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 80vh;">
            <div style="background-color: #121315; border: 1px solid rgba(255,255,255,0.06); padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border-top: 4px solid #10b981; max-width: 400px;">
                <h2 style="color: #10b981; margin-bottom: 10px;">Google Account Connected!</h2>
                <p style="color: #8e939e; margin-bottom: 20px; font-size: 14px;">Gmail integration authorized successfully. You can close this window now.</p>
                <button onclick="window.close()" style="padding: 10px 24px; background: #5e6ad2; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 500; font-size: 13.5px;">Close Window</button>
            </div>
            <script>
                try {
                    if (window.opener) {
                        window.opener.postMessage('gmail-auth-success', '*');
                    }
                } catch(e) {}
                setTimeout(function() { window.close(); }, 2000);
            </script>
        </body>
        </html>
        """)
    except Exception as e:
        return HTMLResponse(content=f"""
        <html>
        <body style="font-family: sans-serif; background-color: #0c0d0e; color: #ef4444; padding: 50px; text-align: center;">
            <h2>Exception Occurred</h2>
            <p>{str(e)}</p>
            <button onclick="window.close()" style="padding: 10px 20px; background: #5e6ad2; color: white; border: none; border-radius: 6px; cursor: pointer; margin-top: 20px;">Close Window</button>
        </body>
        </html>
        """)

@router.post("/gmail-config/test")
async def test_gmail_config(payload: GmailConfigPayload):
    from serviceBot.services.encryption import encrypt_key
    from serviceBot.services.gmail import send_smtp_email, send_gmail_api_email
    
    config = load_config()
    subject = "[serviceBot] Gmail Integration Test Email"
    html_body = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body { font-family: -apple-system, sans-serif; padding: 24px; background-color: #f3f4f6; color: #1f2937; }
            .card { background: #fff; padding: 24px; border-radius: 8px; border-top: 4px solid #5e6ad2; max-width: 500px; margin: 0 auto; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Connection Test Successful!</h2>
            <p>Your Gmail integration settings are configured correctly.</p>
        </div>
    </body>
    </html>
    """
    
    try:
        if payload.gmail_auth_type == "oauth2":
            if not config.get("gmail_refresh_token"):
                raise HTTPException(
                    status_code=400,
                    detail="Google Account is not connected. Please click 'Connect Gmail Account' first to authorize access."
                )
            success = send_gmail_api_email(
                sender=payload.gmail_sender,
                recipient=payload.gmail_recipient,
                subject=subject,
                html_body=html_body,
                plain_body="Gmail integration OAuth2 test email."
            )
        else:
            encrypted_password = config.get("gmail_password", "")
            if payload.gmail_password and payload.gmail_password != "••••••••••••••••":
                encrypted_password = encrypt_key(payload.gmail_password)
                
            if not encrypted_password:
                raise HTTPException(status_code=400, detail="SMTP App Password is required to run connection test.")
                
            success = send_smtp_email(
                sender=payload.gmail_sender,
                encrypted_password=encrypted_password,
                recipient=payload.gmail_recipient,
                server=payload.gmail_smtp_server or "smtp.gmail.com",
                port=payload.gmail_smtp_port or 587,
                subject=subject,
                html_body=html_body,
                plain_body="Gmail integration SMTP test email."
            )
            
        if not success:
            raise HTTPException(status_code=500, detail="Gmail connection test failed. Please verify configurations.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gmail connection test failed: {str(e)}")
        
    return {"success": True}


@router.post("/seed")
async def trigger_seeding():
    from serviceBot.seed_cba_services import main as seed_main
    try:
        seed_main()
        return {"success": True, "message": "Database seeded successfully via API"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seeding failed: {str(e)}")





