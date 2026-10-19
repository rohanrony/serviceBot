import os
import json
import tempfile
import httpx
import datetime as dt_mod
from datetime import datetime
from typing import Optional, List, Literal
from fastapi import APIRouter, HTTPException, UploadFile, File, Request, BackgroundTasks
from pydantic import Field, BaseModel, StrictBool, StrictStr, field_validator
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool

from serviceBot.services.calendar_availability import CalendarAvailabilityService, CalendarConflictError, CalendarError
from serviceBot.logger import get_logger

logger = get_logger("api.portal")

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
    from serviceBot.services.encryption import get_active_secret
    if not any(x in sys.modules for x in ["pytest", "unittest"]):
        load_dotenv(override=False)
    api_key = get_active_secret("elevenlabs_api_key")
    agent_id = get_active_secret("elevenlabs_agent_id")
    
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
            
            # Persist selected model to config.json if supplied
            if payload.model:
                try:
                    cfg = load_config()
                    cfg["agent_llm_model"] = payload.model
                    save_config(cfg)
                except Exception as save_err:
                    logger.warning(f"Could not persist agent_llm_model to config: {save_err}")

            return {"success": True, "data": response.json()}
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"HTTP request failed: {str(e)}")


class SecretsPayload(BaseModel):
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_agent_id: Optional[str] = None
    twilio_auth_token: Optional[str] = None


def mask_secret(value: str) -> str:
    if not value:
        return ""
    val = value.strip()
    if len(val) <= 8:
        return "••••••••"
    return f"{val[:4]}••••••••{val[-4:]}"


@router.get("/secrets")
async def get_system_secrets():
    """
    Returns masked secrets status and source ('env', 'custom', 'none').
    Decrypted plaintext keys are NEVER exposed in the response.
    """
    from serviceBot.services.encryption import decrypt_key
    
    cfg = load_config()
    system_secrets = cfg.get("system_secrets", {})
    
    keys_meta = {
        "openai": {"config_key": "openai_api_key", "env_vars": ["OPENAI_API_KEY"]},
        "gemini": {"config_key": "gemini_api_key", "env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]},
        "anthropic": {"config_key": "anthropic_api_key", "env_vars": ["ANTHROPIC_API_KEY"]},
        "elevenlabs_key": {"config_key": "elevenlabs_api_key", "env_vars": ["ELEVENLABS_API_KEY"]},
        "elevenlabs_agent": {"config_key": "elevenlabs_agent_id", "env_vars": ["ELEVENLABS_AGENT_ID"]},
        "twilio": {"config_key": "twilio_auth_token", "env_vars": ["TWILIO_AUTH_TOKEN"]}
    }
    
    result = {}
    for key_id, meta in keys_meta.items():
        c_val_enc = system_secrets.get(meta["config_key"])
        c_val = decrypt_key(c_val_enc).strip() if c_val_enc else ""
        
        env_val = ""
        for ev in meta["env_vars"]:
            v = os.getenv(ev, "").strip()
            if v:
                env_val = v
                break
                
        if c_val:
            result[key_id] = {
                "has_key": True,
                "source": "custom",
                "masked": mask_secret(c_val),
                # For non-secret agent ID, return value directly for editing ease
                "display_value": c_val if key_id == "elevenlabs_agent" else None
            }
        elif env_val:
            result[key_id] = {
                "has_key": True,
                "source": "env",
                "masked": mask_secret(env_val),
                "display_value": env_val if key_id == "elevenlabs_agent" else None
            }
        else:
            result[key_id] = {
                "has_key": False,
                "source": "none",
                "masked": "",
                "display_value": None
            }
            
    return result


@router.post("/secrets")
async def update_system_secrets(payload: SecretsPayload):
    """
    Encrypts and persists custom secret overrides in config.json.
    Passing empty string or clear command will remove the custom override,
    reverting back to default environment variables.
    """
    from serviceBot.services.encryption import encrypt_key
    
    cfg = load_config()
    if "system_secrets" not in cfg or not isinstance(cfg["system_secrets"], dict):
        cfg["system_secrets"] = {}
        
    fields = {
        "openai_api_key": payload.openai_api_key,
        "gemini_api_key": payload.gemini_api_key,
        "anthropic_api_key": payload.anthropic_api_key,
        "elevenlabs_api_key": payload.elevenlabs_api_key,
        "elevenlabs_agent_id": payload.elevenlabs_agent_id,
        "twilio_auth_token": payload.twilio_auth_token,
    }
    
    for k, val in fields.items():
        if val is None:
            continue
        cleaned = val.strip()
        if cleaned == "" or cleaned.lower() == "clear":
            # Remove custom override so it falls back to environment defaults
            cfg["system_secrets"].pop(k, None)
        elif not (cleaned.startswith("•") or "••••" in cleaned):
            # Only encrypt and store if it's an actual new key (not a dummy mask)
            cfg["system_secrets"][k] = encrypt_key(cleaned)
            
    save_config(cfg)
    return {"success": True, "message": "System secrets updated and encrypted at rest"}


class StaffAgentCreate(BaseModel):
    name: str
    role: Optional[str] = "Service Advisor"
    email: Optional[str] = None
    phone_number: Optional[str] = None


class StaffAgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None


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
    agent_ids: Optional[List[int]] = None

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "system_prompt.txt")

