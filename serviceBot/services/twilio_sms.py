import os
import re
from serviceBot.db.queries import (
    get_sms_config,
    is_phone_whitelisted,
    log_sms_dispatch,
    update_sms_log_status,
)
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

    def get_sandbox_credentials(self, role: str = "CUSTOMER", phone_number: str = None) -> dict:
        """Returns configured Twilio WhatsApp Sandbox info and generated wa.me deep links tailored by role."""
        sandbox_number = os.getenv("TWILIO_WHATSAPP_SANDBOX_NUMBER", "+14155238886")
        join_code = os.getenv("TWILIO_WHATSAPP_JOIN_CODE", "join evidence-lips")
        
        # Customize join code label based on role if needed
        clean_role = (role or "CUSTOMER").upper()
        clean_num = re.sub(r"\D", "", sandbox_number)
        from urllib.parse import quote
        encoded_join = quote(join_code) if join_code else "join"
        
        whatsapp_url = f"https://wa.me/{clean_num}?text={encoded_join}"
        qr_code_url = f"/api/v1/portal/twilio/qr-code?data={whatsapp_url}"
        fallback_qr_url = f"https://chart.googleapis.com/chart?chs=200x200&cht=qr&chl={whatsapp_url}"
        
        return {
            "role": clean_role,
            "recipient_phone": phone_number,
            "sandbox_number": sandbox_number,
            "join_code": join_code,
            "whatsapp_url": whatsapp_url,
            "qr_code_url": qr_code_url,
            "fallback_qr_url": fallback_qr_url
        }

    def send_whatsapp(
        self,
        to: str,
        body: str,
        template_type: str = "whatsapp_verification",
        appointment_id: int = None,
        recipient_type: str = "customer",
        dispatch_log_id: int = None,
    ) -> dict:
        """Dispatch a WhatsApp message and persist it as WhatsApp, not SMS."""
        clean_to = to.strip() if to else ""
        if not clean_to.startswith("whatsapp:"):
            clean_to = f"whatsapp:{clean_to}"
        return self.send_sms(
            to=clean_to,
            body=body,
            template_type=template_type,
            appointment_id=appointment_id,
            recipient_type=recipient_type,
            channel="WHATSAPP",
            dispatch_log_id=dispatch_log_id,
        )

    def send_sms(
        self,
        to: str,
        body: str,
        template_type: str = "notification",
        appointment_id: int = None,
        recipient_type: str = "customer",
        channel: str = "SMS",
        dispatch_log_id: int = None,
    ) -> dict:
        """Dispatch one SMS/WhatsApp message and update its durable log state."""
        config = get_sms_config()
        env_mode = (config.get("environment") or os.getenv("ENVIRONMENT") or "PRODUCTION").upper()
        clean_to = to.strip() if to else ""
        normalized_channel = (channel or "SMS").upper()

        # Check if attempting SMS with WhatsApp sandbox from_number
        sandbox_number = os.getenv("TWILIO_WHATSAPP_SANDBOX_NUMBER", "+14155238886").replace("whatsapp:", "").strip()
        from_clean = self.from_number.replace("whatsapp:", "").strip() if self.from_number else ""
        if normalized_channel == "SMS" and not self.messaging_service_sid and from_clean == sandbox_number:
            logger.info("From number matches Twilio WhatsApp Sandbox number; routing dispatch to WHATSAPP.")
            normalized_channel = "WHATSAPP"

        def record(
            status: str,
            *,
            sid: str = None,
            error_code: str = None,
            error_message: str = None,
        ) -> int:
            if dispatch_log_id:
                update_sms_log_status(
                    log_id=dispatch_log_id,
                    status=status,
                    twilio_message_sid=sid,
                    error_code=error_code,
                    error_message=error_message,
                    increment_retry=status == "FAILED",
                )
                return dispatch_log_id
            return log_sms_dispatch(
                appointment_id=appointment_id,
                recipient_type=recipient_type,
                recipient_phone=clean_to,
                template_type=template_type,
                status=status,
                twilio_message_sid=sid,
                error_code=error_code,
                error_message=error_message,
                body=body,
                channel=normalized_channel,
            )

        # Test Whitelist validation in STAGING/TEST environment
        if env_mode in ("STAGING", "TEST") and not is_phone_whitelisted(clean_to):
            log_id = record(
                "SKIPPED_NOT_WHITELISTED",
                error_message="Phone number is not present in test whitelist.",
            )
            return {
                "success": False,
                "status": "SKIPPED_NOT_WHITELISTED",
                "log_id": log_id,
                "channel": normalized_channel,
                "error_message": "Phone number is not whitelisted for staging."
            }

        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

        # In PRODUCTION mode, missing credentials must fail, never mock as SENT
        if env_mode == "PRODUCTION" and (not account_sid or not auth_token):
            log_id = record(
                "FAILED",
                error_message="Missing Twilio credentials in production.",
                error_code="30001",
            )
            return {
                "success": False,
                "status": "FAILED",
                "log_id": log_id,
                "channel": normalized_channel,
                "error_message": "Missing Twilio credentials in production.",
            }

        # Check Twilio credentials & mock execution environment
        is_testing = any(k in os.environ for k in ["PYTEST_CURRENT_TEST", "TESTING"]) or not (account_sid and auth_token)

        if is_testing:
            mock_sid = f"SMmock_{os.urandom(8).hex()}"
            log_id = record("SENT", sid=mock_sid)
            return {
                "success": True,
                "status": "SENT",
                "sid": mock_sid,
                "log_id": log_id,
                "channel": normalized_channel,
            }

        # Real Twilio API Call
        try:
            from twilio.rest import Client
            client = Client(account_sid, auth_token)

            # Handle channel formatting for SMS vs WhatsApp
            target_to = clean_to.replace("whatsapp:", "").strip()

            if normalized_channel == "WHATSAPP":
                digits = re.sub(r"\D", "", target_to)
                if len(digits) == 10:
                    target_to = f"+1{digits}"
                elif len(digits) == 11 and digits.startswith("1"):
                    target_to = f"+{digits}"
                elif not target_to.startswith("+"):
                    target_to = f"+{target_to}"
                if not target_to.startswith("whatsapp:"):
                    target_to = f"whatsapp:{target_to}"

                # WhatsApp requires a registered WhatsApp Sender or the WhatsApp Sandbox number
                whatsapp_from = (
                    os.getenv("TWILIO_WHATSAPP_FROM_NUMBER")
                    or os.getenv("TWILIO_WHATSAPP_SANDBOX_NUMBER")
                    or "+14155238886"
                ).strip()
                if not whatsapp_from.startswith("whatsapp:"):
                    whatsapp_from = f"whatsapp:{whatsapp_from}"
                from_num = whatsapp_from
            else:
                from_num = (self.from_number or "").replace("whatsapp:", "").strip()

            kwargs = {"to": target_to, "body": body}
            if self.messaging_service_sid and normalized_channel != "WHATSAPP":
                kwargs["messaging_service_sid"] = self.messaging_service_sid
            elif from_num:
                kwargs["from_"] = from_num
            else:
                raise ValueError("Neither TWILIO_MESSAGING_SERVICE_SID nor TWILIO_FROM_NUMBER is configured.")

            msg = client.messages.create(**kwargs)
            
            log_id = record("SENT", sid=msg.sid)
            logger.info("Twilio %s dispatched successfully (SID: %s).", normalized_channel, msg.sid)
            return {
                "success": True,
                "status": "SENT",
                "sid": msg.sid,
                "log_id": log_id,
                "channel": normalized_channel,
            }
        except Exception as e:
            error_str = str(e)
            error_code = None
            match = re.search(r"code\s*:\s*(\d+)", error_str, re.IGNORECASE) or re.search(r"\b(\d{5})\b", error_str)
            if match:
                error_code = match.group(1)

            log_id = record("FAILED", error_code=error_code, error_message=error_str)
            logger.error("Twilio %s dispatch failed (code %s): %s", normalized_channel, error_code, error_str, exc_info=e)
            return {
                "success": False,
                "status": "FAILED",
                "error_code": error_code,
                "error_message": error_str,
                "log_id": log_id,
                "channel": normalized_channel,
            }
