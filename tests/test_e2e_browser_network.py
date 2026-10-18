"""Exercise the real browser route policy without any browser or provider traffic."""

import struct
import zlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from e2e.browser_network import route_offline_browser_request


def route_for(url):
    route = MagicMock()
    route.request = SimpleNamespace(url=url)
    return route


def test_offline_qr_gateway_is_captured_before_redirect():
    route = route_for("http://127.0.0.1:54321/api/v1/portal/twilio/qr-code?data=https%3A%2F%2Fwa.me%2F15550100001")
    route_offline_browser_request(route)
    route.continue_.assert_not_called()
    route.abort.assert_not_called()
    route.fulfill.assert_called_once()
    response = route.fulfill.call_args.kwargs
    assert response["status"] == 200
    assert response["content_type"] == "image/png"
    body = response["body"]
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", body[16:24]) == (1, 1)
    position = 8
    image_data = b""
    while position < len(body):
        length = struct.unpack(">I", body[position:position + 4])[0]
        chunk = body[position + 4:position + 8 + length]
        checksum = struct.unpack(">I", body[position + 8 + length:position + 12 + length])[0]
        assert zlib.crc32(chunk) == checksum
        if chunk[:4] == b"IDAT":
            image_data += chunk[4:]
        position += length + 12
    assert zlib.decompress(image_data)


@pytest.mark.parametrize("path", ["/portal/", "/api/v1/portal/agents", "/api/v1/portal/config", "/api/v1/portal/twilio/sandbox-info"])
def test_offline_browser_keeps_ordinary_loopback_requests_native(path):
    route = route_for(f"http://127.0.0.1:54321{path}")
    route_offline_browser_request(route)
    route.continue_.assert_called_once_with()
    route.fulfill.assert_not_called()
    route.abort.assert_not_called()


@pytest.mark.parametrize("url", ["https://api.qrserver.com/v1/create-qr-code/?data=synthetic", "https://fonts.googleapis.com/css2", "https://127.0.0.1.example.test/api/v1/portal/twilio/qr-code"])
def test_offline_browser_aborts_external_requests(url):
    route = route_for(url)
    route_offline_browser_request(route)
    route.abort.assert_called_once_with()
    route.fulfill.assert_not_called()
    route.continue_.assert_not_called()