def load_config():
    import json
    default_system_prompt = """You are Rachel, an AI voice assistant for Davidson Car Care. Be polite, friendly, professional, and conversational. Speak clearly and concisely.

### 1. CORE INTENT & BEHAVIOR
Understand the caller's intent and assist them naturally across these areas:
- **Service Request / Courtesy Inspection Intake:** The caller reports a vehicle issue, asks for repair advice, or requests service.
- **Appointment Booking & Rescheduling:** The caller wants to schedule, book, reschedule, or cancel a service appointment.
- **FAQ & General Knowledge:** The caller has questions about business hours (Monday-Friday 7:00 AM - 6:00 PM, closed weekends), location, warranty, shuttle service, or specific service details.
<!-- [COMMENTED OUT - Service advisor handoff is not configured]
- **Human Handoff:** The caller explicitly requests to speak with a human agent, manager, or service advisor.
-->

### 2. MANDATORY INTAKE & SERVICE REQUESTS
Under our "Nice Difference" policy, before booking any appointment or arranging a callback, you MUST collect and confirm:
1. Customer's full name
2. Valid 10-digit phone number (verify it has 10 digits)
3. Vehicle details (Year, Make, and Model)
4. Description of the vehicle issue or requested service

If a specific service is requested (such as an oil change, brake inspection, or tire rotation), call `get_service_fields` first to verify any extra required details. Ask for missing details politely, one at a time.
- Multiple Issues: If a service request involves two or more different issues (e.g., oil change, AC repair, and brake repair), state the estimated rate and duration for EACH service to the caller. Then combine ALL issues and requested services together in a SINGLE tool call (`create_service_request` or `book_appointment`) for the confirmed slot. Do NOT call booking tools multiple times sequentially for the same slot.

Once all mandatory details are collected, ask:
"Would you like to book an appointment for this service now, or would you prefer to arrange a callback?"
- If they prefer a callback: Callback calls are made during business hours (Monday–Friday 7:00 AM – 6:00 PM ET). If the caller mentions a preferred day or time window (e.g. "tomorrow morning" or "around 2 PM"), confirm it and book directly without needing an availability check. Only call `check_availability` with `booking_type="callback"` if the caller explicitly asks when an advisor is free or asks for callback slot options. Confirm their preferred day and time window, then immediately call `create_service_request` with `booking_type="callback"` and `booking_time` set to their confirmed time. MANDATORY: Keep `issue_description` (or `issue`) concise and focused ONLY on the requested services or reported symptoms (e.g., "Windshield repair", "Oil change"). Do NOT repeat caller name, phone, vehicle details, or preferred time inside `issue_description`, as those are tracked in separate fields. NEVER verbally confirm a callback or end the call without executing the `create_service_request` tool call!
- If they want to book an appointment: Proceed to the Appointment Booking steps below.

### 3. APPOINTMENT BOOKING & RESCHEDULING
- **Checking Availability:** Always check open calendar slots first by calling `check_availability` with their preferred date and, when mentioned by the caller, their preferred time or time window (e.g., `preferred_date="2026-10-01"`, `preferred_time="9:00 AM"` or `"morning"`). Present 2 to 3 of the recommended options clearly. Note that these are highlighted recommendations centered around their request; additional slots are open across the day. NEVER tell or imply to the caller that the returned slots are the "only" available slots for the entire day. If the caller requests a different specific time, call `check_availability` with `preferred_time` set to their requested time. If no slots are available for that timeframe: Inform the customer politely (e.g., *"I apologize, but we don't have any open appointment slots for that specific time."*). If the customer asks for another specific time window or day (e.g. "What about afternoon?" or "What about Friday?"), call `check_availability` for their new request. If no slots work, smoothly transition to arranging an advisor callback. Do NOT loop autonomously through unrequested dates.
- **Business Hours Closing Boundary & Duration Constraints (MANDATORY):** Business hours are strictly Monday–Friday, 7:00 AM – 6:00 PM ET. All appointments must conclude strictly by 6:00 PM. Calculate Latest Start Time = 6:00 PM minus service duration (e.g., 60m -> 5:00 PM max; 90m -> 4:30 PM max; 120m -> 4:00 PM max). NEVER offer or accept any appointment extending past 6:00 PM. If a caller asks for a time that would run past 6:00 PM (e.g. 5:00 PM for 90m), immediately inform them that the shop closes at 6:00 PM, explain the latest start time is 4:30 PM, and offer 4:30 PM or an earlier slot.
- **Mandatory Price & Duration Quote Before Booking:** BEFORE calling `create_service_request` or `book_appointment` for an appointment, you MUST look up the service's estimated cost and time duration in our knowledge base (using `query_knowledge_base` if needed). Quote both clearly to the caller (for example: *"An oil change is typically $79 to $119 and takes about 45 minutes"*). Ask for their explicit confirmation to proceed at that rate. Only call the booking tool after they explicitly confirm. MANDATORY: Keep `issue_description` (or `issue`) concise and focused ONLY on the requested services or reported symptoms. Do NOT repeat caller name, phone, vehicle details, or appointment date/time in `issue_description`, as those are tracked in separate fields. Never leave the description generic or empty.
- **Rescheduling:** First call `get_customer_appointments` using their phone number to check current bookings. State their existing appointment time, then call `check_availability` for their preferred new date/time. Once confirmed, call `reschedule_appointment`.

### 4. FAQ & KNOWLEDGE BASE
When asked general questions about services, pricing, hours, or policies, call `query_knowledge_base`. Answer strictly using the context provided. Handle minor pronunciation differences or typos gracefully. Do not fabricate or hallucinate information not found in the knowledge base.

<!-- [COMMENTED OUT - Service advisor handoff is not configured]
### 5. HUMAN HANDOFF
If the caller asks to speak to a person or if their issue requires immediate human attention during business hours (M-F 7am-6pm), summarize their details (name, phone, vehicle, issue) and call the handoff tool (`handoff` / `cba_webbook`) to transfer the call to +14242704893.
-->
### 5. HUMAN HANDOFF & SERVICE ADVISOR INQUIRIES (TEMPORARILY UNAVAILABLE)
Live transfer to a service advisor or human representative is currently NOT configured. If the caller asks to speak with a human agent, manager, or service advisor, politely let them know that direct phone transfer is currently unavailable, and offer to schedule an in-shop appointment or arrange an advisor callback during business hours. Do not attempt to transfer or initiate live handoff.

### 6. CRITICAL DELAY PREVENTION (MANDATORY FILLER PHRASES)
Whenever you call any tool or perform a database/server lookup (`check_availability`, `create_service_request`, `book_appointment`, `query_knowledge_base`, `get_service_fields`, `request_callback`), you MUST immediately utter a quick, natural conversational filler phrase BEFORE triggering the tool call. Do NOT remain silent while checking the system. Vary your phrases dynamically:
- Checking calendar: *"Let me check our schedule for you..."*, *"Looking up open slots on the calendar..."*, *"Let's see what times we have available..."*
- Looking up info/FAQ: *"Let me look that up for you..."*, *"Checking our service catalog, just a moment..."*, *"Let me check our details on that..."*
- Booking/Saving: *"Getting that appointment booked for you now..."*, *"Saving those details for you, one moment..."*
<!-- [COMMENTED OUT - Service advisor handoff is not configured]
- Transferring: *"Connecting you with a service advisor now, please hold..."*
-->
Speak the filler naturally as part of the conversation so the caller experiences zero dead air.
**STRICT RULES FOR FILLERS:**
- NEVER repeat the same filler phrase back-to-back.
- NEVER enter an autonomous loop checking multiple dates without the caller asking. Call `check_availability` for the timeframe the caller requests. If the caller asks for a different time window (such as morning vs afternoon) or a different date, call `check_availability` for that updated request."""

    defaults = {
        "handoff_phone_number": "+14242704893",
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_hours": [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        "business_days": [0, 1, 2, 3, 4],
        "required_fields": {
            "customer_name": True,
            "phone_number": True,
            "vehicle_details": True,
            "issue_description": True,
            "location": True
        },
        "system_prompt": default_system_prompt,
        "first_message": "Hello! Thank you for calling Davidson Car Care. I am Rachel, AI voice Assistant. Please note that this conversation will be recorded. How can I help you today?",
        "gmail_enabled": False,
        "gmail_sender": "",
        "gmail_recipient": "",
        "enable_agent_selection": False,
        "gmail_auth_type": "oauth2",
        "gmail_client_id": "",
        "gmail_client_secret": "",
        "gmail_access_token": "",
        "gmail_refresh_token": "",
        "gmail_token_expires_at": 0,
        "min_booking_buffer_hours": 4,
        "min_callback_buffer_hours": 2.0,
        "initial_notification_enabled": True,
        "max_dispatch_retries": 3,
        "sla_advance_booking_hours": 4.0,
        "sla_medium_booking_hours": 3.0,
        "sla_short_booking_hours": 2.0,
        "final_reminder_hours": 2.0,
        "overnight_grace_minutes": 30,
        "auto_reassign_on_escalation": True,
        "reassignment_confirmation_window_minutes": 15,
        "supervisor_alert_phone": "+14242704893",
        "cutoff_window_hours": 2,
        "extended_cutoff_window_hours": 4,
        "morning_opening_grace_minutes": 60,
        "supervisor_escalation_sms": True,
        "supervisor_escalation_phone": "",
        "carrier_retry_backoff_minutes": [1, 5, 15],
        "business_name": "Davidson Car Care",
        "business_address": "123 Main St, Springfield, NC 27513",
        "google_maps_url": "https://maps.google.com/?q=Davidson+Car+Care+Springfield+NC",
        "business_timezone": "America/New_York"
    }
    if not os.path.exists(CONFIG_PATH):
        data = defaults.copy()
    else:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
        except Exception as e:
            print(f"Error loading {CONFIG_PATH}: {e}")
            data = defaults.copy()

    # Also check system_prompt.txt for overrides
    if os.path.exists(SYSTEM_PROMPT_PATH):
        try:
            with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data["system_prompt"] = content
        except Exception as e:
            print(f"Error loading system_prompt.txt: {e}")

    data["business_profile"] = get_business_profile(data)
    return data

