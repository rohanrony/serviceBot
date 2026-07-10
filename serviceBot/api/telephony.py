import os
from fastapi import APIRouter, Response, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import zoneinfo
from datetime import datetime

from serviceBot.db.queries import lookup_customer_by_phone, create_service_request, check_availability, book_appointment, get_service_required_fields, create_crm_note, create_callback_request, get_customer_appointments, reschedule_appointment
from serviceBot.services.rag import FAQService
from serviceBot.graph.nodes import handoff_node

# Load env variables from .env file
load_dotenv(override=True)

import re

def is_within_business_hours() -> bool:
    """
    Checks if the current time in America/New_York (Eastern Time)
    is within business hours: Monday to Friday, 7:00 AM to 6:00 PM.
    """
    tz = zoneinfo.ZoneInfo("America/New_York")
    now = datetime.now(tz)
    # 0 = Monday, 4 = Friday
    if now.weekday() > 4:
        return False
    start_time = now.replace(hour=7, minute=0, second=0, microsecond=0).time()
    end_time = now.replace(hour=18, minute=0, second=0, microsecond=0).time()
    return start_time <= now.time() < end_time

def clean_and_validate_phone(phone: str) -> Optional[str]:
    """
    Cleans a phone number by removing non-digits and checks if it is a valid 10-digit number.
    Handles optional leading US country code '1'.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return None

def generate_service_summary(transcript: str) -> str:
    """
    Generates a structured, service-oriented summary for Test
    using the OpenAI API.
    """
    if not transcript or not transcript.strip():
        return "No conversation transcript available."
    
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        
        # Load environment API Key
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            return "Error: OPENAI_API_KEY not configured."
            
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, openai_api_key=openai_key)
        
        system_prompt = (
            "You are a service advisor call summarizer for Test.\n"
            "Analyze the phone call transcript and write a concise, structured summary (3-4 bullet points) "
            "specifically tailored to an automotive service intake.\n\n"
            "Include the following details where mentioned:\n"
            "- The customer's primary concern or vehicle issue (e.g. grinding brakes, AC blowing warm air).\n"
            "- The vehicle's Make, Model, and Year.\n"
            "- Any scheduled appointments or booking times.\n"
            "- Additional context (e.g., if shuttle was requested, warranty questions).\n\n"
            "Format the summary as clean bullet points. Keep it professional and focused on the service intake details.\n\n"
            "CRITICAL: If the call ended before completion, or if no service details, vehicle info, or booking details were gathered, simply output the exact sentence: 'Call ended before completion; no service details were gathered.' Do not list empty bullet points or repeat placeholder information."
        )
        
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Transcript:\n{transcript}")
        ])
        
        return response.content.strip()
    except Exception as e:
        return f"Failed to generate AI summary: {str(e)}"

def get_booking_details(customer_id: int, service_request_id: int = None) -> dict:
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Get customer
            cursor.execute("SELECT name, phone FROM customers WHERE id = %s;", (customer_id,))
            cust = cursor.fetchone()
            cust_name = cust["name"] if cust else "Unknown Customer"
            cust_phone = cust["phone"] if cust else "Unknown Phone"
            
            # Get vehicle details
            vehicle_str = "Unknown Vehicle"
            issue_desc = ""
            service_type = "Repair"
            if service_request_id:
                cursor.execute("""
                    SELECT sr.service_type, sr.issue_description, v.year, v.make, v.model 
                    FROM service_requests sr
                    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                    WHERE sr.id = %s;
                """, (service_request_id,))
                row = cursor.fetchone()
                if row:
                    service_type = row["service_type"] or "Repair"
                    issue_desc = row["issue_description"] or ""
                    if row["make"] or row["model"]:
                        vehicle_str = f"{row['year'] or ''} {row['make'] or ''} {row['model'] or ''}".strip()
            else:
                # Get last vehicle
                cursor.execute("SELECT year, make, model FROM vehicles WHERE customer_id = %s ORDER BY id DESC LIMIT 1;", (customer_id,))
                row = cursor.fetchone()
                if row:
                    vehicle_str = f"{row['year'] or ''} {row['make'] or ''} {row['model'] or ''}".strip()
                    
            return {
                "customer_name": cust_name,
                "phone": cust_phone,
                "vehicle": vehicle_str,
                "service_type": service_type,
                "issue": issue_desc
            }



router = APIRouter(prefix="/api/v1/telephony", tags=["telephony"])

@router.post("/inbound")
@router.get("/inbound")
async def inbound_call():
    # Dynamically resolve agentId from environment settings (.env)
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "default-agent-id")
    
    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <ConversationAgent url="https://api.elevenlabs.io/v1/convai/conversation/stream" agentId="{agent_id}" />
    </Connect>
</Response>"""
    return Response(content=twiml_response, media_type="application/xml")


