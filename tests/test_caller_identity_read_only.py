"""Read-only caller identity inspection never changes customer records."""

import asyncio
from unittest.mock import patch

import pytest

from serviceBot.api.telephony import voice_tools


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    """These isolated tool tests use only mocked customer persistence."""
    yield


@pytest.mark.parametrize("existing_name, claimed_name, verified", [
    ("Unknown Customer", "Taylor Test", False),
    ("Taylor Test", "Taylor Test", True),
    ("Taylor Test", "Different Person", False),
    ("Taylor Test", None, False),
])
def test_read_only_returns_recorded_identity_without_updates(existing_name, claimed_name, verified):
    with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value={
        "customer_id": 123, "name": existing_name,
    }), patch("serviceBot.api.telephony.update_customer_name") as update:
        response = asyncio.run(voice_tools({"name": "verify_caller_identity", "arguments": {
            "phone": "+15550100006", "claimed_name": claimed_name, "read_only": True,
        }}))
    result = response["result"]
    assert result["success"] is True
    assert result["is_existing_customer"] is True
    assert result["is_verified_existing_customer"] is verified
    assert result["customer_id"] == 123
    assert result["customer_name"] == existing_name
    assert result["read_only"] is True
    update.assert_not_called()


def test_read_only_missing_customer_does_not_create_or_update_profile():
    with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value=None), \
         patch("serviceBot.api.telephony.update_customer_name") as update:
        result = asyncio.run(voice_tools({"name": "verify_caller_identity", "arguments": {
            "phone": "+15550100006", "read_only": True,
        }}))["result"]
    assert result["is_existing_customer"] is False
    assert result["is_verified_existing_customer"] is False
    assert result["read_only"] is True
    assert "will be created" not in result["message"]
    update.assert_not_called()


def test_ordinary_verification_still_updates_unknown_profile():
    with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value={
        "id": 123, "name": "Unknown Customer",
    }), patch("serviceBot.api.telephony.update_customer_name") as update:
        result = asyncio.run(voice_tools({"name": "verify_caller_identity", "arguments": {
            "phone": "+15550100006", "claimed_name": "Taylor Test",
        }}))["result"]
    assert result["is_verified_existing_customer"] is True
    assert result["customer_name"] == "Taylor Test"
    update.assert_called_once_with(123, "Taylor Test")