def save_config(config_data):
    import json
    system_prompt = config_data.get("system_prompt")
    if system_prompt is not None:
        try:
            with open(SYSTEM_PROMPT_PATH, "w", encoding="utf-8") as f:
                f.write(system_prompt)
        except Exception as e:
            print(f"Error saving system_prompt.txt: {e}")

    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=2)

def sync_services_to_kb():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.services.rag import FAQService

    # The snapshot must be inside the same boundary as embedding/publication:
    # an older background job cannot publish a snapshot it took before waiting.
    with FAQService.operation_lock:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("SELECT name, description, price_range, duration_minutes FROM services")
                rows = cursor.fetchall()
        lines = ["# Auto Service Catalog and Offerings"]
        for row in rows:
            lines.extend([f"## {row['name']}",
                f"Description: {row['description'] or 'No description available'}",
                f"Price Range: {row['price_range'] or 'TBD'}",
                f"Duration: {row['duration_minutes'] or 'TBD'} minutes", ""])
        catalog_text = "\n".join(lines)
        os.makedirs(KB_DIR, exist_ok=True)
        filename = "auto_services_catalog.txt"
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=KB_DIR,
                    prefix=".auto-services-", suffix=".tmp", delete=False) as temporary:
                temporary_path = temporary.name
                temporary.write(catalog_text)
            FAQService().replace_text(catalog_text, filename)
            os.replace(temporary_path, os.path.join(KB_DIR, filename))
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