def extract_callback_from_transcript(transcript: str) -> Optional[dict]:
    """
    Uses ChatOpenAI to parse the transcript and extract callback preferences if requested.
    Returns a dict with 'preferred_time', 'service_type', 'issue_description' if callback is requested,
    otherwise None.
    """
    if not transcript or not transcript.strip():
        return None
        
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        import json
        
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            return None
            
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, openai_api_key=openai_key)
        
        system_prompt = (
            "Analyze the phone call transcript and determine if the customer requested or arranged a callback.\n"
            "Respond strictly in JSON format with the following keys:\n"
            "- \"requested\": true or false\n"
            "- \"preferred_time\": string or null (e.g., \"tomorrow morning at 8:00 a.m.\")\n"
            "- \"service_type\": string or null\n"
            "- \"issue_description\": string or null\n\n"
            "Only set \"requested\" to true if they explicitly arranged or wanted a callback."
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=transcript)
        ]
        
        response = llm.invoke(messages)
        res_text = response.content.strip()
        
        # Clean JSON markdown formatting if present
        if res_text.startswith("```json"):
            res_text = res_text[7:]
        if res_text.endswith("```"):
            res_text = res_text[:-3]
        res_text = res_text.strip()
        
        data = json.loads(res_text)
        if data.get("requested"):
            return {
                "preferred_time": data.get("preferred_time"),
                "service_type": data.get("service_type"),
                "issue_description": data.get("issue_description")
            }
    except Exception as e:
        print(f"Error extracting callback from transcript: {e}")
    return None


