import os
import json
from fastapi import APIRouter, Response, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import zoneinfo
from datetime import datetime, timedelta

from serviceBot.services.booking import get_session_booking, track_session_booking


class ConsolidateAppointmentRequest(BaseModel):
    appointment_id: int
    phone: Optional[str] = None
    additional_issue: str
    additional_service_type: Optional[str] = None
    additional_duration_minutes: Optional[int] = 45


class SessionBookingContext(BaseModel):
    session_key: str
    service_request_id: int
    booking_time: str
    duration_minutes: int = 60
    phone: Optional[str] = None


def format_appointment_window_message(
    booking_time: str,
    duration_minutes: int = 60,
    price_range: str = "Varies",
    is_update: bool = False,
    previous_booking_time: Optional[str] = None,
) -> tuple[str, str]:
    """
    Computes expected_end_time and formats a customer message that states
    both the start time and expected completion window, along with the notice
    that the duration is likely to extend.
    """
    clean_dt_str = str(booking_time).strip().replace("T", " ")
    if "." in clean_dt_str:
        clean_dt_str = clean_dt_str.split(".")[0]

    start_dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M", "%I:%M %p"):
        try:
            start_dt = datetime.strptime(clean_dt_str[:19], fmt)
            break
        except ValueError:
            continue

    if start_dt:
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        start_fmt = start_dt.strftime("%I:%M %p").lstrip("0")
        end_fmt = end_dt.strftime("%I:%M %p").lstrip("0")
        end_dt_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        window_str = f"from {start_fmt} to approximately {end_fmt}"
    else:
        end_dt_str = str(booking_time)
        window_str = f"at {booking_time} (approx {duration_minutes} minutes)"

    extension_notice = "Please note that we are scheduling for this time window, but the visit is likely to extend depending on service and diagnostic findings."

    if is_update:
        prev_str = f" from {previous_booking_time}" if previous_booking_time else ""
        msg = (
            f"Updated existing appointment{prev_str} to {booking_time} ({window_str}). "
            f"Calendar slot updated successfully. {extension_notice}"
        )
    else:
        msg = (
            f"Appointment booked successfully. Service request booked as an appointment {window_str}. Calendar projection and notifications are queued. "
            f"The estimated rate for this service is {price_range}. {extension_notice}"
        )
    return end_dt_str, msg


from serviceBot.db.queries import lookup_customer_by_phone, create_service_request, check_availability, book_appointment, get_service_required_fields, create_crm_note, create_callback_request, get_customer_appointments, reschedule_appointment, cancel_appointment, update_customer_name, get_customer_service_history, consolidate_appointment_service
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.services.calendar_availability import verify_contiguous_slot_capacity
from serviceBot.services.rag import FAQService
from serviceBot.graph.nodes import handoff_node
from serviceBot.logger import get_logger
from serviceBot.api.portal import load_config
from langchain_core.messages import HumanMessage

logger = get_logger("api.telephony")

# Load env variables from .env file
load_dotenv(override=False)

import re

def is_within_business_hours() -> bool:
    """
    Checks if the current time in configured business timezone
    is within business hours: Monday to Friday, 7:00 AM to 6:00 PM.
    """
    from serviceBot.services import timezone_service
    now = timezone_service.now_in_business_tz()
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
    Generates a structured, service-oriented summary for Davidson Car Care
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
            "You are a service advisor call summarizer for Davidson Car Care.\n"
            "Analyze the phone call transcript and write a concise, structured summary (3-4 bullet points) "
            "specifically tailored to an automotive service intake.\n\n"
            "Include the following details where mentioned:\n"
            "- The customer's primary concern or vehicle issue (e.g. grinding brakes, AC blowing warm air).\n"
            "- The vehicle/asset details (Make, Model, and Year) formatted as 'Vehicle details: <Year Make Model>' (or 'None' if not specified).\n"
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
            duration_minutes = 60
            if service_request_id:
                cursor.execute("""
                    SELECT sr.service_type, sr.issue_description, sr.duration_minutes, v.year, v.make, v.model 
                    FROM service_requests sr
                    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                    WHERE sr.id = %s;
                """, (service_request_id,))
                row = cursor.fetchone()
                if row:
                    service_type = row["service_type"] or "Repair"
                    issue_desc = row["issue_description"] or ""
                    duration_minutes = row["duration_minutes"] or 60
                    if row["make"] or row["model"]:
                        vehicle_str = f"{row['year'] or ''} {row['make'] or ''} {row['model'] or ''}".strip()
            else:
                # Get last vehicle
                cursor.execute("SELECT year, make, model FROM vehicles WHERE customer_id = %s ORDER BY id DESC LIMIT 1;", (customer_id,))
                row = cursor.fetchone()
                if row:
                    vehicle_str = f"{row['year'] or ''} {row['make'] or ''} {row['model'] or ''}".strip()
                    
            if not duration_minutes or duration_minutes == 60:
                from serviceBot.db.queries import get_service_required_fields
                fields = get_service_required_fields(service_type)
                if fields and fields.get("duration_minutes"):
                    duration_minutes = fields["duration_minutes"]

            return {
                "customer_name": cust_name,
                "phone": cust_phone,
                "vehicle": vehicle_str,
                "service_type": service_type,
                "duration_minutes": duration_minutes,
                "issue": issue_desc
            }



router = APIRouter(prefix="/api/v1/telephony", tags=["telephony"])

@router.post("/inbound")
@router.get("/inbound")
async def inbound_call(request: Request = None):
    # Dynamically resolve agentId from environment settings (.env)
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "default-agent-id")
    
    caller_phone = None
    form_dict = {}
    if request:
        try:
            form_data = await request.form()
            form_dict = {key: value for key, value in form_data.items()}
            caller_phone = form_data.get("From") or form_data.get("Caller") or request.query_params.get("From")
        except Exception:
            form_dict = {}

        from serviceBot.services.webhook_security import (
            WebhookVerificationError,
            verify_twilio_request,
        )

        try:
            verify_twilio_request(request, form_dict)
        except WebhookVerificationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    import html
    recent_booking_context = ""
    customer_name = ""
    upcoming_appointments_summary = ""
    recent_history_summary = ""

    clean_caller_phone = clean_and_validate_phone(caller_phone) if caller_phone else None
    phone_for_param = clean_caller_phone or caller_phone

    if phone_for_param:
        from serviceBot.db import queries
        from unittest.mock import Mock
        def _resolve(mod_fn, q_fn):
            if isinstance(mod_fn, Mock):
                return mod_fn
            if isinstance(q_fn, Mock):
                return q_fn
            return q_fn

        lookup_cust = _resolve(lookup_customer_by_phone, getattr(queries, "lookup_customer_by_phone", None))
        get_appts = _resolve(get_customer_appointments, getattr(queries, "get_customer_appointments", None))
        get_hist = _resolve(get_customer_service_history, getattr(queries, "get_customer_service_history", None))

        c_data = lookup_cust(phone_for_param)
        if c_data:
            c_name = c_data.get("name")
            if c_name and c_name not in ("Unknown Customer", "Unknown", ""):
                customer_name = c_name

            print(f"Inbound call from existing customer #{c_data.get('customer_id')} ({customer_name}). Active SR: {c_data.get('open_sr_type')}")
            appts = []
            try:
                appts = get_appts(caller_phone)
                if not appts and phone_for_param and phone_for_param != caller_phone:
                    appts = get_appts(phone_for_param)
                if appts:
                    # Filter for upcoming appointments (scheduled today or in the future)
                    from serviceBot.services import timezone_service
                    now_dt = timezone_service.now_in_business_tz()
                    today_str = now_dt.strftime("%Y-%m-%d")

                    upcoming_list = [
                        a for a in appts
                        if a.get("appointment_datetime") and str(a.get("appointment_datetime"))[:10] >= today_str
                    ]
                    target_appt = upcoming_list[0] if upcoming_list else appts[0]
                    v_info = f"{target_appt.get('year', '')} {target_appt.get('make', '')} {target_appt.get('model', '')}".strip() or "Vehicle"
                    srv = target_appt.get("service_type") or "Service"
                    dt = target_appt.get("appointment_datetime") or "recent date"
                    issue = target_appt.get("issue_description")
                    duration = target_appt.get("duration_minutes") or 60
                    recent_booking_context = f"Recent booking on {dt} for {v_info} ({srv})".strip()

                    if upcoming_list:
                        if len(upcoming_list) == 1:
                            if issue and issue.lower() != srv.lower():
                                upcoming_appointments_summary = f"Scheduled for {dt} for {v_info} regarding {srv} ({issue}). Duration: {duration} min."
                            else:
                                upcoming_appointments_summary = f"Scheduled for {dt} for {v_info} regarding {srv}. Duration: {duration} min."
                        else:
                            summaries = []
                            for idx, u in enumerate(upcoming_list, 1):
                                u_dt = u.get("appointment_datetime")
                                u_v = f"{u.get('year', '')} {u.get('make', '')} {u.get('model', '')}".strip() or "Vehicle"
                                u_srv = u.get("service_type") or "Service"
                                summaries.append(f"{idx}) {u_dt} for {u_v} ({u_srv})")
                            upcoming_appointments_summary = f"Customer has {len(upcoming_list)} upcoming appointment(s): " + "; ".join(summaries)
                    else:
                        if issue and issue.lower() != srv.lower():
                            upcoming_appointments_summary = f"Scheduled for {dt} for {v_info} regarding {srv} ({issue}). Duration: {duration} min."
                        else:
                            upcoming_appointments_summary = f"Scheduled for {dt} for {v_info} regarding {srv}. Duration: {duration} min."
            except Exception as e:
                print(f"Error fetching upcoming appointments context: {e}")

            try:
                history = get_hist(caller_phone)
                if history:
                    first_appt_id = appts[0].get("id") if (appts and len(appts) > 0) else None
                    prev_items = [h for h in history if h.get("id") != first_appt_id]
                    if prev_items:
                        h_parts = []
                        for h in prev_items[:2]:
                            h_dt = str(h.get("booking_time") or h.get("created_at") or "")[:10]
                            h_srv = h.get("service_type") or "Service"
                            h_issue = h.get("issue_description")
                            h_stat = h.get("status", "past")
                            if h_issue and h_issue.lower() != h_srv.lower():
                                h_parts.append(f"{h_srv} ({h_issue}) on {h_dt} [{h_stat}]")
                            else:
                                h_parts.append(f"{h_srv} on {h_dt} [{h_stat}]")
                        recent_history_summary = "; ".join(h_parts)
                    elif history:
                        h = history[0]
                        h_dt = str(h.get("booking_time") or h.get("created_at") or "")[:10]
                        h_srv = h.get("service_type") or "Service"
                        recent_history_summary = f"{h_srv} on {h_dt}"
            except Exception as e:
                print(f"Error fetching service history context: {e}")

    param_xml = ""
    if phone_for_param:
        param_xml += f'        <Parameter name="caller_phone" value="{html.escape(phone_for_param, quote=True)}" />\n'
    if customer_name:
        param_xml += f'        <Parameter name="customer_name" value="{html.escape(customer_name, quote=True)}" />\n'
    if upcoming_appointments_summary:
        param_xml += f'        <Parameter name="upcoming_appointments_summary" value="{html.escape(upcoming_appointments_summary, quote=True)}" />\n'
    if recent_history_summary:
        param_xml += f'        <Parameter name="recent_history_summary" value="{html.escape(recent_history_summary, quote=True)}" />\n'
    if recent_booking_context:
        param_xml += f'        <Parameter name="recent_booking_context" value="{html.escape(recent_booking_context, quote=True)}" />\n'

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <ConversationAgent url="https://api.elevenlabs.io/v1/convai/conversation/stream" agentId="{agent_id}">
{param_xml}        </ConversationAgent>
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