async def sync_prompt_to_elevenlabs(prompt_text: str, first_message: str = None):
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")

    if not api_key or not agent_id:
        return

    log_file = os.path.join(os.path.dirname(CONFIG_PATH), "elevenlabs_sync.log")
    
    try:
        with open(log_file, "a") as lf:
            lf.write(f"\n--- Sync Attempt ---\n")
            lf.write(f"Agent ID: {agent_id}\n")
            lf.write(f"API Key configured: {bool(api_key)}\n")
    except Exception:
        pass
        
    target_agents = [agent_id]
    prod_agent_id = os.getenv("ELEVENLABS_PRODUCTION_AGENT_ID")
    if prod_agent_id and prod_agent_id not in target_agents:
        target_agents.append(prod_agent_id)
        
    headers = {"xi-api-key": api_key}
    el_payload = {
        "name": f"{load_config().get('business_name') or 'Business'} Service Agent",
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
        for target_id in target_agents:
            try:
                response = await client.patch(
                    f"https://api.elevenlabs.io/v1/convai/agents/{target_id}",
                    json=el_payload,
                    headers=headers
                )
                try:
                    with open(log_file, "a") as lf:
                        lf.write(f"Target: {target_id} - Status Code: {response.status_code}\n")
                        lf.write(f"Response: {response.text}\n")
                except Exception:
                    pass
                if response.status_code != 200:
                    print(f"ElevenLabs prompt sync for {target_id} returned status code {response.status_code}: {response.text}")
            except Exception as e:
                try:
                    with open(log_file, "a") as lf:
                        lf.write(f"Target {target_id} Exception: {str(e)}\n")
                except Exception:
                    pass
                print(f"Failed to sync prompt to ElevenLabs agent {target_id}: {str(e)}")

from serviceBot.services.business_profile import (
    BusinessProfile, build_business_prompt, get_business_profile, normalize_portal_base_url, validate_intake_data,
)


class ConfigUpdatePayload(BaseModel):
    business_profile: Optional[BusinessProfile] = None
    regenerate_business_prompt: bool = False
    portal_base_url: Optional[str] = None

    @field_validator("portal_base_url")
    @classmethod
    def validate_portal_url(cls, value):
        return normalize_portal_base_url(value) if value is not None else None

    required_fields: Optional[dict] = None
    prompts: Optional[dict] = None
    system_prompt: Optional[str] = None
    first_message: Optional[str] = None
    handoff_phone_number: Optional[str] = None
    business_hours_start: Optional[int] = None
    business_hours_end: Optional[int] = None
    business_hours: Optional[list] = None
    business_days: Optional[list] = None
    min_booking_buffer_hours: Optional[int] = None
    min_callback_buffer_hours: Optional[float] = None
    initial_notification_enabled: Optional[bool] = None
    sla_advance_booking_hours: Optional[float] = None
    sla_medium_booking_hours: Optional[float] = None
    sla_short_booking_hours: Optional[float] = None
    final_reminder_hours: Optional[float] = None
    overnight_grace_minutes: Optional[int] = None
    max_dispatch_retries: Optional[int] = None
    supervisor_alert_phone: Optional[str] = None
    auto_reassign_on_escalation: Optional[bool] = None
    reassignment_confirmation_window_minutes: Optional[int] = None
    business_name: Optional[str] = None
    business_address: Optional[str] = None
    google_maps_url: Optional[str] = None
    business_timezone: Optional[str] = None

@router.get("/config")
async def get_config():
    return load_config()

@router.post("/config")
async def update_config(payload: ConfigUpdatePayload):
    existing = load_config()

    prompt_to_sync = payload.system_prompt
    if not prompt_to_sync and payload.prompts:
        p = payload.prompts
        prompt_to_sync = "\n\n".join([v for v in p.values() if isinstance(v, str) and v.strip()])

    if not prompt_to_sync:
        prompt_to_sync = existing.get("system_prompt", "")

    b_start = payload.business_hours_start if payload.business_hours_start is not None else existing.get("business_hours_start", 7)
    b_end = payload.business_hours_end if payload.business_hours_end is not None else existing.get("business_hours_end", 18)
    if payload.business_hours is not None:
        b_hours = [int(h) for h in payload.business_hours]
    elif payload.business_hours_start is not None or payload.business_hours_end is not None:
        b_hours = list(range(b_start, b_end))
    else:
        b_hours = existing.get("business_hours", list(range(7, 18)))

    b_days = [int(d) for d in payload.business_days] if payload.business_days is not None else existing.get("business_days", [0, 1, 2, 3, 4])
    req_fields = payload.required_fields if payload.required_fields is not None else existing.get("required_fields", {})

    config_data = existing.copy()
    config_data.update({
        "handoff_phone_number": payload.handoff_phone_number or existing.get("handoff_phone_number", "+14242704893"),
        "required_fields": req_fields,
        "first_message": payload.first_message if payload.first_message is not None else existing.get("first_message", ""),
        "system_prompt": prompt_to_sync,
        "business_hours_start": b_start,
        "business_hours_end": b_end,
        "business_hours": b_hours,
        "business_days": b_days
    })

    if payload.min_booking_buffer_hours is not None:
        config_data["min_booking_buffer_hours"] = int(payload.min_booking_buffer_hours)
    if payload.min_callback_buffer_hours is not None:
        config_data["min_callback_buffer_hours"] = float(payload.min_callback_buffer_hours)
    if payload.initial_notification_enabled is not None:
        config_data["initial_notification_enabled"] = bool(payload.initial_notification_enabled)
    if payload.sla_advance_booking_hours is not None:
        config_data["sla_advance_booking_hours"] = float(payload.sla_advance_booking_hours)
    if payload.sla_medium_booking_hours is not None:
        config_data["sla_medium_booking_hours"] = float(payload.sla_medium_booking_hours)
    if payload.sla_short_booking_hours is not None:
        config_data["sla_short_booking_hours"] = float(payload.sla_short_booking_hours)
    if payload.final_reminder_hours is not None:
        config_data["final_reminder_hours"] = float(payload.final_reminder_hours)
    if payload.overnight_grace_minutes is not None:
        config_data["overnight_grace_minutes"] = int(payload.overnight_grace_minutes)
    if payload.max_dispatch_retries is not None:
        config_data["max_dispatch_retries"] = int(payload.max_dispatch_retries)
    if payload.supervisor_alert_phone is not None:
        config_data["supervisor_alert_phone"] = str(payload.supervisor_alert_phone)
    if payload.auto_reassign_on_escalation is not None:
        config_data["auto_reassign_on_escalation"] = bool(payload.auto_reassign_on_escalation)
    if payload.reassignment_confirmation_window_minutes is not None:
        config_data["reassignment_confirmation_window_minutes"] = int(payload.reassignment_confirmation_window_minutes)
    if payload.business_name is not None:
        config_data["business_name"] = str(payload.business_name).strip()
    if payload.business_address is not None:
        config_data["business_address"] = str(payload.business_address).strip()
    if payload.google_maps_url is not None:
        config_data["google_maps_url"] = str(payload.google_maps_url).strip()
    if payload.business_timezone is not None:
        tz_str = str(payload.business_timezone).strip()
        from serviceBot.services.timezone_service import validate_timezone
        if not validate_timezone(tz_str):
            raise HTTPException(status_code=400, detail=f"Invalid IANA timezone identifier: {tz_str}")
        config_data["business_timezone"] = tz_str

    if payload.portal_base_url is not None:
        config_data["portal_base_url"] = payload.portal_base_url
    if payload.business_profile is not None:
        config_data["business_profile"] = payload.business_profile.model_dump()
    if payload.regenerate_business_prompt:
        prompt_to_sync, config_data["first_message"] = build_business_prompt(config_data)

    # Ensure prompt has synchronized lead time buffers
    appt_buf = float(config_data.get("min_booking_buffer_hours", 4.0))
    cb_buf = float(config_data.get("min_callback_buffer_hours", 2.0))
    from serviceBot.services.prompt_service import update_prompt_lead_time_buffers, update_prompt_business_hours
    prompt_to_sync = update_prompt_lead_time_buffers(prompt_to_sync, appt_buf, cb_buf)
    prompt_to_sync = update_prompt_business_hours(
        prompt_to_sync,
        start_hour=b_start,
        end_hour=b_end,
        business_days=b_days,
        timezone_str=config_data.get("business_timezone", "America/New_York")
    )
    config_data["system_prompt"] = prompt_to_sync

    save_config(config_data)
    
    await sync_prompt_to_elevenlabs(prompt_to_sync, config_data["first_message"] if payload.regenerate_business_prompt else payload.first_message)
    
    return {"success": True}

@router.get("/services")
async def get_services():
    """
    Retrieves all catalog services ordered by ID.
    Enriched with assigned staff agent IDs and names (assigned_agent_ids, assigned_agent_names).
    Services without tagged agents are open to any qualified staff agent.
    """
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, name, description, price_range, duration_minutes, req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location FROM services ORDER BY id ASC")
            rows = cursor.fetchall()

            # Fetch agent mappings
            service_agents_map = {}
            service_agent_names_map = {}
            try:
                cursor.execute("""
                    SELECT ssa.service_id, sa.id AS agent_id, sa.name AS agent_name
                    FROM service_staff_agents ssa
                    JOIN staff_agents sa ON ssa.staff_agent_id = sa.id
                    ORDER BY sa.name ASC;
                """)
                for m in cursor.fetchall():
                    sid = m["service_id"]
                    service_agents_map.setdefault(sid, []).append(m["agent_id"])
                    service_agent_names_map.setdefault(sid, []).append(m["agent_name"])
            except Exception as e:
                logger.warning(f"Error fetching service agent mappings: {e}")

            results = []
            for row in rows:
                d = dict(row)
                d["assigned_agent_ids"] = service_agents_map.get(d["id"], [])
                d["assigned_agent_names"] = service_agent_names_map.get(d["id"], [])
                results.append(d)
            return results

@router.post("/services/seed-defaults")
async def seed_default_services(background_tasks: BackgroundTasks):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.seed_cba_services import SERVICES_DATA
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            inserted_count = 0
            for svc in SERVICES_DATA:
                cursor.execute("""
                    INSERT INTO services (
                        name, description, price_range, duration_minutes, 
                        req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location
                    )
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM services WHERE LOWER(name) = LOWER(%s)
                    );
                """, (svc[0], svc[1], svc[2], svc[3], bool(svc[4]), bool(svc[5]), bool(svc[6]), bool(svc[7]), bool(svc[8]), svc[0]))
                if cursor.rowcount > 0:
                    inserted_count += 1
            conn.commit()
    background_tasks.add_task(sync_services_to_kb)
    return {"success": True, "inserted_count": inserted_count, "total_defaults": len(SERVICES_DATA)}

@router.post("/services", status_code=201)
async def create_service(payload: ServiceCreate, background_tasks: BackgroundTasks):
    """
    Creates a new catalog service item and optionally associates qualified staff agents
    via payload.agent_ids. If agent_ids is empty or null, the service remains open to all agents.
    """
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import set_service_agents
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
            new_id = cursor.fetchone()["id"]
            conn.commit()

    if payload.agent_ids is not None:
        try:
            set_service_agents(new_id, payload.agent_ids)
        except Exception as e:
            logger.warning(f"Error setting service agents: {e}")

    background_tasks.add_task(sync_services_to_kb)
    return {"id": new_id, "name": payload.name, "success": True}

@router.put("/services/{service_id}")
async def update_service(service_id: int, payload: ServiceCreate, background_tasks: BackgroundTasks):
    """
    Updates an existing catalog service item and synchronizes assigned staff agents
    via payload.agent_ids. Providing an empty list clears agent restrictions, making
    the service open to all active staff agents.
    """
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import set_service_agents
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

    if payload.agent_ids is not None:
        try:
            set_service_agents(service_id, payload.agent_ids)
        except Exception as e:
            logger.warning(f"Error updating service agents: {e}")

    background_tasks.add_task(sync_services_to_kb)
    return {"id": service_id, "name": payload.name, "success": True}

@router.delete("/services/{service_id}")
async def delete_service(service_id: int, background_tasks: BackgroundTasks):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM services WHERE id = %s", (service_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Service not found")
            cursor.execute("DELETE FROM services WHERE id = %s", (service_id,))
            conn.commit()
    background_tasks.add_task(sync_services_to_kb)
    return {"id": service_id, "success": True}