@router.post("/webhook")
async def post_call_webhook(request: Request = None, payload: Dict[str, Any] = None):
    print(f"\n--- ElevenLabs Webhook Received ---")
    import json
    import traceback
    from datetime import datetime
    
    import sys
    is_testing = "pytest" in sys.modules or any("pytest" in arg or "unittest" in arg for arg in sys.argv)
    if is_testing:
        log_file = "/Users/rohanroy/.gemini/antigravity-ide/scratch/webhook_activity.log"
    else:
        log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webhook_activity.log")

    
    def log_to_file(msg: str):
        try:
            with open(log_file, "a") as lf:
                lf.write(msg)
        except Exception as e:
            print(f"Log write failed: {e}")

    try:
        if isinstance(request, dict):
            payload = request
            request = None
            
        if request is not None:
            body_bytes = await request.body()
            body_str = body_bytes.decode("utf-8")
            
            log_to_file(f"\n[{datetime.now().isoformat()}] --- Webhook Request Received ---\n")
            log_to_file(f"Headers: {dict(request.headers)}\n")
            log_to_file(f"Body: {body_str}\n")
                
            if body_str.strip():
                payload = json.loads(body_str)
        else:
            log_to_file(f"\n[{datetime.now().isoformat()}] --- Direct Function Call ---\n")
            log_to_file(f"Payload: {json.dumps(payload)}\n")
            
        if payload is None:
            payload = {}
        
        event_type = payload.get("type")
        if event_type != "post_call_transcription":
            print(f"Ignored webhook event type: {event_type}")
            log_to_file(f"Ignored event type: {event_type}\n")
            return {"success": False, "message": f"Ignored event type: {event_type}"}
            
        data = payload.get("data") or {}
        conversation_id = data.get("conversation_id")
        if not conversation_id:
            print("Error: Missing conversation_id in webhook data payload.")
            log_to_file("Error: Missing conversation_id in webhook data payload.\n")
            raise HTTPException(status_code=400, detail="Missing conversation_id in data payload.")
            
        metadata = data.get("metadata") or {}
        phone_call = metadata.get("phone_call") or {}
        from_number = phone_call.get("external_number") or metadata.get("from_number") or data.get("user_id") or "Unknown"
        
        print(f"Processing call {conversation_id} from {from_number}...")
        log_to_file(f"Processing call {conversation_id} from {from_number}...\n")
        
        # Format the turn-by-turn conversation transcript
        transcript_arr = data.get("transcript") or []
        transcript_lines = []
        for turn in transcript_arr:
            role = turn.get("role", "unknown")
            role_label = "User" if role == "user" else "Agent"
            msg = turn.get("message", "")
            transcript_lines.append(f"{role_label}: {msg}")
        transcript_text = "\n".join(transcript_lines)
        
        # Generate service-oriented AI summary
        if transcript_text.strip():
            summary = generate_service_summary(transcript_text)
        else:
            analysis = data.get("analysis") or {}
            summary = analysis.get("summary") or "No summary provided."
        
        # Look up customer
        customer = None
        from_number_to_use = from_number if from_number else "Unknown"
        customer = lookup_customer_by_phone(from_number_to_use)
            
        if not customer:
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute(
                        "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
                        ("Unknown Customer", from_number_to_use)
                    )
                    conn.commit()
                    customer_id = cursor.fetchone()["id"]
        else:
            customer_id = customer["customer_id"]
            
        # Create the CRM note entry
        create_crm_note(
            call_id=conversation_id,
            customer_id=customer_id,
            summary=summary,
            transcript=transcript_text
        )
        print(f"CRM note created successfully for call {conversation_id}!")
        log_to_file(f"CRM note created successfully for call {conversation_id}!\n")
        
        # Fallback callback creation: check if callback request was requested in the call
        # and if it wasn't already logged in the last 5 minutes.
        callback_info = extract_callback_from_transcript(transcript_text)
        if callback_info:
            print("Extracted callback info from transcript, updating/creating service request...")
            log_to_file(f"Extracted callback info: {callback_info}\n")
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("""
                        SELECT id FROM service_requests 
                        WHERE customer_id = %s AND booking_type = 'callback' AND created_at >= NOW() - INTERVAL '5 minutes'
                    """, (customer_id,))
                    exists = cursor.fetchone()
                    if not exists:
                        sr_id = None
                        if customer:
                            sr_id = customer.get("open_sr_id")
                        if not sr_id:
                            cursor.execute("""
                                SELECT id FROM service_requests 
                                WHERE customer_id = %s 
                                ORDER BY id DESC LIMIT 1
                            """, (customer_id,))
                            sr_row = cursor.fetchone()
                            if sr_row:
                                sr_id = sr_row["id"]
                        
                        if sr_id:
                            # Select a staff agent to assign the callback to (default to ID 1 or the first agent)
                            cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 1;")
                            agent_row = cursor.fetchone()
                            staff_agent_id = agent_row["id"] if agent_row else None
                            
                            cursor.execute("""
                                UPDATE service_requests 
                                SET booking_type = 'callback', booking_time = %s, staff_agent_id = %s, updated_at = CURRENT_TIMESTAMP
                                WHERE id = %s;
                            """, (callback_info.get("preferred_time"), staff_agent_id, sr_id))
                        else:
                            cursor.execute("SELECT id FROM vehicles WHERE customer_id = %s ORDER BY id DESC LIMIT 1;", (customer_id,))
                            v_row = cursor.fetchone()
                            v_id = v_row["id"] if v_row else None
                            if not v_id:
                                cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Unknown', 'Unknown', 2000) RETURNING id;", (customer_id,))
                                v_id = cursor.fetchone()["id"]
                            
                            # Select a staff agent to assign the callback to (default to ID 1 or the first agent)
                            cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 1;")
                            agent_row = cursor.fetchone()
                            staff_agent_id = agent_row["id"] if agent_row else None
                            
                            cursor.execute("""
                                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status, booking_type, booking_time, staff_agent_id)
                                VALUES (%s, %s, 'Repair', 'Callback requested from transcript.', 'pending', 'callback', %s, %s) RETURNING id;
                            """, (customer_id, v_id, callback_info.get("preferred_time"), staff_agent_id))
                            sr_id = cursor.fetchone()["id"]
                        conn.commit()
                        print("Service request callback logged successfully!")
                        log_to_file("Service request callback logged successfully!\n")
                        
                        # Trigger Gmail notification for callback request
                        try:
                            agent_email = None
                            if staff_agent_id:
                                cursor.execute("""
                                    SELECT COALESCE(uga.email, sa.email) AS email
                                    FROM staff_agents sa
                                    LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                                    WHERE sa.id = %s;
                                """, (staff_agent_id,))
                                a_row = cursor.fetchone()
                                agent_email = a_row["email"] if a_row else None
                                
                            details = get_booking_details(customer_id, sr_id)
                            details["time"] = callback_info.get("preferred_time") or "ASAP"
                            from serviceBot.services.gmail import send_booking_notification
                            send_booking_notification("callback", details, agent_email=agent_email)
                        except Exception as email_err:
                            print(f"Error triggering webhook callback email: {email_err}")

        
        return {"success": True}
    except Exception as err:
        print(f"ERROR: Exception while processing ElevenLabs post-call webhook: {err}")
        tb_str = traceback.format_exc()
        print(tb_str)
        log_to_file(f"ERROR: {str(err)}\n{tb_str}\n")
        raise HTTPException(status_code=500, detail=str(err))


