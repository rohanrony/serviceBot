"""Business identity and intake contracts shared by portal and voice adapters."""

import json
import math
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter, field_validator


def prefix_business_name(message: str, config: dict) -> str:
    """Prefix a customer notification with a valid configured business name."""
    name = (config or {}).get("business_name")
    if not isinstance(name, str) or not name.strip():
        return message
    return f"{name.strip()}\n{message}"


class IntakeField(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "number"] = "text"
    required: bool = False


class BusinessProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    industry: str = Field(default="Service business", min_length=1, max_length=100)
    collect_vehicle_details: bool = True
    intake_fields: list[IntakeField] = Field(default_factory=list, max_length=20)

    @field_validator("intake_fields")
    @classmethod
    def unique_keys(cls, fields):
        keys = [field.key for field in fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Intake field keys must be unique")
        return fields


def get_business_profile(config=None) -> dict:
    if config is None:
        from serviceBot.api.portal import load_config
        config = load_config()
    return BusinessProfile.model_validate(config.get("business_profile") or {}).model_dump()


def validate_intake_data(data, profile=None) -> dict:
    profile = profile if profile is not None else get_business_profile()
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("Intake details must be an object")
    fields = {field["key"]: field for field in profile["intake_fields"]}
    if data.keys() - fields.keys():
        raise ValueError("Intake details contain an unconfigured field")
    clean = {}
    for key, field in fields.items():
        value = data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if field["required"]:
                raise ValueError(f"{field['label']} is required")
            continue
        if field["type"] == "text":
            if not isinstance(value, str) or len(value) > 2000:
                raise ValueError(f"{field['label']} must be text of at most 2000 characters")
            value = value.strip()
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{field['label']} must be a finite number")
        clean[key] = value
    return clean


def parse_voice_intake(args, profile) -> dict:
    data = args.get("intake_data")
    if data is None and args.get("intake_data_json") is not None:
        try:
            data = json.loads(args["intake_data_json"])
        except (ValueError, TypeError) as exc:
            raise ValueError("Intake details must be valid JSON") from exc
    return validate_intake_data(data, profile)


def build_business_prompt(config) -> tuple[str, str]:
    from serviceBot.services.prompt_service import format_business_schedule

    profile = get_business_profile(config)
    name = config.get("business_name") or "our business"
    schedule = format_business_schedule(config.get("business_hours_start", 7), config.get("business_hours_end", 18),
        config.get("business_days"), config.get("business_timezone"))
    fields = "\n".join(f"- {f['label']} ({f['type']}, {'required' if f['required'] else 'optional'}), key: {f['key']}"
        for f in profile["intake_fields"]) or "No additional intake fields are configured."
    automotive = "Collect vehicle make, model and year when required by the selected service." if profile["collect_vehicle_details"] else ""
    prompt = f"""You are a professional AI voice assistant for {name}, a {profile['industry']} business.
Be friendly, concise, and ask one question at a time. Use Agent for staff members.
Collect and confirm customer name, valid phone number, requested service and a concise issue description.
{automotive}
Configured additional intake:
{fields}
Call get_service_fields before intake. Pass collected configured values as intake_data_json (a JSON object encoded as a string) to create_service_request, book_appointment or request_callback. Never invent values.
Use caller ID only after confirmation. Call get_customer_appointments after confirming the phone number, before scheduling; offer to update an existing visit when appropriate.
Use the service catalog and knowledge base for prices, durations and business information; never invent services or quotes. Review every requested service, quote its rate and duration, and obtain explicit consent before booking.
Business hours: {schedule['days_hyphen']} {schedule['start_str']} - {schedule['end_str']} {schedule['tz_code']}.
Appointments require at least {config.get('min_booking_buffer_hours', 4)} hours advance notice; callbacks require {config.get('min_callback_buffer_hours', 2)} hours. All work must finish before closing.
Check availability for the requested date/time and offer returned options. Never claim unknown capacity is available or loop through unrequested dates.
Finalize all services and times before executing one booking tool during wrap-up. A callback is saved only after its tool succeeds. Never claim booking, rescheduling, cancellation, transfer, or notification delivery without a verified tool result.
For changes, verify appointment ownership and obtain explicit consent. For unsupported requests offer a callback or supported human recovery; never claim a live transfer is configured without evidence.
"""
    greeting = f"Hello! Thank you for calling {name}. I am an AI voice assistant. Please note that this conversation will be recorded. How can I help you today?"
    return prompt, greeting


def build_summary_prompt(config) -> str:
    profile = get_business_profile(config)
    labels = ", ".join(field["label"] for field in profile["intake_fields"])
    automotive = " Include vehicle details where mentioned." if profile["collect_vehicle_details"] else ""
    return (f"Summarize this service call for {config.get('business_name') or 'the business'} ({profile['industry']}) "
        "in 3-4 concise bullet points: requested services, concerns, booking times and relevant context. "
        f"Include configured intake details where mentioned: {labels or 'none'}." + automotive +
        " Do not invent missing details. If no service or booking details were gathered, output exactly: "
        "Call ended before completion; no service details were gathered.")


def format_service_details(record) -> str:
    profile = get_business_profile()
    labels = {field["key"]: field["label"] for field in profile["intake_fields"]}
    legacy = " ".join(str(record[key]) for key in ("year", "make", "model") if record.get(key))
    intake = "; ".join(f"{labels.get(key, key.replace('_', ' '))}: {value}"
        for key, value in (record.get("intake_data") or {}).items())
    return " · ".join(value for value in (legacy, intake) if value) or "N/A"


def normalize_portal_base_url(value: str) -> str:
    if not value.strip():
        return ""
    url = TypeAdapter(AnyHttpUrl).validate_python(value.strip())
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Portal URL must not contain credentials, a query, or a fragment")
    return str(url).rstrip("/")


def notification_portal_url(config) -> str:
    try:
        base = normalize_portal_base_url(config.get("portal_base_url") or "")
    except ValueError:
        return ""
    return f"{base}/portal/#dashboard" if base else ""
