import time
import uuid
import traceback
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from serviceBot.logger import get_logger, set_request_id, get_request_id

logger = get_logger("middleware")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to inject X-Request-ID correlation headers and log HTTP access metrics.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate unique request ID
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())[:8]
        set_request_id(req_id)

        start_time = time.time()
        client_host = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method

        try:
            response = await call_next(request)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            # Skip noise for standard static files or health checks unless non-200
            if path in ["/health"] and response.status_code == 200:
                pass
            else:
                logger.info(
                    f"{method} {path} - {response.status_code} ({duration_ms}ms) [{client_host}]",
                    extra={"extra_payload": {
                        "http_method": method,
                        "http_path": path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                        "client_host": client_host
                    }}
                )

            response.headers["X-Request-ID"] = req_id
            return response
        except Exception as exc:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(
                f"Unhandled middleware exception on {method} {path} ({duration_ms}ms): {exc}",
                exc_info=exc,
                extra={"extra_payload": {
                    "http_method": method,
                    "http_path": path,
                    "duration_ms": duration_ms,
                    "client_host": client_host
                }}
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred. Please contact support with the request ID.",
                    "request_id": req_id
                },
                headers={"X-Request-ID": req_id}
            )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global FastAPI exception handler for uncaught application errors.
    """
    req_id = get_request_id()
    method = request.method
    path = request.url.path
    
    logger.error(
        f"Unhandled application exception on {method} {path}: {str(exc)}",
        exc_info=exc,
        extra={"extra_payload": {
            "http_method": method,
            "http_path": path,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }}
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. Please contact support with the request ID.",
            "request_id": req_id
        },
        headers={"X-Request-ID": req_id}
    )
