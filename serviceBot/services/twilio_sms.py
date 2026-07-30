import os
import re
from serviceBot.db.queries import get_sms_config, is_phone_whitelisted, log_sms_dispatch
from serviceBot.logger import get_logger

logger = get_logger("services.twilio_sms")

class TwilioSMSClient:
    """
    Twilio SMS dispatch wrapper service.
    Supports dual-mode dispatch:
    - Preferred: TWILIO_MESSAGING_SERVICE_SID (A2P 10DLC compliance, automatic pool)
    - Fallback: TWILIO_FROM_NUMBER (individual number)
    """

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER", "")

    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and (self.messaging_service_sid or self.from_number))

    def get_sandbox_credentials(self) -> dict:
        """Returns configured Twilio WhatsApp Sandbox info and generated wa.me deep links."""
        sandbox_number = os.getenv("TWILIO_WHATSAPP_SANDBOX_NUMBER", "+14155238886")
        join_code = os.getenv("TWILIO_WHATSAPP_JOIN_CODE", "join service-bot")
        
        clean_num = re.sub(r"\D", "", sandbox_number)
        encoded_join = join_code.replace(" ", "%20") if join_code else "join"
        whatsapp_url = f"https://wa.me/{clean_num}?text={encoded_join}"
        qr_code_url = f"https://chart.googleapis.com/chart?chs=200x200&cht=qr&chl={whatsapp_url}"
        
        return {
            "sandbox_number": sandbox_number,
            "join_code": join_code,
            "whatsapp_url": whatsapp_url,
            "qr_code_url": qr_code_url
        }

    def send_whatsapp(self, to: str, body: str, template_type: str = "whatsapp_verification", appointment_id: int = None) -> dict:
        """Dispatches an explicit WhatsApp test/verification message."""
        clean_to = to.strip() if to else ""
        if not clean_to.startswith("whatsapp:"):
            clean_to = f"whatsapp:{clean_to}"
        return self.send_sms(to=clean_to, body=body, template_type=template_type, appointment_id=appointment_id)

    def send_sms(self, to: str, body: str, template_type: str = "notification", appointment_id: int = None) -> dict:
        config = get_sms_config()
        env_mode = (config.get("environment") or os.getenv("ENVIRONMENT") or "PRODUCTION").upper()

        # Clean destination phone
        clean_to = to.strip() if to else ""

        # Test Whitelist validation in STAGING/TEST environment
        if env_mode in ("STAGING", "TEST") and not is_phone_whitelisted(clean_to):
            log_id = log_sms_dispatch(
                appointment_id=appointment_id,
                recipient_type="customer",
                recipient_phone=clean_to,
                template_type=template_type,
                status="SKIPPED_NOT_WHITELISTED",
                error_message="Phone number is not present in test whitelist."
            )
            return {
                "success": False,
                "status": "SKIPPED_NOT_WHITELISTED",
                "log_id": log_id,
                "error_message": "Phone number is not whitelisted for staging."
            }

        # Check Twilio credentials & mock execution environment
        is_testing = any(k in os.environ for k in ["PYTEST_CURRENT_TEST", "TESTING"]) or not (self.account_sid and self.auth_token)

        if is_testing:
            mock_sid = f"SMmock_{os.urandom(8).hex()}"
            log_id = log_sms_dispatch(
                appointment_id=appointment_id,
                recipient_type="customer",
                recipient_phone=clean_to,
                template_type=template_type,
                status="SENT",
                twilio_message_sid=mock_sid
            )
            return {
                "success": True,
                "status": "SENT",
                "sid": mock_sid,
                "log_id": log_id
            }

        # Real Twilio API Call
        try:
            from twilio.rest import Client
            client = Client(self.account_sid, self.auth_token)

            # Handle channel formatting for SMS vs WhatsApp
            target_to = clean_to
            from_num = self.from_number.strip() if self.from_number else ""

            if target_to.startswith("whatsapp:"):
                if from_num and not from_num.startswith("whatsapp:"):
                    from_num = f"whatsapp:{from_num}"
            else:
                from_num = from_num.replace("whatsapp:", "").strip()

            kwargs = {"to": target_to, "body": body}
            if self.messaging_service_sid:
                kwargs["messaging_service_sid"] = self.messaging_service_sid
            elif from_num:
                kwargs["from_"] = from_num
            else:
                raise ValueError("Neither TWILIO_MESSAGING_SERVICE_SID nor TWILIO_FROM_NUMBER is configured.")

            msg = client.messages.create(**kwargs)
            
            log_id = log_sms_dispatch(
                appointment_id=appointment_id,
                recipient_type="customer",
                recipient_phone=clean_to,
                template_type=template_type,
                status="SENT",
                twilio_message_sid=msg.sid
            )
            logger.info(f"Twilio SMS dispatched successfully to {clean_to} (SID: {msg.sid}).")
            return {
                "success": True,
                "status": "SENT",
                "sid": msg.sid,
                "log_id": log_id
            }
        except Exception as e:
            error_str = str(e)
            error_code = None
            match = re.search(r"code\s*:\s*(\d+)", error_str, re.IGNORECASE) or re.search(r"\b(\d{5})\b", error_str)
            if match:
                error_code = match.group(1)

            log_id = log_sms_dispatch(
                appointment_id=appointment_id,
                recipient_type="customer",
                recipient_phone=clean_to,
                template_type=template_type,
                status="FAILED",
                error_code=error_code,
                error_message=error_str
            )
            logger.error(f"Twilio SMS dispatch failed to {clean_to} (code {error_code}): {error_str}", exc_info=e)
            return {
                "success": False,
                "status": "FAILED",
                "error_code": error_code,
                "error_message": error_str,
                "log_id": log_id
            }
