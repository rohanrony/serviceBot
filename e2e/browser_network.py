"""Browser transport policy for offline acceptance tests."""

from base64 import b64decode
from urllib.parse import urlparse

# Transparent pixel: provider-boundary test data, never a scannable live QR code.
CAPTURED_QR_IMAGE = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII="
)


def route_offline_browser_request(route):
    url = urlparse(route.request.url)
    if url.hostname != "127.0.0.1":
        route.abort()
    elif url.path == "/api/v1/portal/twilio/qr-code":
        # Capture before the local gateway's redirect can leave loopback.
        route.fulfill(status=200, content_type="image/png", body=CAPTURED_QR_IMAGE)
    else:
        route.continue_()
