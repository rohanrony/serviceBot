import os
import sys
import logging
import json
import time
import functools
import inspect
import re
from contextvars import ContextVar
from typing import Optional, Dict, Any, Callable

# Context variable to hold current HTTP request ID across async/sync execution
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

def get_request_id() -> str:
    return request_id_var.get()

def set_request_id(req_id: str):
    request_id_var.set(req_id)


def mask_pii_data(val: Any) -> Any:
    """
    Sanitizes phone numbers, passwords, secrets, and authorization tokens in log outputs.
    """
    if isinstance(val, str):
        # Mask E.164 phone numbers (e.g. +15551234567 -> +1555***4567)
        val = re.sub(r'(\+\d{1,3}\d{3})\d{3,4}(\d{4})', r'\1***\2', val)
        # Mask secrets / tokens / passwords
        if any(sec in val.lower() for sec in ["bearer ", "sk-", "key-", "token=", "password="]):
            return "[SENSITIVE_DATA_MASKED]"
        return val
    elif isinstance(val, dict):
        masked_dict = {}
        for k, v in val.items():
            if any(sec in k.lower() for sec in ["password", "token", "secret", "api_key", "auth"]):
                masked_dict[k] = "[MASKED]"
            else:
                masked_dict[k] = mask_pii_data(v)
        return masked_dict
    elif isinstance(val, (list, tuple)):
        return [mask_pii_data(item) for item in val]
    return val


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON Log Formatter for cloud execution (Vercel, Render, Better Stack, GCP Cloud Run).
    Formats log records into structured JSON objects.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt or "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
            "module": record.module,
            "funcName": record.funcName,
            "lineNo": record.lineno,
        }

        # Include exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                "message": str(record.exc_info[1]),
                "stack": self.formatException(record.exc_info),
            }

        # Include extra dictionary payload if user provided extra={...}
        if hasattr(record, "extra_payload") and isinstance(record.extra_payload, dict):
            log_data.update(mask_pii_data(record.extra_payload))

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """
    Human-readable colored formatter for local terminal CLI development.
    """
    COLORS = {
        "DEBUG": "\033[0;36m",    # Cyan
        "INFO": "\033[0;32m",     # Green
        "WARNING": "\033[0;33m",  # Yellow
        "ERROR": "\033[0;31m",    # Red
        "CRITICAL": "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        req_id = get_request_id()
        req_str = f" [{req_id}]" if req_id and req_id != "-" else ""
        time_str = self.formatTime(record, "%H:%M:%S")
        
        msg = f"{time_str} {color}{record.levelname:<7}{self.RESET} [{record.name}]{req_str} {record.getMessage()}"
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"
            
        return msg


def setup_logging(
    level: Optional[str] = None,
    log_format: Optional[str] = None,
    betterstack_token: Optional[str] = None
) -> logging.Logger:
    """
    Configures and initializes root logger for serviceBot.
    """
    level_str = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, level_str, logging.INFO)

    fmt_choice = (log_format or os.getenv("LOG_FORMAT", "console")).lower()
    token = betterstack_token or os.getenv("BETTERSTACK_SOURCE_TOKEN") or os.getenv("LOGTAIL_SOURCE_TOKEN")

    root_logger = logging.getLogger("serviceBot")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # Console / stdout handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(log_level)

    if fmt_choice == "json":
        stream_handler.setFormatter(StructuredJsonFormatter())
    else:
        stream_handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(stream_handler)

    # Optional Better Stack Logtail Handler
    if token:
        try:
            from logtail import LogtailHandler
            logtail_handler = LogtailHandler(source_token=token)
            logtail_handler.setLevel(log_level)
            if fmt_choice == "json":
                logtail_handler.setFormatter(StructuredJsonFormatter())
            root_logger.addHandler(logtail_handler)
            root_logger.info("Better Stack (Logtail) logger integration enabled successfully.")
        except Exception as err:
            root_logger.warning(f"Could not initialize LogtailHandler for Better Stack: {err}")

    # Silence noisy 3rd party logs by default unless DEBUG
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("chromadb").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str = "serviceBot") -> logging.Logger:
    """
    Returns a child logger under serviceBot namespace.
    """
    if not name.startswith("serviceBot"):
        logger_name = f"serviceBot.{name}"
    else:
        logger_name = name
    return logging.getLogger(logger_name)


def log_execution(module_name: Optional[str] = None, re_raise: bool = True):
    """
    Decorator to wrap any function with defensive error handling and duration logging.
    """
    def decorator(func: Callable):
        target_logger = get_logger(module_name or func.__module__)

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                func_name = func.__name__
                try:
                    res = await func(*args, **kwargs)
                    duration_ms = round((time.time() - start_time) * 1000, 2)
                    target_logger.debug(
                        f"Function {func_name} executed successfully ({duration_ms}ms).",
                        extra={"extra_payload": {"func": func_name, "duration_ms": duration_ms}}
                    )
                    return res
                except Exception as exc:
                    duration_ms = round((time.time() - start_time) * 1000, 2)
                    target_logger.error(
                        f"Exception in function {func_name} ({duration_ms}ms): {exc}",
                        exc_info=exc,
                        extra={"extra_payload": {"func": func_name, "duration_ms": duration_ms}}
                    )
                    if re_raise:
                        raise
                    return None
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                func_name = func.__name__
                try:
                    res = func(*args, **kwargs)
                    duration_ms = round((time.time() - start_time) * 1000, 2)
                    target_logger.debug(
                        f"Function {func_name} executed successfully ({duration_ms}ms).",
                        extra={"extra_payload": {"func": func_name, "duration_ms": duration_ms}}
                    )
                    return res
                except Exception as exc:
                    duration_ms = round((time.time() - start_time) * 1000, 2)
                    target_logger.error(
                        f"Exception in function {func_name} ({duration_ms}ms): {exc}",
                        exc_info=exc,
                        extra={"extra_payload": {"func": func_name, "duration_ms": duration_ms}}
                    )
                    if re_raise:
                        raise
                    return None
            return sync_wrapper
    return decorator


# Default root setup on import
logger = setup_logging()