class CalendarSlotCreate(BaseModel):
    slot_datetime: str
    is_booked: bool = False

class CalendarSlotUpdate(BaseModel):
    is_booked: Optional[bool] = None
    slot_datetime: Optional[str] = None
class CalendarPopulatePayload(BaseModel):
    days: int = 30
    hours: Optional[list[int]] = None


def _calendar_http_error(exc: CalendarError) -> HTTPException:
    detail = str(exc)
    status_code = 404 if "was not found" in detail else 400
    if isinstance(exc, CalendarConflictError):
        status_code = 409
    return HTTPException(status_code=status_code, detail=detail)


@router.get("/agents/{agent_id}/calendar")
def get_agent_calendar_slots(agent_id: int):
    try:
        return CalendarAvailabilityService().list_slots(agent_id)
    except CalendarError as exc:
        raise _calendar_http_error(exc) from exc


@router.post("/agents/{agent_id}/calendar", status_code=201)
def create_agent_calendar_slot(agent_id: int, payload: CalendarSlotCreate):
    try:
        slot = CalendarAvailabilityService().create_slot(
            agent_id,
            payload.slot_datetime,
            payload.is_booked,
        )
        return {"success": True, **slot}
    except CalendarError as exc:
        raise _calendar_http_error(exc) from exc


@router.patch("/calendar/{slot_id}")
def update_calendar_slot(slot_id: int, payload: CalendarSlotUpdate):
    try:
        slot = CalendarAvailabilityService().update_slot(
            slot_id,
            is_booked=payload.is_booked,
            slot_datetime=payload.slot_datetime,
        )
        return {"success": True, **slot}
    except CalendarError as exc:
        raise _calendar_http_error(exc) from exc


@router.delete("/calendar/{slot_id}")
def delete_calendar_slot(slot_id: int):
    try:
        CalendarAvailabilityService().delete_slot(slot_id)
        return {"id": slot_id, "success": True}
    except CalendarError as exc:
        raise _calendar_http_error(exc) from exc


@router.post("/agents/{agent_id}/calendar/populate")
def populate_agent_calendar_slots(agent_id: int, payload: CalendarPopulatePayload):
    try:
        result = CalendarAvailabilityService().populate_agent(
            agent_id,
            days=payload.days,
            hours=payload.hours,
        )
        return {"success": True, **result}
    except CalendarError as exc:
        raise _calendar_http_error(exc) from exc


@router.post("/calendar/sync-all")
def sync_all_agent_calendars(days: int = 30):
    try:
        result = CalendarAvailabilityService().sync_all(days=days)
        return {"success": True, **result}
    except CalendarError as exc:
        raise _calendar_http_error(exc) from exc



@router.get("/agents")
async def get_staff_agents():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import is_agent_whatsapp_connected
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("""
                    SELECT sa.id, sa.name, sa.role, sa.email AS db_email, sa.phone_number, uga.email AS google_email
                    FROM staff_agents sa
                    LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                    WHERE sa.is_active IS NOT FALSE
                    ORDER BY sa.id ASC;
                """)
                rows = cursor.fetchall()
                config = load_config()
                system_email = config.get("gmail_sender") or os.getenv("GMAIL_SENDER") or None
                agents = []
                for row in rows:
                    resolved_email = row["google_email"] or row["db_email"] or system_email
                    d = {
                        "id": row["id"],
                        "name": row["name"],
                        "role": row["role"],
                        "email": resolved_email,
                        "phone_number": row["phone_number"],
                        "is_connected": bool(row["google_email"]),
                        "whatsapp_connected": is_agent_whatsapp_connected(row["phone_number"])
                    }
                    agents.append(d)
                return agents
    except Exception as e:
        logger.error(f"Error fetching staff agents: {e}")
        return []