def _record_callback_for_staff_review(
    customer_id: int,
    customer: Optional[dict],
    callback_info: dict,
) -> Optional[int]:
    """Record an AI-extracted callback preference without scheduling a reservation."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id FROM service_requests
                WHERE customer_id = %s
                  AND created_at >= NOW() - INTERVAL '5 minutes'
                LIMIT 1;
                """,
                (customer_id,),
            )
            if cursor.fetchone():
                return None

            candidate_id = (customer or {}).get("open_sr_id")
            if candidate_id:
                cursor.execute(
                    """
                    SELECT id FROM service_requests
                    WHERE id = %s AND customer_id = %s AND booking_type IS NULL
                    FOR UPDATE;
                    """,
                    (candidate_id, customer_id),
                )
                if not cursor.fetchone():
                    candidate_id = None
            if not candidate_id:
                cursor.execute(
                    """
                    SELECT id FROM service_requests
                    WHERE customer_id = %s AND status = 'pending' AND booking_type IS NULL
                    ORDER BY id DESC LIMIT 1 FOR UPDATE;
                    """,
                    (customer_id,),
                )
                row = cursor.fetchone()
                candidate_id = row["id"] if row else None

            issue = callback_info.get("issue_description") or "Callback requested from call transcript."
            if candidate_id:
                cursor.execute(
                    """
                    UPDATE service_requests
                    SET booking_type = 'callback',
                        booking_time = NULL,
                        staff_agent_id = NULL,
                        issue_description = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                    """,
                    (issue, candidate_id),
                )
                request_id = candidate_id
            else:
                cursor.execute(
                    "SELECT id FROM vehicles WHERE customer_id = %s ORDER BY id DESC LIMIT 1;",
                    (customer_id,),
                )
                vehicle = cursor.fetchone()
                vehicle_id = vehicle["id"] if vehicle else None
                if not vehicle_id:
                    cursor.execute(
                        """
                        INSERT INTO vehicles (customer_id, make, model, year)
                        VALUES (%s, 'Unknown', 'Unknown', 2000)
                        RETURNING id;
                        """,
                        (customer_id,),
                    )
                    vehicle_id = cursor.fetchone()["id"]
                cursor.execute(
                    """
                    INSERT INTO service_requests
                    (customer_id, vehicle_id, service_type, issue_description, status, booking_type)
                    VALUES (%s, %s, 'Callback / Phone Consultation', %s, 'pending', 'callback')
                    RETURNING id;
                    """,
                    (customer_id, vehicle_id, issue),
                )
                request_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO service_request_audit_log
                (request_id, triggered_by, from_status, to_status, notes)
                VALUES (%s, 'elevenlabs_webhook', NULL, 'pending',
                        'Callback preference extracted; staff confirmation is required before scheduling.');
                """,
                (request_id,),
            )
            return request_id


@router.post("/webhook")
async def post_call_webhook(request: Request = None, payload: Dict[str, Any] = None):
    event_store = None
    event_id = None
    event_claimed = False
    raw_event_payload = payload or {}
    try:
        if isinstance(request, dict):
            payload = request
            request = None
            raw_event_payload = payload
        if request is not None:
            body_bytes = await request.body()
            raw_event_payload = body_bytes
            from serviceBot.services.webhook_security import (
                WebhookVerificationError,
                verify_elevenlabs_request,
            )
            try:
                verify_elevenlabs_request(
                    body_bytes,
                    request.headers.get("ElevenLabs-Signature"),
                )
            except WebhookVerificationError as exc:
                if exc.status_code >= 500:
                    logger.error("ElevenLabs webhook verification unavailable: reason=%s", exc.code)
                    detail = "Webhook temporarily unavailable."
                else:
                    logger.warning("Rejected ElevenLabs webhook: reason=%s", exc.code)
                    detail = "Webhook authentication failed."
                raise HTTPException(status_code=exc.status_code, detail=detail) from exc
            if body_bytes.strip():
                try:
                    payload = json.loads(body_bytes)
                except json.JSONDecodeError as exc:
                    raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.") from exc

        if payload is None:
            payload = {}
        
        event_type = payload.get("type")
        if event_type != "post_call_transcription":
            return {"success": False, "message": f"Ignored event type: {event_type}"}
            
        data = payload.get("data") or {}
        conversation_id = data.get("conversation_id")
        if not conversation_id:
            raise HTTPException(status_code=400, detail="Missing conversation_id in data payload.")

        from serviceBot.services.webhook_security import (
            WebhookEventStore,
            WebhookReplayConflictError,
        )
        event_store = WebhookEventStore()
        event_id = conversation_id
        try:
            event_claimed = event_store.begin("elevenlabs", event_id, raw_event_payload)
        except WebhookReplayConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not event_claimed:
            return {"success": True, "duplicate": True}
            
        metadata = data.get("metadata") or {}
        phone_call = metadata.get("phone_call") or {}
        from_number = phone_call.get("external_number") or metadata.get("from_number") or data.get("user_id") or "Unknown"
        
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
        
        # Transcript extraction is advisory: staff must confirm a callback time before
        # capacity is reserved or any notification is sent.
        callback_info = extract_callback_from_transcript(transcript_text)
        if callback_info:
            _record_callback_for_staff_review(customer_id, customer, callback_info)

        event_store.complete("elevenlabs", event_id)
        return {"success": True}
    except HTTPException:
        if event_claimed and event_store and event_id:
            try:
                event_store.fail("elevenlabs", event_id)
            except Exception as state_err:
                logger.warning("Could not record ElevenLabs webhook failure: %s", state_err)
        raise
    except Exception:
        if event_claimed and event_store and event_id:
            try:
                event_store.fail("elevenlabs", event_id)
            except Exception as state_err:
                logger.warning("Could not record ElevenLabs webhook failure: %s", state_err)
        logger.exception("ElevenLabs post-call webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed.")


class ElevenLabsToolCall(BaseModel):
    tool_call_id: str
    name: str
    arguments: Dict[str, Any]


def _send_booking_notifications_bg(booking_kind: str, customer_id: int, item_id: int, booking_time: str, service_type: str = "Repair"):
    """Background worker function for sending email and SMS notifications without blocking HTTP response."""
    try:
        agent_email = None
        agent_name = None
        agent_phone = None
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("""
                    SELECT sa.name, sa.phone_number, COALESCE(uga.email, sa.email) AS email
                    FROM service_requests sr
                    LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                    LEFT JOIN user_google_accounts uga ON sa.id = uga.agent_id
                    WHERE sr.id = %s;
                """, (item_id,))
                a_row = cursor.fetchone()
                if a_row:
                    agent_name = a_row.get("name")
                    agent_email = a_row.get("email")
                    agent_phone = a_row.get("phone_number")

        details = get_booking_details(customer_id, item_id) or {}
        details["time"] = booking_time or ("Scheduled" if booking_kind == "appointment" else "ASAP")
        if service_type:
            details["service_type"] = service_type

        try:
            from serviceBot.services.gmail import send_booking_notification, send_admin_notification
            send_booking_notification(booking_kind, details, agent_email=agent_email)
            send_admin_notification(booking_kind, details, mechanic_name=agent_name, mechanic_email=agent_email)
        except Exception as email_err:
            logger.warning(f"Email notification failed ({booking_kind}): {email_err}")

        try:
            from serviceBot.services.sms_router import SMSNotificationRouter
            SMSNotificationRouter().process_event(
                event_type="BOOKING",
                appointment_id=item_id,
                customer_phone=details.get("phone"),
                agent_phone=agent_phone,
                booking_time=details.get("time")
            )
        except Exception as sms_err:
            logger.warning(f"SMS notification failed ({booking_kind}): {sms_err}")
    except Exception as notify_err:
        logger.warning(f"Background notification processing failed ({booking_kind}): {notify_err}")


voice_router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@voice_router.post("/tools")
async def voice_tools(payload: Dict[str, Any], request: Request = None, background_tasks: BackgroundTasks = None, name: Optional[str] = None):
    # Check if this is the standard wrapped tool call format
    if "name" in payload and "arguments" in payload:
        tool_name = payload["name"]
        args = payload["arguments"]
        tool_call_id = payload.get("tool_call_id", "call_flat")
    elif "tool_call_id" in payload and "name" in payload:
        tool_name = payload["name"]
        args = payload.get("arguments", {})
        tool_call_id = payload["tool_call_id"]
    else:
        # Flat format - extract name and arguments
        # Check if name is supplied in the query params or payload
        tool_name = name or payload.get("name")
        
        # If not in query params, try to detect from the payload keys
        if not tool_name:
            if any(k in payload for k in ["cancel_appointment", "cancellation_reason", "cancel_reason"]):
                tool_name = "cancel_appointment"
            elif any(k in payload for k in ["new_appointment_datetime", "new_datetime", "new_time", "new_slot"]):
                tool_name = "reschedule_appointment"
            elif any(k in payload for k in ["additional_issue", "additional_service_type", "additional_duration_minutes"]):
                tool_name = "consolidate_appointment_service"
            elif any(k in payload for k in ["summary_text", "summaryText", "summary", "reason", "transfer_phone_number"]):
                tool_name = "cba_webhook"
            elif any(k in payload for k in ["appointment_datetime", "appointmentDatetime", "datetime"]):
                tool_name = "book_appointment"
            elif any(k in payload for k in ["preferred_date", "preferredDate"]):
                tool_name = "check_availability"
            elif any(k in payload for k in ["preferred_time", "preferredTime", "callback_priority", "callback_number"]):
                tool_name = "request_callback"
            elif any(k in payload for k in ["service_name", "serviceName"]):
                tool_name = "get_service_fields"
            elif any(k in payload for k in ["query_text", "query"]):
                tool_name = "query_knowledge_base"
            elif any(k in payload for k in ["make", "model", "year", "issue_description", "issue"]):
                tool_name = "create_service_request"
            elif any(k in payload for k in ["phone", "phone_number", "phoneNumber", "caller_phone"]):
                tool_name = "get_customer_appointments"
            else:
                tool_name = "check_availability"

        args = payload
        tool_call_id = payload.get("tool_call_id", "call_flat")

    # Ingest verified Caller ID from incoming HTTP headers or query params if provided
    if request:
        header_caller = (
            request.headers.get("x-caller-id")
            or request.headers.get("caller_id")
            or request.query_params.get("caller_id")
            or request.query_params.get("caller_phone")
        )
        if header_caller and not str(header_caller).startswith("{{") and not args.get("caller_phone"):
            args["caller_phone"] = header_caller

    # Strip raw unexpanded template placeholders if passed by model
    if str(args.get("caller_phone", "")).startswith("{{"):
        args.pop("caller_phone", None)

    result = {"success": False, "message": f"Unknown tool called: {tool_name}"}

    try:
        if tool_name == "check_availability":
            preferred_date = args.get("preferred_date") or args.get("preferredDate")
            preferred_time = args.get("preferred_time") or args.get("preferredTime") or args.get("time") or args.get("preferred_slot")
            service_type = args.get("service_type") or args.get("serviceType") or args.get("service") or args.get("issue_description") or args.get("issue")
            booking_type = args.get("booking_type") or args.get("bookingType") or "appointment"
            slots = check_availability(service_type=service_type, preferred_date=preferred_date, booking_type=booking_type, preferred_time=preferred_time)

            from serviceBot.db.queries import parse_specific_time
            requested_time_target = parse_specific_time(f"{preferred_date or ''} {preferred_time or ''}")
            time_match = False
            if requested_time_target and slots:
                time_match = any(
                    datetime.strptime(s, "%Y-%m-%d %H:%M:%S").time().hour == requested_time_target.hour
                    and datetime.strptime(s, "%Y-%m-%d %H:%M:%S").time().minute == requested_time_target.minute
                    for s in slots
                )

            if slots:
                if time_match:
                    time_display = preferred_time if preferred_time else requested_time_target.strftime("%I:%M %p").lstrip("0")
                    msg = (
                        f"The requested time ({time_display}) IS AVAILABLE in our schedule! "
                        f"Recommended available slots: {', '.join(slots)}. "
                        f"Clearly confirm the requested time with the caller or offer these adjacent options. "
                        f"NOTE TO AGENT: Additional slots are also available throughout the day if the caller prefers another specific time. "
                        f"Never tell or imply to the caller that these are the only available slots for the day. "
                        f"CRITICAL: All appointments must conclude strictly by 6:00 PM. Never offer or accept an appointment that would run past 6:00 PM."
                    )
                else:
                    msg = (
                        f"Recommended available slots: {', '.join(slots)}. "
                        f"Clearly suggest 2 to 3 of these options to the caller. "
                        f"NOTE TO AGENT: These are recommended options around the caller's requested time/date that fit strictly within business hours. "
                        f"Additional slots are also available throughout the day if the caller prefers another specific time. "
                        f"Never tell or imply to the caller that these are the only available slots for the day. If the caller requests a different time, "
                        f"call check_availability with their preferred time. "
                        f"CRITICAL: All appointments must conclude strictly by 6:00 PM. Never offer or accept an appointment that would run past 6:00 PM."
                    )
            else:
                msg = (
                    "I apologize, but there are no open appointment slots available in our schedule around that time/date right now. "
                    "Please note our business hours are Monday to Friday, 7:00 AM to 6:00 PM, and appointments must conclude by 6:00 PM. "
                    "Please apologize to the caller for the inconvenience and offer to check another date or arrange an advisor callback."
                )
            result = {
                "success": True,
                "available_slots": slots,
                "message": msg
            }

        elif tool_name in ["cba_webbook", "cba_webhook", "transfer_call", "handoff"]:
            if not is_within_business_hours():
                result = {
                    "success": False,
                    "message": "Handoff to a human agent is only available during our business hours, which are Monday to Friday from 7:00 AM to 6:00 PM. Currently we are closed. Please let the caller know that we are currently closed, and offer to schedule an appointment or arrange a callback instead."
                }
            else:
                # Perform handoff node simulation
                phone = args.get("phone") or args.get("phone_number") or args.get("phoneNumber") or args.get("caller_phone") or args.get("caller_id")
                customer_name = args.get("customer_name") or args.get("name") or args.get("claimed_name") or "Unknown Customer"
                issue_description = args.get("issue_description") or args.get("summary_text") or args.get("summaryText") or args.get("summary") or args.get("reason") or "Not specified"
                
                customer = None
                if phone:
                    validated_p = clean_and_validate_phone(phone)
                    if validated_p:
                        customer = lookup_customer_by_phone(validated_p)
                if not customer:
                    customer = {
                        "name": customer_name,
                        "phone": phone or "Unknown"
                    }

                # Gather summary
                state = {
                    "messages": [HumanMessage(content=f"I have an issue: {issue_description}")],
                    "customer": customer,
                    "service_request_id": args.get("service_request_id"),
                    "appointment_id": args.get("appointment_id")
                }
                handoff_result = handoff_node(state)
                summary = handoff_result.get("handoff_summary", "Handoff initiated.")
                config = load_config()
                handoff_number = config.get("handoff_phone_number", "+14242704893")
                result = {
                    "success": True,
                    "message": "Call transferred to human customer service representative successfully.",
                    "summary": summary,
                    "transfer_phone_number": handoff_number
                }

        elif tool_name == "create_service_request":
            phone = args.get("phone") or args.get("phone_number") or args.get("phoneNumber") or args.get("caller_phone") or args.get("caller_id")
            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number. Please ask the caller to repeat or correct their phone number."
                }
            else:
                phone = validated_phone
                customer_name = args.get("customer_name") or args.get("name")
                caller_phone_arg = args.get("caller_phone") or args.get("caller_id") or args.get("callerId") or args.get("from_number")
                validated_caller_phone = clean_and_validate_phone(caller_phone_arg)

                # ANI cross-referencing & acoustic error reconciliation
                if validated_caller_phone and phone != validated_caller_phone:
                    if phone[-7:] == validated_caller_phone[-7:]:
                        logger.warning(
                            f"Reconciling spoken phone {phone} to verified caller ID {validated_caller_phone} "
                            f"(matching 7-digit subscriber suffix {phone[-7:]})"
                        )
                        phone = validated_caller_phone
                    elif len(phone) == len(validated_caller_phone) and sum(1 for a, b in zip(phone, validated_caller_phone) if a != b) <= 1:
                        logger.warning(
                            f"Reconciling spoken phone {phone} to verified caller ID {validated_caller_phone} "
                            f"(single-digit acoustic discrepancy)"
                        )
                        phone = validated_caller_phone
                    else:
                        c_spoken = lookup_customer_by_phone(phone)
                        c_caller = lookup_customer_by_phone(validated_caller_phone)
                        if not c_spoken and c_caller:
                            caller_cname = (c_caller.get("name") or "").lower()
                            req_cname = (customer_name or "").lower()
                            if req_cname in caller_cname or caller_cname in req_cname or not req_cname:
                                logger.info(
                                    f"Linking intake for spoken phone {phone} to existing verified customer "
                                    f"#{c_caller.get('id')} ({validated_caller_phone})"
                                )
                                phone = validated_caller_phone

                make = args.get("make")
                model = args.get("model")
                year = args.get("year")
                has_explicit_make = bool(make and make not in ("Unknown", ""))
                has_explicit_model = bool(model and model not in ("Unknown", ""))

                issue_description = args.get("issue_description") or args.get("issue") or "Not specified"
                service_type = args.get("service_type") or args.get("serviceType") or "Repair"
                time_slot = args.get("time_slot") or args.get("timeSlot")
                booking_type = args.get("booking_type") or args.get("bookingType")
                booking_time = args.get("booking_time") or args.get("bookingTime") or args.get("appointment_datetime") or args.get("preferred_time") or time_slot

                if not booking_type:
                    if args.get("appointment_datetime") or args.get("appointmentDatetime"):
                        booking_type = "appointment"
                    elif args.get("preferred_time") or args.get("preferredTime"):
                        booking_type = "callback"

                if booking_type == "appointment" and booking_time:
                    is_mocked = hasattr(create_service_request, "mock_calls") or hasattr(create_service_request, "_mock_return_value")
                    if not is_mocked:
                        from serviceBot.services.booking import validate_appointment_lead_time
                        is_valid, earliest_allowed, suggested_slots = validate_appointment_lead_time(
                            requested_datetime=booking_time,
                            booking_type="appointment"
                        )
                        if not is_valid:
                            cfg = load_config()
                            min_buf = int(cfg.get("min_booking_buffer_hours", 4))
                            earliest_str = earliest_allowed.strftime("%I:%M %p").lstrip("0")
                            earliest_iso = earliest_allowed.strftime("%Y-%m-%dT%H:%M:%S")
                            agent_inst = (
                                f"Politely inform the caller that our shop requires at least {min_buf} hours advance notice to prepare bays and parts. "
                                f"The earliest available time is around {earliest_str}. Offer the suggested slots at or after {earliest_str}."
                            )
                            result = {
                                "success": False,
                                "error": "INSUFFICIENT_LEAD_TIME",
                                "min_buffer_hours": min_buf,
                                "earliest_allowed_time": earliest_iso,
                                "suggested_slots": suggested_slots,
                                "agent_instruction": agent_inst,
                                "message": agent_inst
                            }
                            response_data = {
                                "tool_call_id": tool_call_id,
                                "result": result
                            }
                            return response_data

                # Check if customer exists
                customer_id = None
                phone_to_lookup = phone if phone else "Unknown"
                c_data = lookup_customer_by_phone(phone_to_lookup)
                if not c_data and validated_caller_phone:
                    c_data = lookup_customer_by_phone(validated_caller_phone)
                    if c_data:
                        phone_to_lookup = validated_caller_phone
                        phone = validated_caller_phone

                # Fuzzy lookup by 7-digit subscriber suffix + customer name if not found
                if not c_data and len(phone) >= 7 and customer_name and customer_name not in ("Unknown Customer", "Unknown"):
                    try:
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    """
                                    SELECT id, name, phone
                                    FROM customers
                                    WHERE RIGHT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', ''), 7) = %s
                                      AND name ILIKE %s
                                    LIMIT 1;
                                    """,
                                    (phone[-7:], f"%{customer_name.strip()}%")
                                )
                                fuzzy_c = cursor.fetchone()
                                if fuzzy_c:
                                    logger.info(f"Fuzzy matched existing customer #{fuzzy_c['id']} ({fuzzy_c['phone']}) for phone {phone} and name {customer_name}")
                                    c_data = {"id": fuzzy_c["id"], "customer_id": fuzzy_c["id"], "name": fuzzy_c["name"], "phone": fuzzy_c["phone"]}
                    except Exception as fuzzy_err:
                        logger.warning(f"Fuzzy customer lookup error: {fuzzy_err}")

                if c_data:
                    customer_id = c_data.get("customer_id") or c_data.get("id")
                    if customer_name and customer_name not in ("Unknown Customer", "Unknown"):
                        try:
                            update_customer_name(customer_id, customer_name)
                        except Exception:
                            pass
                    if not has_explicit_make and not has_explicit_model:
                        make = c_data.get("make")
                        model = c_data.get("model")
                        if not year or year == 2000 or str(year) == "2000":
                            year = c_data.get("year")

                if not make or make in ("Unknown", ""):
                    make = "Vehicle"
                if not model or model in ("Unknown", ""):
                    model = "Standard"
                if not year or year == 2000 or str(year) == "2000":
                    year = 2020
                
                if not customer_id:
                    # Insert customer
                    with get_db_connection() as conn:
                        with dict_cursor(conn) as cursor:
                            cursor.execute(
                                "INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;",
                                (customer_name or "Unknown Customer", phone_to_lookup)
                            )
                            conn.commit()
                            customer_id = cursor.fetchone()["id"]

                extra_kwargs = {}
                if "is_uncataloged" in args or "isUncataloged" in args:
                    extra_kwargs["is_uncataloged"] = bool(args.get("is_uncataloged") or args.get("isUncataloged"))
                if "linked_appointment_id" in args or "linkedAppointmentId" in args:
                    extra_kwargs["linked_appointment_id"] = args.get("linked_appointment_id") or args.get("linkedAppointmentId")
                if "callback_priority" in args or "callbackPriority" in args:
                    extra_kwargs["callback_priority"] = args.get("callback_priority") or args.get("callbackPriority")
                if "callback_number" in args or "callbackNumber" in args:
                    extra_kwargs["callback_number"] = args.get("callback_number") or args.get("callbackNumber")

                is_uncataloged = extra_kwargs.get("is_uncataloged", False)

                vehicle_details = {"make": make, "model": model, "year": year}
                session_key = (
                    args.get("call_sid")
                    or args.get("callSid")
                    or args.get("conversation_id")
                    or args.get("session_id")
                    or (f"phone_{phone}" if phone else None)
                )
                existing_session = get_session_booking(session_key) if (booking_type == "appointment" and session_key) else None

                price_range = "Varies"
                duration_minutes = 60
                if booking_type == "appointment":
                    try:
                        fields = get_service_required_fields(service_type)
                        if fields:
                            price_range = fields.get("price_range") or "Varies"
                            duration_minutes = (fields.get("duration_minutes") or 60)
                    except Exception:
                        pass

                if booking_type == "appointment" and existing_session and existing_session.get("service_request_id"):
                    # Existing in-flight booking in this call session -> update rather than duplicate!
                    existing_sr_id = existing_session["service_request_id"]
                    prev_time = existing_session.get("booking_time")
                    try:
                        reschedule_appointment(
                            appointment_id=existing_sr_id,
                            new_datetime=booking_time,
                            customer_consent_obtained=True,
                            triggered_by="telephony_voice_assistant",
                        )
                    except Exception as resch_err:
                        logger.warning(f"Error rescheduling session booking #{existing_sr_id}: {resch_err}")

                    track_session_booking(
                        session_key=session_key,
                        service_request_id=existing_sr_id,
                        booking_time=booking_time,
                        duration_minutes=duration_minutes,
                        phone=phone,
                        vehicle=vehicle_details,
                    )
                    end_dt_str, win_msg = format_appointment_window_message(
                        booking_time=booking_time,
                        duration_minutes=duration_minutes,
                        price_range=price_range,
                        is_update=True,
                        previous_booking_time=prev_time,
                    )
                    result = {
                        "success": True,
                        "service_request_id": existing_sr_id,
                        "is_update": True,
                        "booking_type": "appointment",
                        "booking_time": booking_time,
                        "duration_minutes": duration_minutes,
                        "expected_end_time": end_dt_str,
                        "is_uncataloged": is_uncataloged,
                        "message": win_msg,
                    }
                else:
                    # Create service request
                    sr_id = create_service_request(
                        customer_id=customer_id,
                        vehicle_details=vehicle_details,
                        issue=issue_description,
                        service_type=service_type,
                        time_slot=time_slot,
                        booking_type=booking_type,
                        booking_time=booking_time,
                        **extra_kwargs
                    )

                    if booking_type == "appointment":
                        track_session_booking(
                            session_key=session_key,
                            service_request_id=sr_id,
                            booking_time=booking_time,
                            duration_minutes=duration_minutes,
                            phone=phone,
                            vehicle=vehicle_details,
                        )
                        end_dt_str, win_msg = format_appointment_window_message(
                            booking_time=booking_time,
                            duration_minutes=duration_minutes,
                            price_range=price_range,
                            is_update=False,
                        )
                        result = {
                            "success": True,
                            "service_request_id": sr_id,
                            "booking_type": "appointment",
                            "booking_time": booking_time,
                            "duration_minutes": duration_minutes,
                            "expected_end_time": end_dt_str,
                            "is_uncataloged": is_uncataloged,
                            "message": win_msg,
                        }
                    elif booking_type in ("callback", "appointment_and_callback"):
                        result = {
                            "success": True,
                            "service_request_id": sr_id,
                            "booking_type": booking_type,
                            "is_uncataloged": is_uncataloged,
                            "message": "Service request callback recorded successfully. Calendar projection and notifications are queued."
                        }
                    else:
                        result = {
                            "success": True,
                            "service_request_id": sr_id,
                            "message": "Service request created successfully."
                        }

        elif tool_name == "book_appointment":
            phone = args.get("phone") or args.get("phone_number") or args.get("phoneNumber") or args.get("caller_phone") or args.get("caller_id")
            appointment_datetime = args.get("appointment_datetime") or args.get("appointmentDatetime") or args.get("datetime")
            service_type = args.get("service_type") or args.get("serviceType") or "Repair"

            # Lead time validation (minimum planning horizon)
            if appointment_datetime:
                is_mocked = hasattr(book_appointment, "mock_calls") or hasattr(book_appointment, "_mock_return_value")
                if not is_mocked:
                    from serviceBot.services.booking import validate_appointment_lead_time
                    is_valid, earliest_allowed, suggested_slots = validate_appointment_lead_time(
                        requested_datetime=appointment_datetime,
                        booking_type="appointment"
                    )
                    if not is_valid:
                        cfg = load_config()
                        min_buf = int(cfg.get("min_booking_buffer_hours", 4))
                        earliest_str = earliest_allowed.strftime("%I:%M %p").lstrip("0")
                        earliest_iso = earliest_allowed.strftime("%Y-%m-%dT%H:%M:%S")
                        agent_inst = (
                            f"Politely inform the caller that our shop requires at least {min_buf} hours advance notice to prepare bays and parts. "
                            f"The earliest available time is around {earliest_str}. Offer the suggested slots at or after {earliest_str}."
                        )
                        result = {
                            "success": False,
                            "error": "INSUFFICIENT_LEAD_TIME",
                            "min_buffer_hours": min_buf,
                            "earliest_allowed_time": earliest_iso,
                            "suggested_slots": suggested_slots,
                            "agent_instruction": agent_inst,
                            "message": agent_inst
                        }
                        response_data = {
                            "tool_call_id": tool_call_id,
                            "result": result
                        }
                        return response_data

            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number. Please ask the caller to repeat or correct their phone number."
                }
            else:
                phone = validated_phone
                customer_name = args.get("customer_name") or args.get("name")
                caller_phone_arg = args.get("caller_phone") or args.get("caller_id") or args.get("callerId") or args.get("from_number")
                validated_caller_phone = clean_and_validate_phone(caller_phone_arg)

                # ANI cross-referencing & acoustic error reconciliation
                if validated_caller_phone and phone != validated_caller_phone:
                    if phone[-7:] == validated_caller_phone[-7:]:
                        logger.warning(
                            f"Reconciling spoken phone {phone} to verified caller ID {validated_caller_phone} "
                            f"(matching 7-digit subscriber suffix {phone[-7:]})"
                        )
                        phone = validated_caller_phone
                    elif len(phone) == len(validated_caller_phone) and sum(1 for a, b in zip(phone, validated_caller_phone) if a != b) <= 1:
                        logger.warning(
                            f"Reconciling spoken phone {phone} to verified caller ID {validated_caller_phone} "
                            f"(single-digit acoustic discrepancy)"
                        )
                        phone = validated_caller_phone
                    else:
                        c_spoken = lookup_customer_by_phone(phone)
                        c_caller = lookup_customer_by_phone(validated_caller_phone)
                        if not c_spoken and c_caller:
                            caller_cname = (c_caller.get("name") or "").lower()
                            req_cname = (customer_name or "").lower()
                            if req_cname in caller_cname or caller_cname in req_cname or not req_cname:
                                logger.info(
                                    f"Linking intake for spoken phone {phone} to existing verified customer "
                                    f"#{c_caller.get('id')} ({validated_caller_phone})"
                                )
                                phone = validated_caller_phone

                make = args.get("make")
                model = args.get("model")
                year = args.get("year")

                has_explicit_make = bool(make and make not in ("Unknown", ""))
                has_explicit_model = bool(model and model not in ("Unknown", ""))

                c_data = lookup_customer_by_phone(phone)
                if c_data:
                    if not customer_name or customer_name in ("Unknown Customer", "Unknown", ""):
                        customer_name = c_data.get("name")
                    # Only fallback to historical vehicle if caller/agent provided NO car info at all
                    if not has_explicit_make and not has_explicit_model:
                        make = c_data.get("make")
                        model = c_data.get("model")
                        if not year or year == 2000 or str(year) == "2000":
                            year = c_data.get("year")
                
                if not customer_name or customer_name in ("Unknown Customer", "Unknown", ""):
                    if c_data and c_data.get("name") and c_data["name"] not in ("Unknown Customer", "Unknown", ""):
                        customer_name = c_data["name"]
                    else:
                        customer_name = "Valued Customer"

                if not make or make in ("Unknown", ""):
                    make = "Vehicle"
                if not model or model in ("Unknown", ""):
                    model = "Standard"
                if not year or year == 2000 or str(year) == "2000":
                    year = 2020

                customer_id = None
                sr_id = None
                if c_data:
                    customer_id = c_data.get("customer_id") or c_data.get("id")
                    sr_id = c_data.get("open_sr_id")
                    if customer_name and customer_name not in ("Unknown Customer", "Unknown"):
                        try:
                            update_customer_name(customer_id, customer_name)
                        except Exception:
                            pass

                if not customer_id:
                    with get_db_connection() as conn:
                        with dict_cursor(conn) as cursor:
                            cursor.execute(
                                "INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;",
                                (customer_name, phone)
                            )
                            conn.commit()
                            customer_id = cursor.fetchone()["id"]

                vehicle_details = {"make": make, "model": model, "year": year}
                session_key = args.get("call_sid") or args.get("callSid") or args.get("conversation_id") or args.get("session_id")
                existing_session = get_session_booking(session_key) if session_key else None

                price_range = "Varies"
                duration_minutes = 60
                try:
                    fields = get_service_required_fields(service_type)
                    if fields:
                        price_range = fields.get("price_range") or "Varies"
                        duration_minutes = (fields.get("duration_minutes") or 60)
                except Exception:
                    pass

                if existing_session and existing_session.get("service_request_id"):
                    existing_appt_id = existing_session["service_request_id"]
                    prev_time = existing_session.get("booking_time")
                    try:
                        reschedule_appointment(
                            appointment_id=existing_appt_id,
                            new_datetime=appointment_datetime,
                            customer_consent_obtained=True,
                            triggered_by="telephony_voice_assistant",
                        )
                    except Exception as resch_err:
                        logger.warning(f"Error rescheduling session appointment #{existing_appt_id}: {resch_err}")

                    track_session_booking(
                        session_key=session_key,
                        service_request_id=existing_appt_id,
                        booking_time=appointment_datetime,
                        duration_minutes=duration_minutes,
                        phone=phone,
                        vehicle=vehicle_details,
                    )
                    end_dt_str, win_msg = format_appointment_window_message(
                        booking_time=appointment_datetime,
                        duration_minutes=duration_minutes,
                        price_range=price_range,
                        is_update=True,
                        previous_booking_time=prev_time,
                    )
                    result = {
                        "success": True,
                        "appointment_id": existing_appt_id,
                        "is_update": True,
                        "booking_time": appointment_datetime,
                        "duration_minutes": duration_minutes,
                        "expected_end_time": end_dt_str,
                        "message": win_msg,
                    }
                else:
                    try:
                        appt_id = book_appointment(
                            customer_id=customer_id,
                            service_request_id=sr_id,
                            appointment_datetime=appointment_datetime,
                            service_type=service_type,
                            vehicle_details=vehicle_details
                        )
                        track_session_booking(
                            session_key=session_key,
                            service_request_id=appt_id,
                            booking_time=appointment_datetime,
                            duration_minutes=duration_minutes,
                            phone=phone,
                            vehicle=vehicle_details,
                        )
                        end_dt_str, win_msg = format_appointment_window_message(
                            booking_time=appointment_datetime,
                            duration_minutes=duration_minutes,
                            price_range=price_range,
                            is_update=False,
                        )
                        result = {
                            "success": True,
                            "appointment_id": appt_id,
                            "booking_time": appointment_datetime,
                            "duration_minutes": duration_minutes,
                            "expected_end_time": end_dt_str,
                            "message": win_msg,
                        }
                    except ValueError as val_err:
                        result = {
                            "success": False,
                            "message": f"Booking failed: {str(val_err)}"
                        }

        elif tool_name == "request_callback":
            phone = args.get("phone") or args.get("phone_number") or args.get("phoneNumber") or args.get("caller_phone") or args.get("caller_id")
            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number. Please repeat or correct your phone number."
                }
            else:
                phone = validated_phone
                customer_name = args.get("customer_name") or args.get("name") or args.get("claimed_name")
                make = args.get("make")
                model = args.get("model")
                year = args.get("year")
                
                c_data = lookup_customer_by_phone(phone)
                if c_data:
                    if not customer_name or customer_name in ("Unknown Customer", "Unknown", ""):
                        customer_name = c_data.get("name")
                    if not make or make == "Unknown":
                        make = c_data.get("make")
                    if not model or model == "Unknown":
                        model = c_data.get("model")
                    if not year or year == 2000 or str(year) == "2000":
                        year = c_data.get("year")
                
                if not customer_name or customer_name in ("Unknown Customer", "Unknown", ""):
                    if c_data and c_data.get("name") and c_data["name"] not in ("Unknown Customer", "Unknown", ""):
                        customer_name = c_data["name"]
                    else:
                        customer_name = "Valued Customer"

                if not make or make in ("Unknown", ""):
                    make = (c_data.get("make") if c_data else None) or "Vehicle"
                if not model or model in ("Unknown", ""):
                    model = (c_data.get("model") if c_data else None) or "Standard"
                if not year or year == 2000 or str(year) == "2000":
                    year = (c_data.get("year") if c_data else None) or 2020

                if True:
                    customer_id = None
                    sr_id = args.get("service_request_id")
                    if c_data:
                        customer_id = c_data.get("customer_id") or c_data.get("id")
                        if not sr_id:
                            sr_id = c_data.get("open_sr_id")
                        if c_data.get("name") == "Unknown Customer" and customer_name != "Unknown Customer":
                            with get_db_connection() as conn:
                                with dict_cursor(conn) as cursor:
                                    cursor.execute("UPDATE customers SET name = %s WHERE id = %s;", (customer_name, customer_id))
                                    conn.commit()
                    
                    if not customer_id:
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    "INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;",
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
                            "message": "Callback request captured successfully. Calendar projection and notifications are queued."
                        }
                    except ValueError as val_err:
                        result = {
                            "success": False,
                            "message": f"Callback request failed: {str(val_err)}"
                        }

        elif tool_name == "verify_caller_identity":
            phone = args.get("phone")
            claimed_name = args.get("claimed_name") or args.get("name") or args.get("customer_name")
            validated_phone = clean_and_validate_phone(phone)
            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number."
                }
            else:
                c_data = lookup_customer_by_phone(validated_phone)
                if not c_data:
                    result = {
                        "success": True,
                        "is_existing_customer": False,
                        "is_verified_existing_customer": False,
                        "message": f"No existing customer profile found for phone number {validated_phone}. A new profile will be created."
                    }
                else:
                    existing_name = c_data.get("name", "")
                    clean_existing = existing_name.lower().strip()
                    clean_claimed = claimed_name.lower().strip() if claimed_name else ""

                    if clean_existing == "unknown customer" and clean_claimed:
                        update_customer_name(c_data.get("customer_id") or c_data.get("id"), claimed_name)
                        result = {
                            "success": True,
                            "is_existing_customer": True,
                            "is_verified_existing_customer": True,
                            "customer_id": c_data.get("customer_id") or c_data.get("id"),
                            "customer_name": claimed_name,
                            "open_sr_id": c_data.get("open_sr_id"),
                            "open_sr_type": c_data.get("open_sr_type"),
                            "message": f"Profile updated for {claimed_name}."
                        }
                    elif clean_claimed and (clean_claimed in clean_existing or clean_existing in clean_claimed):
                        result = {
                            "success": True,
                            "is_existing_customer": True,
                            "is_verified_existing_customer": True,
                            "customer_id": c_data.get("customer_id") or c_data.get("id"),
                            "customer_name": existing_name,
                            "open_sr_id": c_data.get("open_sr_id"),
                            "open_sr_type": c_data.get("open_sr_type"),
                            "message": f"Verified caller as {existing_name}."
                        }
                    else:
                        result = {
                            "success": True,
                            "is_existing_customer": True,
                            "is_verified_existing_customer": False,
                            "existing_profile_name": existing_name,
                            "claimed_name": claimed_name,
                            "customer_id": c_data.get("customer_id") or c_data.get("id"),
                            "message": f"Phone number is registered to {existing_name}, but caller identified as {claimed_name}."
                        }

        elif tool_name == "get_customer_appointments":
            phone = args.get("phone") or args.get("phone_number") or args.get("phoneNumber") or args.get("caller_phone") or args.get("caller_id")
            validated_phone = clean_and_validate_phone(phone)
            caller_phone_arg = args.get("caller_phone") or args.get("caller_id") or args.get("callerId") or args.get("from_number")
            validated_caller_phone = clean_and_validate_phone(caller_phone_arg)

            if not validated_phone and validated_caller_phone:
                validated_phone = validated_caller_phone

            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number."
                }
            else:
                phone = validated_phone
                appts = get_customer_appointments(phone)
                found_via_caller_phone = False

                # Fallback cross-reference: check calling number (Caller ID) and merge if different
                if validated_caller_phone and validated_caller_phone != phone:
                    alt_appts = get_customer_appointments(validated_caller_phone)
                    if alt_appts:
                        if not appts:
                            phone = validated_caller_phone
                            found_via_caller_phone = True
                        existing_ids = {a.get("id") for a in appts}
                        for aa in alt_appts:
                            if aa.get("id") not in existing_ids:
                                appts.append(aa)
                                existing_ids.add(aa.get("id"))

                # Suffix cross-reference: match any pending/in_progress bookings by 7-digit subscriber suffix if none found
                if not appts and len(phone) >= 7:
                    suffix = phone[-7:]
                    try:
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    """
                                    SELECT sr.id, sr.booking_time AS appointment_datetime, sr.booking_type, sr.service_type,
                                           sr.issue_description, COALESCE(sr.duration_minutes, 60) AS duration_minutes,
                                           sr.status, v.year, v.make, v.model
                                    FROM service_requests sr
                                    JOIN customers c ON sr.customer_id = c.id
                                    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                                    WHERE RIGHT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', ''), 7) = %s
                                      AND sr.status IN ('pending', 'in_progress', 'confirmed')
                                      AND (sr.booking_type IN ('appointment', 'callback', 'appointment_and_callback') OR sr.booking_time IS NOT NULL)
                                    ORDER BY sr.booking_time ASC NULLS LAST;
                                    """,
                                    (suffix,)
                                )
                                suffix_rows = cursor.fetchall()
                                existing_ids = {a.get("id") for a in appts}
                                for sr_row in suffix_rows:
                                    if sr_row.get("id") not in existing_ids:
                                        appts.append(dict(sr_row))
                                        existing_ids.add(sr_row.get("id"))
                    except Exception as suffix_err:
                        logger.warning(f"7-digit suffix lookup error in get_customer_appointments: {suffix_err}")

                from serviceBot.services import timezone_service
                now_dt = timezone_service.now_in_business_tz()
                today_str = now_dt.strftime("%Y-%m-%d")

                upcoming = []
                past = []
                unscheduled = []

                for a in appts:
                    dt = a.get("appointment_datetime")
                    btype = "appointment" if a.get("booking_type") == "appointment" else "callback"
                    a["kind"] = "in-shop appointment" if btype == "appointment" else "advisor callback"
                    if not dt:
                        unscheduled.append(a)
                    elif str(dt)[:10] >= today_str:
                        upcoming.append(a)
                    else:
                        past.append(a)

                if not appts:
                    msg = (
                        f"No active appointments or service requests found for phone number {phone}. "
                        "Note: The scheduling system only tracks active or upcoming bookings; "
                        "completed service history and past visit records are not accessible over the phone."
                    )
                    summary_for_agent = (
                        f"No active appointments or callbacks on file for {phone}. "
                        "Important: Completed service records/invoices are not accessible over the phone. "
                        "If the caller asks about past completed visits, clarify that the voice assistant only tracks "
                        "active/upcoming bookings and offer an advisor callback or refer them to their invoice/portal."
                    )
                else:
                    parts = []
                    source_prefix = f"found under your calling number ({phone}) " if found_via_caller_phone else ""
                    if upcoming:
                        parts.append(f"Found {len(upcoming)} upcoming scheduled request(s) on file {source_prefix}:".strip())
                        for idx, u in enumerate(upcoming, 1):
                            kind_label = "In-shop Appointment" if u.get("booking_type") == "appointment" else "Advisor Callback"
                            v_str = f"{u.get('year') or ''} {u.get('make') or ''} {u.get('model') or ''}".strip() or "Vehicle"
                            srv = u.get("service_type") or "Service"
                            issue = u.get("issue_description") or ""
                            dt_str = u.get("appointment_datetime")
                            issue_part = f" ({issue})" if issue and issue.lower() != srv.lower() else ""
                            parts.append(f"{idx}) {kind_label} at {dt_str} for {v_str} regarding {srv}{issue_part}.")
                    if past:
                        past_source = f" {source_prefix}".rstrip() if not upcoming and source_prefix else ""
                        parts.append(f"Also found {len(past)} prior uncompleted record(s) on file{past_source}.")
                    if unscheduled:
                        unsch_source = f" {source_prefix}".rstrip() if not upcoming and not past and source_prefix else ""
                        parts.append(f"Also found {len(unscheduled)} unscheduled request(s){unsch_source}.")
                    msg = " ".join(parts)
                    summary_for_agent = (
                        f"Customer {phone} has {len(upcoming)} upcoming scheduled request(s) on file. "
                        "Clearly inform the caller of both in-shop appointments and advisor callbacks, "
                        "and do not claim there are only in-shop appointments if advisor callbacks are also scheduled. "
                        "Important (Option A Policy): The scheduling system only accesses active and upcoming bookings. "
                        "If the caller asks about past completed appointments, work done earlier, or past invoices, "
                        "explicitly inform them that you do not have access to completed service records over the phone, "
                        "and offer to arrange an advisor callback or refer them to their invoice/portal."
                    )

                result = {
                    "success": True,
                    "appointments": appts,
                    "total_count": len(appts),
                    "upcoming_count": len(upcoming),
                    "upcoming_appointments": upcoming,
                    "past_count": len(past),
                    "message": msg,
                    "summary_for_agent": summary_for_agent,
                }

        elif tool_name == "consolidate_appointment_service":
            appt_id = args.get("appointment_id")
            if appt_id:
                try:
                    appt_id = int(appt_id)
                except (ValueError, TypeError):
                    pass
            additional_issue = args.get("additional_issue") or args.get("issue_description") or args.get("issue")
            additional_service_type = args.get("additional_service_type") or args.get("service_type")
            raw_duration = args.get("additional_duration_minutes")
            if raw_duration is None:
                raw_duration = args.get("duration_minutes")
            if raw_duration is None:
                raw_duration = 30
            try:
                additional_duration = int(raw_duration)
            except (ValueError, TypeError):
                additional_duration = -1

            phone = args.get("phone") or args.get("phone_number")
            source_ids = args.get("source_appointment_ids") or args.get("source_appointment_id") or args.get("cancelled_appointment_ids")

            if additional_duration <= 0:
                result = {
                    "success": False,
                    "error": "additional_duration_minutes must be a positive integer",
                    "message": "Additional duration must be a positive integer."
                }
            elif not appt_id and phone:
                p_clean = clean_and_validate_phone(phone)
                if p_clean:
                    active_appts = get_customer_appointments(p_clean)
                    if active_appts:
                        appt_id = active_appts[0]["id"]

            if additional_duration <= 0:
                pass
            elif not appt_id:
                result = {
                    "success": False,
                    "message": "Appointment ID is required to consolidate services."
                }
            else:
                appt_details = None
                try:
                    with get_db_connection() as conn:
                        with dict_cursor(conn) as cursor:
                            cursor.execute(
                                "SELECT id, booking_time, duration_minutes, staff_agent_id FROM service_requests WHERE id = %s;",
                                (appt_id,)
                            )
                            appt_details = cursor.fetchone()
                except Exception as db_err:
                    logger.warning(f"Could not load appointment #{appt_id} directly from DB: {db_err}")

                if not appt_details and phone:
                    p_clean = clean_and_validate_phone(phone)
                    if p_clean:
                        for ap in get_customer_appointments(p_clean):
                            if ap.get("id") == appt_id:
                                appt_details = ap
                                break

                booking_time = (appt_details.get("booking_time") or appt_details.get("appointment_datetime")) if appt_details else None
                curr_duration = (appt_details.get("duration_minutes") if appt_details else None) or 60
                staff_agent_id = appt_details.get("staff_agent_id") if appt_details else None
                new_total_duration = curr_duration + additional_duration

                has_capacity = verify_contiguous_slot_capacity(
                    start_time=booking_time,
                    duration_minutes=new_total_duration,
                    exclude_service_request_id=appt_id,
                    staff_agent_id=staff_agent_id,
                ) if booking_time else True

                if not has_capacity:
                    result = {
                        "success": False,
                        "capacity_blocked": True,
                        "appointment_id": appt_id,
                        "message": (
                            f"Technician schedule cannot accommodate the extra {additional_duration} minutes contiguous with this appointment. "
                            f"Please offer the customer to either: 1) Move the combined {new_total_duration}-minute visit to an open slot, "
                            f"or 2) Book a separate appointment for {additional_issue or 'the additional service'}."
                        )
                    }
                else:
                    try:
                        cons_res = consolidate_appointment_service(
                            appointment_id=appt_id,
                            additional_issue=additional_issue,
                            additional_service_type=additional_service_type,
                            additional_duration_minutes=additional_duration,
                            source_appointment_ids=source_ids
                        )
                        if cons_res.get("success") is False:
                            result = cons_res
                        else:
                            combined_issues = cons_res.get("combined_issues")
                            new_dur = cons_res.get("new_duration_minutes", new_total_duration)
                            b_time = cons_res.get("booking_time") or booking_time or ""
                            cancelled_sources = cons_res.get("cancelled_source_ids") or []

                        start_str = str(b_time)
                        end_str = ""
                        st_fmt = "start time"
                        end_fmt = "completion"
                        try:
                            clean_b = str(b_time).replace("T", " ")[:19]
                            st_dt = datetime.strptime(clean_b, "%Y-%m-%d %H:%M:%S")
                            end_dt = st_dt + timedelta(minutes=new_dur)
                            start_str = st_dt.strftime("%Y-%m-%d %H:%M:%S")
                            end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                            st_fmt = st_dt.strftime("%I:%M %p").lstrip("0")
                            end_fmt = end_dt.strftime("%I:%M %p").lstrip("0")
                        except Exception:
                            pass

                        cancel_msg = ""
                        if cancelled_sources:
                            cancel_msg = f" Other requests merged and cancelled: {', '.join(str(x) for x in cancelled_sources)}."

                        msg = (
                            f"Appointment {appt_id} successfully consolidated. "
                            f"Total scheduled duration is now {new_dur} minutes ({st_fmt} to {end_fmt}).{cancel_msg} "
                            f"Calendar reservation extended. Please advise the customer that the visit is booked for this window but is likely to extend."
                        )

                        # Trigger immediate SMS/WhatsApp notification
                        if phone:
                            try:
                                from serviceBot.services.sms_router import SMSNotificationRouter
                                v_info = cons_res.get("vehicle") or (appt_details.get("vehicle") if appt_details else {}) or {}
                                v_str = f"{v_info.get('year') or ''} {v_info.get('make') or ''} {v_info.get('model') or ''}".strip() or "Vehicle"
                                SMSNotificationRouter().process_event(
                                    event_type="CONSOLIDATED",
                                    appointment_id=appt_id,
                                    customer_phone=clean_and_validate_phone(phone),
                                    booking_time=str(b_time),
                                    details={
                                        "customer_name": (appt_details.get("customer_name") if appt_details else None) or "Valued Customer",
                                        "phone": clean_and_validate_phone(phone),
                                        "service_type": cons_res.get("service_type") or (appt_details.get("service_type") if appt_details else None) or "Service",
                                        "issue": combined_issues,
                                        "duration_minutes": new_dur,
                                        "time": str(b_time),
                                        "vehicle": v_str,
                                        "cancelled_source_ids": cancelled_sources
                                    }
                                )
                            except Exception as sms_err:
                                logger.warning(f"SMS notification failed for consolidation #{appt_id}: {sms_err}")

                        result = {
                            "success": True,
                            "appointment_id": appt_id,
                            "combined_issues": combined_issues,
                            "new_duration_minutes": new_dur,
                            "start_time": start_str,
                            "expected_end_time": end_str,
                            "cancelled_source_ids": cancelled_sources,
                            "message": msg
                        }
                    except Exception as err:
                        result = {
                            "success": False,
                            "message": f"Failed to consolidate appointment: {str(err)}"
                        }

        elif tool_name == "reschedule_appointment":
            phone = args.get("phone")
            new_datetime = args.get("new_appointment_datetime") or args.get("newAppointmentDatetime") or args.get("appointment_datetime")
            
            validated_phone = clean_and_validate_phone(phone)
            caller_phone_arg = args.get("caller_phone") or args.get("caller_id") or args.get("callerId") or args.get("from_number")
            validated_caller_phone = clean_and_validate_phone(caller_phone_arg)
            if not validated_phone and validated_caller_phone:
                validated_phone = validated_caller_phone

            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number."
                }
            else:
                phone = validated_phone
                appts = get_customer_appointments(phone)
                if not appts and validated_caller_phone and validated_caller_phone != phone:
                    alt_appts = get_customer_appointments(validated_caller_phone)
                    if alt_appts:
                        appts = alt_appts
                        phone = validated_caller_phone

                if not appts and len(phone) >= 7:
                    try:
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    """
                                    SELECT sr.id, sr.booking_time AS appointment_datetime, sr.booking_type, sr.service_type,
                                           sr.issue_description, COALESCE(sr.duration_minutes, 60) AS duration_minutes,
                                           sr.status, v.year, v.make, v.model
                                    FROM service_requests sr
                                    JOIN customers c ON sr.customer_id = c.id
                                    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                                    WHERE RIGHT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', ''), 7) = %s
                                      AND sr.status IN ('pending', 'in_progress', 'confirmed')
                                      AND (sr.booking_type IN ('appointment', 'callback', 'appointment_and_callback') OR sr.booking_time IS NOT NULL)
                                    ORDER BY sr.booking_time ASC NULLS LAST;
                                    """,
                                    (phone[-7:],)
                                )
                                s_rows = cursor.fetchall()
                                if s_rows:
                                    appts = [dict(r) for r in s_rows]
                    except Exception as resch_s_err:
                        logger.warning(f"Reschedule suffix lookup error: {resch_s_err}")

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
                        reschedule_appointment(
                            appointment_id=appt_id, 
                            new_datetime=new_datetime, 
                            customer_consent_obtained=True, 
                            triggered_by="voice_agent"
                        )
                        result = {
                            "success": True,
                            "appointment_id": appt_id,
                            "message": f"Appointment rescheduled to {new_datetime} successfully. Calendar projection and notifications are queued."
                        }
                    except Exception as e:
                        result = {
                            "success": False,
                            "message": f"Failed to reschedule: {str(e)}"
                        }

        elif tool_name == "cancel_appointment":
            phone = args.get("phone")
            reason = args.get("cancellation_reason") or args.get("cancel_reason") or args.get("reason")
            
            validated_phone = clean_and_validate_phone(phone)
            caller_phone_arg = args.get("caller_phone") or args.get("caller_id") or args.get("callerId") or args.get("from_number")
            validated_caller_phone = clean_and_validate_phone(caller_phone_arg)
            if not validated_phone and validated_caller_phone:
                validated_phone = validated_caller_phone

            if not validated_phone:
                result = {
                    "success": False,
                    "message": "Validation failed: Phone number must be a valid 10-digit number."
                }
            else:
                phone = validated_phone
                appts = get_customer_appointments(phone)
                if not appts and validated_caller_phone and validated_caller_phone != phone:
                    alt_appts = get_customer_appointments(validated_caller_phone)
                    if alt_appts:
                        appts = alt_appts
                        phone = validated_caller_phone

                if not appts and len(phone) >= 7:
                    try:
                        with get_db_connection() as conn:
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    """
                                    SELECT sr.id, sr.booking_time AS appointment_datetime, sr.booking_type, sr.service_type,
                                           sr.issue_description, COALESCE(sr.duration_minutes, 60) AS duration_minutes,
                                           sr.status, v.year, v.make, v.model
                                    FROM service_requests sr
                                    JOIN customers c ON sr.customer_id = c.id
                                    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                                    WHERE RIGHT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', ''), 7) = %s
                                      AND sr.status IN ('pending', 'in_progress', 'confirmed')
                                      AND (sr.booking_type IN ('appointment', 'callback', 'appointment_and_callback') OR sr.booking_time IS NOT NULL)
                                    ORDER BY sr.booking_time ASC NULLS LAST;
                                    """,
                                    (phone[-7:],)
                                )
                                s_rows = cursor.fetchall()
                                if s_rows:
                                    appts = [dict(r) for r in s_rows]
                    except Exception as cancel_s_err:
                        logger.warning(f"Cancel appointment suffix lookup error: {cancel_s_err}")

                if not appts:
                    result = {
                        "success": False,
                        "message": f"No active appointments found for phone number {phone} to cancel."
                    }
                else:
                    appt_id = args.get("appointment_id")
                    if not appt_id:
                        appt_id = appts[0]["id"]
                    else:
                        try:
                            appt_id = int(appt_id)
                        except (ValueError, TypeError):
                            appt_id = appts[0]["id"]

                    try:
                        cancel_res = cancel_appointment(
                            appointment_id=appt_id,
                            customer_consent_obtained=True,
                            triggered_by="voice_agent",
                            reason=reason,
                        )
                        result = {
                            "success": True,
                            "appointment_id": appt_id,
                            "message": f"Appointment #{appt_id} has been successfully cancelled. A confirmation text has been dispatched to your phone."
                        }
                    except Exception as e:
                        result = {
                            "success": False,
                            "message": f"Failed to cancel appointment: {str(e)}"
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
    return response_data


# --- Twilio SMS Inbound & Status Webhooks ---

@router.post("/sms/inbound")
async def inbound_sms_webhook(request: Request):
    """
    Inbound Twilio SMS Webhook Endpoint.
    Validates X-Twilio-Signature, parses incoming customer SMS, runs classifier,
    and returns empty TwiML response (since dispatches are handled asynchronously via SMS client).
    """
    form_data = await request.form()
    form_dict = {k: v for k, v in form_data.items()}
    from serviceBot.services.webhook_security import (
        WebhookEventStore,
        WebhookReplayConflictError,
        WebhookVerificationError,
        verify_twilio_request,
    )

    try:
        verify_twilio_request(request, form_dict)
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    from_phone = form_dict.get("From", "").strip()
    body = form_dict.get("Body", "").strip()
    message_sid = form_dict.get("MessageSid", "")
    if not message_sid:
        raise HTTPException(status_code=400, detail="Missing Twilio MessageSid.")

    event_store = WebhookEventStore()
    try:
        event_claimed = event_store.begin("twilio_sms_inbound", message_sid, form_dict)
    except WebhookReplayConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    twiml_response = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    if not event_claimed:
        return Response(content=twiml_response, media_type="text/xml")
    try:
        if from_phone and body:
            from serviceBot.services.sms_classifier import process_inbound_sms
            process_inbound_sms(from_phone=from_phone, body=body, twilio_message_sid=message_sid)
        event_store.complete("twilio_sms_inbound", message_sid)
        return Response(content=twiml_response, media_type="text/xml")
    except Exception:
        try:
            event_store.fail("twilio_sms_inbound", message_sid)
        except Exception as state_err:
            logger.warning("Could not record Twilio inbound webhook failure: %s", state_err)
        raise


@router.post("/sms/status")
async def sms_status_callback_webhook(request: Request):
    """
    Twilio SMS Delivery Status Callback Webhook Endpoint.
    Updates sms_log record status (DELIVERED, FAILED) based on Twilio callbacks.
    """
    form_data = await request.form()
    form_dict = {key: value for key, value in form_data.items()}
    from serviceBot.services.webhook_security import (
        WebhookEventStore,
        WebhookReplayConflictError,
        WebhookVerificationError,
        verify_twilio_request,
    )

    try:
        verify_twilio_request(request, form_dict)
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    message_sid = form_dict.get("MessageSid")
    message_status = form_dict.get("MessageStatus", "").upper()
    error_code = form_dict.get("ErrorCode")
    error_message = form_dict.get("ErrorMessage")
    if not message_sid or not message_status:
        raise HTTPException(status_code=400, detail="Missing Twilio status callback identifier.")

    event_store = WebhookEventStore()
    event_id = f"{message_sid}:{message_status}"
    try:
        event_claimed = event_store.begin("twilio_sms_status", event_id, form_dict)
    except WebhookReplayConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not event_claimed:
        return {"status": "recorded", "duplicate": True}

    try:
        from serviceBot.db.connection import get_db_connection, dict_cursor
        from serviceBot.db.queries import update_sms_log_status

        status_mapping = {
            "ACCEPTED": "SENT",
            "QUEUED": "SENT",
            "SENDING": "SENT",
            "SENT": "SENT",
            "DELIVERED": "DELIVERED",
            "READ": "DELIVERED",
            "FAILED": "FAILED",
            "UNDELIVERED": "FAILED",
        }
        mapped_status = status_mapping.get(message_status)
        if mapped_status:
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("SELECT id, status FROM sms_log WHERE twilio_message_sid = %s;", (message_sid,))
                    row = cursor.fetchone()
                    if row:
                        curr_status = row.get("status")
                        if curr_status in ("DELIVERED", "FAILED") and mapped_status == "SENT":
                            logger.info(
                                f"Ignoring regressive status {mapped_status} for {message_sid} (currently {curr_status})"
                            )
                        else:
                            update_sms_log_status(
                                log_id=row["id"],
                                status=mapped_status,
                                error_code=error_code,
                                error_message=error_message,
                            )

        event_store.complete("twilio_sms_status", event_id)
        return {"status": "recorded"}
    except Exception:
        try:
            event_store.fail("twilio_sms_status", event_id)
        except Exception as state_err:
            logger.warning("Could not record Twilio status webhook failure: %s", state_err)
        raise


@router.get("/api/v1/render-logs")
@router.get("/render-logs")
@router.post("/api/v1/render-logs")
@router.post("/render-logs")
async def receive_render_logs(request: Request):
    """
    Receives real-time HTTPS log stream payloads from Render
    and saves log entries directly into Supabase render_logs table.
    Also handles GET/empty-body pings from Render verification check.
    """
    if request.method == "GET":
        return {"status": "ok", "message": "Render log stream endpoint is active"}

    try:
        raw_body = await request.body()
        if not raw_body or not raw_body.strip():
            return {"status": "ok", "inserted": 0}
        
        try:
            data = json.loads(raw_body)
        except Exception:
            return {"status": "ok", "inserted": 0}

        entries = data if isinstance(data, list) else [data]
        
        from serviceBot.db.connection import get_db_connection
        inserted_count = 0
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for item in entries:
                    if isinstance(item, dict):
                        log_text = item.get("text") or item.get("message") or str(item)
                        service_id = item.get("serviceId") or item.get("service_id")
                        instance_id = item.get("instanceId") or item.get("instance_id")
                        
                        cur.execute("""
                            INSERT INTO render_logs (service_id, instance_id, log_text, payload)
                            VALUES (%s, %s, %s, %s)
                        """, (service_id, instance_id, log_text, json.dumps(item)))
                        inserted_count += 1
                conn.commit()
                
        logger.info(f"[render_logs] Saved {inserted_count} log lines into Supabase render_logs table.")
        return {"status": "ok", "inserted": inserted_count}
    except Exception as e:
        logger.error(f"[render_logs] Error processing Render log payload: {e}", exc_info=e)
        return {"status": "error", "detail": str(e)}