class ElevenLabsToolCall(BaseModel):
    tool_call_id: str
    name: str
    arguments: Dict[str, Any]


voice_router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@voice_router.post("/tools")
async def voice_tools(payload: Dict[str, Any], name: Optional[str] = None):
    # Check if this is the standard wrapped tool call format
    if "tool_call_id" in payload and "name" in payload and "arguments" in payload:
        tool_name = payload["name"]
        args = payload["arguments"]
        tool_call_id = payload["tool_call_id"]
    else:
        # Flat format - extract name and arguments
        # Check if name is supplied in the query params
        tool_name = name
        
        # If not in query params, try to detect from the payload keys
        if not tool_name:
            if any(k in payload for k in ["appointment_datetime", "appointmentDatetime", "datetime"]):
                tool_name = "book_appointment"
            elif any(k in payload for k in ["preferred_date", "preferredDate"]):
                tool_name = "check_availability"
            elif any(k in payload for k in ["service_name", "serviceName", "service"]):
                tool_name = "get_service_fields"
            elif any(k in payload for k in ["query_text", "query"]):
                tool_name = "query_knowledge_base"
            elif any(k in payload for k in ["make", "model", "year", "issue_description", "issue"]):
                tool_name = "create_service_request"
            elif "phone" in payload:
                # Default to check_availability if only phone is provided, or route accordingly
                tool_name = "check_availability"
            else:
                tool_name = "check_availability"

        args = payload
        tool_call_id = payload.get("tool_call_id", "call_flat")

    result = {"success": False, "message": f"Unknown tool called: {tool_name}"}

    try:
        if tool_name == "check_availability":
            preferred_date = args.get("preferred_date") or args.get("preferredDate")
            slots = check_availability(preferred_date=preferred_date)
            result = {
                "success": True,
                "available_slots": slots,
                "message": f"Found {len(slots)} available slots on/after {preferred_date}." if slots else "No slots found."
            }

        elif tool_name in ["cba_webbook", "cba_webhook", "transfer_call", "handoff"]:
            if not is_within_business_hours():
                result = {
                    "success": False,
                    "message": "Handoff to a human agent is only available during our business hours, which are Monday to Friday from 7:00 AM to 6:00 PM. Currently we are closed. Please let the caller know that we are currently closed, and offer to schedule an appointment or arrange a callback instead."
                }
            else:
                # Perform handoff node simulation
                phone = args.get("phone")
                customer = None
                if phone:
                    customer = lookup_customer_by_phone(phone)
                if not customer:
                    customer = {
                        "name": args.get("customer_name") or args.get("name") or "Unknown Customer",
                        "phone": phone or "Unknown"
                    }

                # Gather summary
                from langchain_core.messages import HumanMessage
                issue_description = args.get("issue_description") or "Not specified"
                state = {
                    "messages": [HumanMessage(content=f"I have an issue: {issue_description}")],
                    "customer": customer,
                    "service_request_id": args.get("service_request_id"),
                    "appointment_id": args.get("appointment_id")
                }
                handoff_result = handoff_node(state)
                summary = handoff_result.get("handoff_summary", "Handoff initiated.")
                from serviceBot.api.portal import load_config
                config = load_config()
                handoff_number = config.get("handoff_phone_number", "+14242704893")
                result = {
                    "success": True,
                    "message": "Call transferred to human customer service representative successfully.",
                    "summary": summary,
                    "transfer_phone_number": handoff_number
                }

        elif tool_name == "create_service_request":
            phone = args.get("phone")
            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number. Please ask the caller to repeat or correct their phone number."
                }
            else:
                phone = validated_phone
                customer_name = args.get("customer_name") or args.get("name")
                make = args.get("make") or "Unknown"
                model = args.get("model") or "Unknown"
                year = args.get("year") or 2000
                issue_description = args.get("issue_description") or args.get("issue") or "Not specified"
                service_type = args.get("service_type") or args.get("serviceType") or "Repair"
                time_slot = args.get("time_slot") or args.get("timeSlot")

                # Check if customer exists
                customer_id = None
                phone_to_lookup = phone if phone else "Unknown"
                c_data = lookup_customer_by_phone(phone_to_lookup)
                if c_data:
                    customer_id = c_data["customer_id"]
                    # If existing customer name is "Unknown Customer" but we got a real name, update it!
                    if c_data.get("name") == "Unknown Customer" and customer_name and customer_name != "Unknown Customer":
                        from serviceBot.db.connection import get_db_connection, dict_cursor
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute("UPDATE customers SET name = %s WHERE id = %s;", (customer_name, customer_id))
                                conn.commit()
                
                if not customer_id:
                    # Insert customer
                    from serviceBot.db.connection import get_db_connection, dict_cursor
                    with get_db_connection() as conn:
                        with dict_cursor(conn) as cursor:
                            cursor.execute(
                                "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
                                (customer_name or "Unknown Customer", phone_to_lookup)
                            )
                            conn.commit()
                            customer_id = cursor.fetchone()["id"]

                # Create service request
                vehicle_details = {"make": make, "model": model, "year": year}
                sr_id = create_service_request(
                    customer_id=customer_id,
                    vehicle_details=vehicle_details,
                    issue=issue_description,
                    service_type=service_type,
                    time_slot=time_slot
                )
                result = {
                    "success": True,
                    "service_request_id": sr_id,
                    "message": "Service request created successfully."
                }

        elif tool_name == "book_appointment":
            phone = args.get("phone")
            appointment_datetime = args.get("appointment_datetime") or args.get("appointmentDatetime") or args.get("datetime")
            service_type = args.get("service_type") or args.get("serviceType") or "Repair"

            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number. Please ask the caller to repeat or correct their phone number."
                }
            else:
                phone = validated_phone
                customer_name = args.get("customer_name") or args.get("name")
                make = args.get("make")
                model = args.get("model")
                year = args.get("year")
                
                c_data = lookup_customer_by_phone(phone)
                if c_data:
                    if not customer_name or customer_name == "Unknown Customer":
                        customer_name = c_data.get("name")
                    if not make or make == "Unknown":
                        make = c_data.get("make")
                    if not model or model == "Unknown":
                        model = c_data.get("model")
                    if not year or year == 2000 or str(year) == "2000":
                        year = c_data.get("year")
                
                if not customer_name or customer_name == "Unknown Customer" or customer_name.strip() == "":
                    result = {
                        "success": False,
                        "message": "Validation failed: Customer name is required to book an appointment. Please ask the customer for their full name."
                    }
                elif not make or make == "Unknown" or make.strip() == "" or not model or model == "Unknown" or model.strip() == "" or not year or year == 2000 or str(year) == "2000":
                    result = {
                        "success": False,
                        "message": "Validation failed: Vehicle year, make, and model are required to book an appointment. Please ask the customer for their vehicle's year, make, and model."
                    }
                else:
                    customer_id = None
                    sr_id = None
                    if c_data:
                        customer_id = c_data["customer_id"]
                        sr_id = c_data.get("open_sr_id")
                        if c_data.get("name") == "Unknown Customer" and customer_name != "Unknown Customer":
                            from serviceBot.db.connection import get_db_connection, dict_cursor
                            with get_db_connection() as conn:
                                with dict_cursor(conn) as cursor:
                                    cursor.execute("UPDATE customers SET name = %s WHERE id = %s;", (customer_name, customer_id))
                                    conn.commit()

                    if not customer_id:
                        from serviceBot.db.connection import get_db_connection, dict_cursor
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
                                    (customer_name, phone)
                                )
                                conn.commit()
                                customer_id = cursor.fetchone()["id"]

                    try:
                        vehicle_details = {"make": make, "model": model, "year": year}
                        appt_id = book_appointment(
                            customer_id=customer_id,
                            service_request_id=sr_id,
                            appointment_datetime=appointment_datetime,
                            service_type=service_type,
                            vehicle_details=vehicle_details
                        )
                        fields = get_service_required_fields(service_type)
                        price_range = fields["price_range"] if fields else "Varies"
                        
                        result = {
                            "success": True,
                            "appointment_id": appt_id,
                            "message": f"Appointment booked successfully. The estimated rate for this service is {price_range}. Please inform the customer of this rate."
                        }
                        
                        # Trigger email notification
                        try:
                            agent_email = None
                            from serviceBot.db.connection import get_db_connection, dict_cursor
                            with get_db_connection() as conn:
                                with dict_cursor(conn) as cursor:
                                    cursor.execute("""
                                        SELECT COALESCE(uga.email, sa.email) AS email
                                        FROM service_requests sr
                                        JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                                        LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                                        WHERE sr.id = %s;
                                    """, (appt_id,))

                                a_row = cursor.fetchone()
                                agent_email = a_row["email"] if a_row else None

                            details = get_booking_details(customer_id, appt_id)
                            details["time"] = appointment_datetime
                            details["service_type"] = service_type
                            from serviceBot.services.gmail import send_booking_notification
                            send_booking_notification("appointment", details, agent_email=agent_email)
                        except Exception as email_err:
                            print(f"Error triggering book appointment email: {email_err}")
                    except ValueError as val_err:
                        result = {
                            "success": False,
                            "message": f"Booking failed: {str(val_err)}"
                        }

        elif tool_name == "request_callback":
            phone = args.get("phone")
            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number. Please repeat or correct your phone number."
                }
            else:
                phone = validated_phone
                customer_name = args.get("customer_name") or args.get("name")
                make = args.get("make")
                model = args.get("model")
                year = args.get("year")
                
                c_data = lookup_customer_by_phone(phone)
                if c_data:
                    if not customer_name or customer_name == "Unknown Customer":
                        customer_name = c_data.get("name")
                    if not make or make == "Unknown":
                        make = c_data.get("make")
                    if not model or model == "Unknown":
                        model = c_data.get("model")
                    if not year or year == 2000 or str(year) == "2000":
                        year = c_data.get("year")
                
                if not customer_name or customer_name == "Unknown Customer" or customer_name.strip() == "":
                    result = {
                        "success": False,
                        "message": "Validation failed: Customer name is required to arrange a callback. Please ask the caller for their name."
                    }
                elif not make or make == "Unknown" or make.strip() == "" or not model or model == "Unknown" or model.strip() == "" or not year or year == 2000 or str(year) == "2000":
                    result = {
                        "success": False,
                        "message": "Validation failed: Vehicle year, make, and model are required to arrange a callback. Please ask the caller for their vehicle's year, make, and model."
                    }
                else:
                    customer_id = None
                    sr_id = args.get("service_request_id")
                    if c_data:
                        customer_id = c_data["customer_id"]
                        if not sr_id:
                            sr_id = c_data.get("open_sr_id")
                        if c_data.get("name") == "Unknown Customer" and customer_name != "Unknown Customer":
                            from serviceBot.db.connection import get_db_connection, dict_cursor
                            with get_db_connection() as conn:
                                with dict_cursor(conn) as cursor:
                                    cursor.execute("UPDATE customers SET name = %s WHERE id = %s;", (customer_name, customer_id))
                                    conn.commit()
                    
                    if not customer_id:
                        from serviceBot.db.connection import get_db_connection, dict_cursor
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
                                    (customer_name, phone)
                                )
                                conn.commit()
                                customer_id = cursor.fetchone()["id"]
                    
                    if not sr_id and any(k in args for k in ["service_type", "issue_description", "make"]):
                        issue_description = args.get("issue_description") or args.get("issue") or "Not specified"
                        service_type = args.get("service_type") or args.get("serviceType") or "Repair"
                        vehicle_details = {"make": make, "model": model, "year": year}
                        sr_id = create_service_request(
                            customer_id=customer_id,
                            vehicle_details=vehicle_details,
                            issue=issue_description,
                            service_type=service_type
                        )
                    
                    try:
                        preferred_time = args.get("preferred_time") or args.get("time_slot") or args.get("time")
                        vehicle_details = {"make": make, "model": model, "year": year}
                        cb_id = create_callback_request(
                            customer_id=customer_id,
                            service_request_id=sr_id,
                            preferred_time=preferred_time,
                            vehicle_details=vehicle_details
                        )
                        result = {
                            "success": True,
                            "callback_id": cb_id,
                            "message": "Callback request captured successfully."
                        }
                        
                        # Trigger email notification
                        try:
                            agent_email = None
                            from serviceBot.db.connection import get_db_connection, dict_cursor
                            with get_db_connection() as conn:
                                with dict_cursor(conn) as cursor:
                                    cursor.execute("""
                                        SELECT COALESCE(uga.email, sa.email) AS email
                                        FROM service_requests sr
                                        JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                                        LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                                        WHERE sr.id = %s;
                                    """, (cb_id,))
                                    a_row = cursor.fetchone()
                                    agent_email = a_row["email"] if a_row else None

                            details = get_booking_details(customer_id, cb_id)
                            details["time"] = preferred_time or "ASAP"
                            from serviceBot.services.gmail import send_booking_notification
                            send_booking_notification("callback", details, agent_email=agent_email)
                        except Exception as email_err:
                            print(f"Error triggering callback email: {email_err}")
                    except ValueError as val_err:
                        result = {
                            "success": False,
                            "message": f"Callback request failed: {str(val_err)}"
                        }

        elif tool_name == "get_customer_appointments":
            phone = args.get("phone")
            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number."
                }
            else:
                phone = validated_phone
                appts = get_customer_appointments(phone)
                result = {
                    "success": True,
                    "appointments": appts,
                    "message": f"Found {len(appts)} appointments for phone number {phone}." if appts else f"No active appointments found for phone number {phone}."
                }

        elif tool_name == "reschedule_appointment":
            phone = args.get("phone")
            new_datetime = args.get("new_appointment_datetime") or args.get("newAppointmentDatetime") or args.get("appointment_datetime")
            
            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number."
                }
            else:
                phone = validated_phone
                appts = get_customer_appointments(phone)
                if not appts:
                    result = {
                        "success": False,
                        "message": f"No active appointments found for phone number {phone}."
                    }
                else:
                    # Choose appointment to reschedule
                    appt_id = args.get("appointment_id")
                    if not appt_id:
                        appt_id = appts[0]["id"]
                    
                    try:
                        # Attempt to reschedule
                        reschedule_appointment(appointment_id=appt_id, new_datetime=new_datetime)
                        result = {
                            "success": True,
                            "appointment_id": appt_id,
                            "message": f"Appointment rescheduled to {new_datetime} successfully."
                        }
                        
                        # Trigger email notification
                        try:
                            cust_id = None
                            c_data = lookup_customer_by_phone(phone)
                            if c_data:
                                cust_id = c_data["customer_id"]
                            if cust_id:
                                agent_email = None
                                from serviceBot.db.connection import get_db_connection, dict_cursor
                                with get_db_connection() as conn:
                                    with dict_cursor(conn) as cursor:
                                        cursor.execute("""
                                            SELECT COALESCE(uga.email, sa.email) AS email
                                            FROM service_requests sr
                                            JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                                            LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                                            WHERE sr.id = %s;
                                        """, (appt_id,))
                                        a_row = cursor.fetchone()
                                        agent_email = a_row["email"] if a_row else None


                                details = get_booking_details(cust_id, appt_id)
                                details["time"] = new_datetime
                                from serviceBot.services.gmail import send_booking_notification
                                send_booking_notification("reschedule", details, agent_email=agent_email)
                        except Exception as email_err:
                            print(f"Error triggering reschedule email: {email_err}")
                    except Exception as e:
                        result = {
                            "success": False,
                            "message": f"Failed to reschedule: {str(e)}"
                        }

        elif tool_name in ["query_knowledge_base", "faq_lookup"]:
            query_text = args.get("query_text") or args.get("query")
            faq_service = FAQService()
            answer = faq_service.answer_question(query_text)
            result = {
                "success": True,
                "answer": answer
            }

        elif tool_name in ["get_service_fields", "get_required_fields"]:
            from serviceBot.api.portal import load_config
            service_name = args.get("service_name") or args.get("serviceName") or args.get("service") or ""
            fields_data = get_service_required_fields(service_name)
            if fields_data:
                result = {
                    "success": True,
                    "service_found": True,
                    "service_name": fields_data["name"],
                    "description": fields_data["description"],
                    "price_range": fields_data["price_range"],
                    "duration_minutes": fields_data["duration_minutes"],
                    "required_fields": {
                        "customer_name": bool(fields_data["req_customer_name"]),
                        "phone_number": bool(fields_data["req_phone_number"]),
                        "vehicle_details": bool(fields_data["req_vehicle_details"]),
                        "issue_description": bool(fields_data["req_issue_description"]),
                        "location": bool(fields_data["req_location"])
                    }
                }
            else:
                config = load_config()
                default_fields = config.get("required_fields", {
                    "customer_name": True,
                    "phone_number": True,
                    "vehicle_details": True,
                    "issue_description": True,
                    "location": True
                })
                result = {
                    "success": True,
                    "service_found": False,
                    "message": f"Service '{service_name}' not found in catalog. Using default fields.",
                    "required_fields": default_fields
                }

    except Exception as e:
        result = {
            "success": False,
            "message": f"Error executing tool {tool_name}: {str(e)}"
        }

    response_data = {
        "tool_call_id": tool_call_id,
        "result": result
    }
    if isinstance(result, dict):
        for k, v in result.items():
            if k not in response_data:
                response_data[k] = v

    return response_data

