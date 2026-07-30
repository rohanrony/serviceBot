import json
import logging
from io import StringIO
from fastapi.testclient import TestClient
from serviceBot.logger import (
    StructuredJsonFormatter,
    ConsoleFormatter,
    set_request_id,
    get_request_id,
    setup_logging,
    get_logger
)
from serviceBot.main import app

def test_request_id_context():
    set_request_id("test-req-123")
    assert get_request_id() == "test-req-123"
    set_request_id("-")

def test_structured_json_formatter():
    set_request_id("req-999")
    formatter = StructuredJsonFormatter()
    logger = logging.getLogger("test_json")
    record = logger.makeRecord(
        name="test_logger",
        level=logging.INFO,
        fn="test_file.py",
        lno=42,
        msg="Test JSON Log Output",
        args=(),
        exc_info=None,
        func="test_func"
    )
    record.extra_payload = {"user_id": 101, "event": "test_event"}
    output = formatter.format(record)
    
    parsed = json.loads(output)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Test JSON Log Output"
    assert parsed["request_id"] == "req-999"
    assert parsed["user_id"] == 101
    assert parsed["event"] == "test_event"
    set_request_id("-")

def test_request_logging_middleware():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    req_id = response.headers["X-Request-ID"]
    assert len(req_id) > 0

def test_global_exception_handler():
    client = TestClient(app, raise_server_exceptions=False)
    
    # Temporarily mount a test endpoint that raises an error
    @app.get("/test-error-endpoint")
    def raise_error():
        raise ValueError("Simulated testing error")

    response = client.get("/test-error-endpoint")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "Internal Server Error"
    assert "request_id" in data
    assert "X-Request-ID" in response.headers