@router.get("/agents/{agent_id}")
async def get_staff_agent(agent_id: int):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import is_agent_whatsapp_connected
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sa.id, sa.name, sa.role, sa.email AS db_email, sa.phone_number, uga.email AS google_email
                FROM staff_agents sa
                LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                WHERE sa.id = %s;
            """, (agent_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Agent not found")
            config = load_config()
            system_email = config.get("gmail_sender") or os.getenv("GMAIL_SENDER") or None
            resolved_email = row["google_email"] or row["db_email"] or system_email
            return {
                "id": row["id"],
                "name": row["name"],
                "role": row["role"],
                "email": resolved_email,
                "db_email": row["db_email"],
                "phone_number": row["phone_number"],
                "is_connected": bool(row["google_email"]),
                "whatsapp_connected": is_agent_whatsapp_connected(row["phone_number"])
            }

@router.put("/agents/{agent_id}")
@router.patch("/agents/{agent_id}")
async def update_staff_agent(agent_id: int, payload: StaffAgentUpdate):
    from serviceBot.db.connection import get_db_connection, dict_cursor

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, name, role, email, phone_number FROM staff_agents WHERE id = %s;", (agent_id,))
            agent = cursor.fetchone()
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")

            updates = []
            params = []
            if payload.name is not None:
                updates.append("name = %s")
                params.append(payload.name)
            if payload.role is not None:
                updates.append("role = %s")
                params.append(payload.role)
            if payload.email is not None:
                updates.append("email = %s")
                params.append(payload.email)
            if payload.phone_number is not None:
                updates.append("phone_number = %s")
                params.append(payload.phone_number)

            if updates:
                query = f"UPDATE staff_agents SET {', '.join(updates)} WHERE id = %s RETURNING id, name, role, email, phone_number;"
                params.append(agent_id)
                cursor.execute(query, tuple(params))
                updated_agent = dict(cursor.fetchone())

                # If email changed, update connected user_google_accounts if present
                if payload.email is not None:
                    cursor.execute("UPDATE user_google_accounts SET email = %s WHERE agent_id = %s;", (payload.email, agent_id))

                conn.commit()
            else:
                updated_agent = dict(agent)

    return {
        "success": True,
        "agent": updated_agent
    }

@router.post("/agents", status_code=201)
async def create_staff_agent(payload: StaffAgentCreate):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO staff_agents (name, role, email, phone_number) VALUES (%s, %s, %s, %s) RETURNING id;",
                (payload.name, payload.role, payload.email, payload.phone_number)
            )
            conn.commit()
            new_id = cursor.fetchone()["id"]
            return {"id": new_id, "name": payload.name, "phone_number": payload.phone_number, "success": True}


@router.delete("/agents/{agent_id}")
async def delete_staff_agent(agent_id: int):
    import traceback
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.services import timezone_service
    from serviceBot.db.queries import escalate_service_request
    from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                # 1. Verify agent exists
                cursor.execute("SELECT id, name, is_active FROM staff_agents WHERE id = %s;", (agent_id,))
                agent = cursor.fetchone()
                if not agent:
                    raise HTTPException(status_code=404, detail="Agent not found")

                agent_name = agent.get("name") or f"Agent #{agent_id}"

                # 2. Soft-delete the agent (mark inactive)
                cursor.execute("UPDATE staff_agents SET is_active = FALSE WHERE id = %s;", (agent_id,))

                # 3. Clean up active Google integrations, oauth states, and unbooked slots
                cursor.execute("DELETE FROM user_google_accounts WHERE agent_id = %s;", (agent_id,))
                cursor.execute("DELETE FROM oauth_states WHERE agent_id = %s;", (agent_id,))
                cursor.execute("DELETE FROM service_staff_agents WHERE staff_agent_id = %s;", (agent_id,))
                cursor.execute(
                    """
                    DELETE FROM mock_calendar_slots 
                    WHERE staff_agent_id = %s AND (is_booked = FALSE OR is_booked IS NULL);
                    """,
                    (agent_id,)
                )

                # 4. Find all upcoming active appointments for this agent
                now_business = timezone_service.now_in_business_tz().replace(tzinfo=None)
                cutoff_time = now_business - dt_mod.timedelta(minutes=15)

                cursor.execute(
                    """
                    SELECT sr.id, sr.status, sr.escalation_status, sr.booking_time, ar.starts_at
                    FROM service_requests sr
                    LEFT JOIN appointment_reservations ar ON ar.service_request_id = sr.id
                    WHERE sr.staff_agent_id = %s
                      AND sr.status NOT IN ('completed', 'done', 'cancelled', 'cancelled_by_customer')
                      AND (
                        (ar.starts_at IS NOT NULL AND ar.starts_at >= %s)
                        OR (ar.starts_at IS NULL AND (sr.status IN ('pending', 'in_progress', 'rescheduled') OR sr.booking_time >= %s::text))
                      );
                    """,
                    (agent_id, cutoff_time, cutoff_time)
                )
                upcoming_rows = cursor.fetchall()
                sr_ids_to_escalate = [r["id"] for r in upcoming_rows]
                conn.commit()

        # 5. Escalate each upcoming appointment so admin can reassign
        escalated_count = 0
        for sr_id in sr_ids_to_escalate:
            try:
                escalate_service_request(
                    request_id=sr_id,
                    reason="AGENT_DEACTIVATED",
                    triggered_by="admin_agent_deactivation",
                )
                escalated_count += 1
                try:
                    dispatch_supervisor_escalation_alert(
                        service_request_id=sr_id,
                        reason="AGENT_DEACTIVATED",
                    )
                except Exception as alert_err:
                    logger.warning(f"Failed to dispatch supervisor alert for escalated SR #{sr_id}: {alert_err}")
            except Exception as esc_err:
                logger.error(f"Failed to escalate SR #{sr_id} on agent deactivation: {esc_err}")

        return {
            "success": True,
            "message": f"Staff profile '{agent_name}' deactivated.",
            "agent_id": agent_id,
            "escalated_appointments_count": escalated_count,
            "escalated_service_request_ids": sr_ids_to_escalate,
        }
    except Exception as e:
        print(f"Error deleting/deactivating staff agent {agent_id}: {e}")
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


def _get_oauth_redirect_uri(request: Request) -> str:
    x_proto = request.headers.get("x-forwarded-proto", "")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = "https" if x_proto == "https" or (host and "onrender.com" in host) else request.url.scheme
    base = f"{scheme}://{host}".rstrip("/")
    return f"{base}/api/v1/portal/gmail/oauth/callback"


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
        
    redirect_uri = _get_oauth_redirect_uri(request)
    
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
    from serviceBot.db.queries import get_agent_whatsapp_status
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, email FROM staff_agents WHERE id = %s;", (agent_id,))
            sa_row = cursor.fetchone()
            if not sa_row:
                raise HTTPException(status_code=404, detail="Agent not found")
                
            cursor.execute("SELECT email, granted_scopes FROM user_google_accounts WHERE agent_id = %s;", (agent_id,))
            row = cursor.fetchone()
        
    config = load_config()
    system_email = config.get("gmail_sender") or os.getenv("GMAIL_SENDER") or None

    db_email = sa_row["email"] if sa_row else None
    wa_status = get_agent_whatsapp_status(agent_id)
    if not row:
        return {
            "is_connected": False,
            "is_expired": False,
            "email": db_email or system_email,
            "scopes": [],
            "whatsapp_connected": wa_status["is_connected"],
            "whatsapp_phone": wa_status["phone_number"],
            "has_phone": wa_status["has_phone"]
        }
        
    scopes = row["granted_scopes"].split() if row["granted_scopes"] else []
    
    is_expired = False
    try:
        from serviceBot.services.google_calendar import get_user_google_credentials, GoogleAuthException
        # Verify and refresh token if needed
        get_user_google_credentials(agent_id, force_refresh=False)
    except Exception as e:
        logger.warning(f"Google credentials for agent {agent_id} are expired or invalid: {e}")
        is_expired = True

    return {
        "is_connected": True,
        "is_expired": is_expired,
        "email": row["email"] or db_email or system_email,
        "scopes": scopes,
        "whatsapp_connected": wa_status["is_connected"],
        "whatsapp_phone": wa_status["phone_number"],
        "has_phone": wa_status["has_phone"]
    }

@router.get("/agents/{agent_id}/whatsapp/status")
async def get_agent_whatsapp_status_endpoint(agent_id: int):
    from serviceBot.db.queries import get_agent_whatsapp_status
    status = get_agent_whatsapp_status(agent_id)
    return {"success": True, **status}

@router.post("/agents/{agent_id}/whatsapp/disconnect")
async def disconnect_agent_whatsapp_endpoint(agent_id: int):
    from serviceBot.db.queries import disconnect_agent_whatsapp
    result = disconnect_agent_whatsapp(agent_id)
    return result

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




class ServiceRequestStatusUpdate(BaseModel):
    status: str


class AgentAssignPayload(BaseModel):
    staff_agent_id: Optional[int] = None

class CustomerDetails(BaseModel):
    name: str
    phone: str

class VehicleDetails(BaseModel):
    make: str
    model: str
    year: int
    vin: Optional[str] = None

class ServiceRequestCreate(BaseModel):
    customer: CustomerDetails
    vehicle: Optional[VehicleDetails] = None
    intake_data: dict = Field(default_factory=dict)
    service_request: dict

class ServiceRequestEdit(BaseModel):
    issue_description: str
    vehicle_details: Optional[VehicleDetails] = None
    intake_data: Optional[dict] = None
    booking_time: Optional[str] = None
    booking_type: Optional[str] = None
    duration_minutes: Optional[int] = None
    customer_consent_obtained: Optional[bool] = False



def extract_vehicle_from_summary(summary: str) -> str:
    """Extract vehicle/asset string from an AI call summary."""
    import re
    if not summary:
        return ""
    match = re.search(
        r"(?:(?:Customer'?s?\s+)?(?:Vehicle|Asset))(?:\s+(?:information|details|info))?(?:\s*\([^)]*\))?:\s*([^\n\r]+)",
        summary,
        re.IGNORECASE,
    )
    if match:
        vehicle = match.group(1).strip(" .\t")
        if vehicle.lower() in [
            "none",
            "n/a",
            "not mentioned",
            "unknown",
            "none mentioned",
            "not provided",
        ]:
            return ""
        return vehicle
    return ""


@router.get("/calls")
async def get_calls(limit: Optional[int] = None, offset: Optional[int] = None):
    from serviceBot.db.connection import get_db_connection, dict_cursor

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            query = """
                SELECT cn.id, cn.call_id, COALESCE(c.name, 'Unknown Caller') AS customer_name,
                       COALESCE(c.phone, '--') AS phone, cn.summary, cn.transcript, cn.created_at
                FROM crm_notes cn
                LEFT JOIN customers c ON cn.customer_id = c.id
                ORDER BY cn.created_at DESC
            """
            params = []
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
                if offset is not None:
                    query += " OFFSET %s"
                    params.append(offset)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            res = []
            for row in rows:
                r = dict(row)
                if not isinstance(r["created_at"], str) and r["created_at"]:
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                
                # Extract vehicle/asset from AI summary instead of listing all registered vehicles
                r["vehicle"] = extract_vehicle_from_summary(r.get("summary", ""))
                res.append(r)
            return res

@router.get("/appointments")
async def get_appointments():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import get_service_required_fields
    from serviceBot.services.sms_reminders import parse_booking_datetime
    import datetime as dt_mod

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sr.id, sr.booking_time AS appointment_datetime, sr.service_type, sr.issue_description, sr.duration_minutes, sr.status, sr.created_at, c.name AS customer_name, c.phone,
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

                duration = r.get("duration_minutes")
                if not duration:
                    svc = r.get("service_type") or r.get("issue_description") or ""
                    svc_fields = get_service_required_fields(svc) if svc else None
                    duration = (svc_fields.get("duration_minutes") or 60) if svc_fields else 60
                r["duration_minutes"] = duration

                raw_time = r.get("appointment_datetime")
                if raw_time:
                    dt = parse_booking_datetime(str(raw_time))
                    if dt:
                        end_dt = dt + dt_mod.timedelta(minutes=duration)
                        r["booking_start_time"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                        r["booking_end_time"] = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        r["booking_start_time"] = str(raw_time)
                        r["booking_end_time"] = None
                else:
                    r["booking_start_time"] = None
                    r["booking_end_time"] = None

                res.append(r)
            return res

@router.get("/service-requests")
async def get_service_requests(
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    escalated: Optional[bool] = None,
):
    return await run_in_threadpool(_load_service_requests, limit, offset, escalated)


def _booking_start_is_past(value):
    from serviceBot.services import timezone_service
    from serviceBot.services.sms_reminders import parse_booking_datetime

    if not value:
        return False
    text = str(value).strip()
    if " to " in text:
        text = text.split(" to ", 1)[0].strip()
    elif " - " in text and not text.startswith("-"):
        text = text.split(" - ", 1)[0].strip()
    try:
        start = dt_mod.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        start = parse_booking_datetime(text)
    return start is not None and timezone_service.to_business_tz(start) < timezone_service.now_in_business_tz()


def _load_service_requests(
    limit: int | None = None,
    offset: int | None = None,
    escalated: bool | None = None,
):
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import get_service_required_fields
    from serviceBot.services.sms_reminders import parse_booking_datetime
    import datetime as dt_mod

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            where_clauses = []
            params = []

            if escalated is True:
                where_clauses.append("sr.escalation_status != 'none' AND sr.status NOT IN ('cancelled', 'cancelled_by_customer', 'completed', 'done')")
            elif escalated is False:
                where_clauses.append("(sr.escalation_status = 'none' OR sr.status IN ('cancelled', 'cancelled_by_customer', 'completed', 'done'))")

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            query = f"""
                SELECT sr.id, sr.service_type, sr.issue_description, sr.status, sr.time_slot, sr.created_at, sr.updated_at,
                       sr.booking_type, sr.booking_time, sr.duration_minutes, sr.staff_agent_id, sr.service_components, sr.intake_data,
                       sr.notification_dispatched_at, sr.sla_expires_at, sr.calendar_integration_status,
                       (SELECT status FROM outbox_notifications WHERE request_id = sr.id
                        AND event_type = 'booking_notification' ORDER BY created_at DESC, id DESC LIMIT 1) AS notification_queue_status,
                       sr.confirmation_status, sr.escalation_status, sr.escalation_reason,
                       sr.confirmation_cutoff_at, sr.confirmed_at,
                       c.name AS customer_name, c.phone,
                       v.make, v.model, v.year,
                       sa.name AS staff_agent_name, sa.role AS staff_agent_role, sa.phone_number AS staff_agent_phone,
                       COALESCE((SELECT (status = 'FAILED') FROM sms_log WHERE appointment_id = sr.id ORDER BY created_at DESC, id DESC LIMIT 1), FALSE) AS has_failed_sms,
                       COALESCE((SELECT (status = 'FAILED_REVERTED') FROM outbox_notifications WHERE request_id = sr.id ORDER BY created_at DESC, id DESC LIMIT 1), FALSE) AS has_failed_email
                FROM service_requests sr
                LEFT JOIN customers c ON sr.customer_id = c.id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                {where_sql}
                ORDER BY COALESCE(sr.updated_at, sr.created_at) DESC, sr.id DESC
            """
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
                if offset is not None:
                    query += " OFFSET %s"
                    params.append(offset)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            res = []
            whatsapp_status_by_phone = {}
            for row in rows:
                r = dict(row)
                if not isinstance(r["created_at"], str) and r["created_at"]:
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                if r.get("updated_at") and not isinstance(r["updated_at"], str):
                    r["updated_at"] = r["updated_at"].strftime("%Y-%m-%d %H:%M:%S")

                if r.get("confirmation_cutoff_at") and not isinstance(r["confirmation_cutoff_at"], str):
                    r["confirmation_cutoff_at"] = r["confirmation_cutoff_at"].strftime("%Y-%m-%d %H:%M:%S")
                if r.get("confirmed_at") and not isinstance(r["confirmed_at"], str):
                    r["confirmed_at"] = r["confirmed_at"].strftime("%Y-%m-%d %H:%M:%S")

                from serviceBot.db.queries import is_agent_whatsapp_connected
                if r.get("staff_agent_id"):
                    sa_phone = r.get("staff_agent_phone")
                    if sa_phone and sa_phone not in whatsapp_status_by_phone:
                        whatsapp_status_by_phone[sa_phone] = is_agent_whatsapp_connected(sa_phone)
                    r["staff_agent_whatsapp_connected"] = whatsapp_status_by_phone.get(sa_phone, False)
                else:
                    r["staff_agent_whatsapp_connected"] = None

                duration = r.get("duration_minutes")
                if not duration:
                    svc = r.get("service_type") or r.get("issue_description") or ""
                    svc_fields = get_service_required_fields(svc) if svc else None
                    duration = (svc_fields.get("duration_minutes") or 60) if svc_fields else 60
                r["duration_minutes"] = duration

                raw_time = r.get("booking_time") or r.get("time_slot")
                if raw_time:
                    raw_str = str(raw_time).strip()
                    if " to " in raw_str:
                        parts = raw_str.split(" to ")
                        r["booking_start_time"] = parts[0].strip()
                        r["booking_end_time"] = parts[1].strip()
                    elif " - " in raw_str and not raw_str.startswith("-"):
                        parts = raw_str.split(" - ")
                        r["booking_start_time"] = parts[0].strip()
                        r["booking_end_time"] = parts[1].strip()
                    else:
                        dt = parse_booking_datetime(raw_str)
                        if dt:
                            end_dt = dt + dt_mod.timedelta(minutes=duration)
                            r["booking_start_time"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                            r["booking_end_time"] = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            r["booking_start_time"] = raw_str
                            r["booking_end_time"] = None
                else:
                    r["booking_start_time"] = None
                    r["booking_end_time"] = None

                # Compute candidate replacement agents for active escalated or reassigned items
                candidates = []
                is_closed_req = (r.get("status") or "").lower() in ("cancelled", "cancelled_by_customer", "completed", "done")
                if not is_closed_req and not _booking_start_is_past(raw_time) and (escalated is True or r.get("escalation_status") in ("escalated", "reassigned")):
                    try:
                        from serviceBot.db.queries import get_available_agents_for_request
                        all_agents = get_available_agents_for_request(r["id"])
                        curr_agent_id = r.get("staff_agent_id")
                        candidates = [a for a in all_agents if not curr_agent_id or a["id"] != curr_agent_id]
                    except Exception as e:
                        logger.warning(f"Error computing candidate agents for request {r.get('id')}: {e}")
                        candidates = []

                r["candidate_agents"] = candidates
                res.append(r)
            return res


class ReassignRequestPayload(BaseModel):
    new_agent_id: int
    reason: Optional[str] = "Supervisor manual reassignment"


@router.post("/service-requests/{request_id}/reassign")
async def reassign_service_request(request_id: int, payload: ReassignRequestPayload):
    """Reassign through the same validated reservation owner as normal assignment."""
    from serviceBot.db.connection import dict_cursor, get_db_connection
    from serviceBot.db.queries import assign_staff_agent_to_service_request
    from serviceBot.services.booking import BookingConflictError
