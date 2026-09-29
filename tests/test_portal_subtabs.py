import os
import re
import pytest
from html.parser import HTMLParser
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from serviceBot.main import app

client = TestClient(app)

INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "index.html")
APP_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "app.js")


class StrictHTMLTagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.void_tags:
            return
        attrs_dict = dict(attrs)
        elem_id = attrs_dict.get('id', '')
        pos = self.getpos()
        self.stack.append((tag.lower(), pos, elem_id))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.void_tags:
            return
        if not self.stack:
            self.errors.append(f"Unexpected closing tag </{tag}> at line {self.getpos()[0]}")
            return
        last_tag, pos, elem_id = self.stack.pop()
        if last_tag != tag:
            self.errors.append(f"Mismatched </{tag}> at line {self.getpos()[0]}, expected </{last_tag}> from line {pos[0]} id='{elem_id}'")


def test_index_html_has_zero_unclosed_tags():
    """Verify that index.html is completely valid HTML with no unclosed or mismatched tags."""
    assert os.path.exists(INDEX_HTML_PATH)
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()

    checker = StrictHTMLTagChecker()
    checker.feed(html_content)

    assert len(checker.errors) == 0, f"HTML parsing errors found: {checker.errors}"
    assert len(checker.stack) == 0, f"Unclosed tags remaining in index.html: {checker.stack}"


def test_all_config_subtabs_are_direct_siblings_not_nested():
    """Verify that all 6 subtabs exist and none are nested inside staff-view."""
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    subtabs = ["staff", "gmail", "sms-config", "customer-onboarding", "intents", "keys"]

    for subtab in subtabs:
        assert f'data-subtab="{subtab}"' in html, f"Ribbon button missing for subtab: {subtab}"
        assert f'data-subtab-pane="{subtab}"' in html, f"Subtab pane missing for subtab: {subtab}"

    # Extract staff-view content boundaries
    staff_start = html.find('id="staff-view"')
    assert staff_start != -1

    # Find where staff-view closes:
    # Before gmail-view starts, staff-view MUST have closed
    gmail_start = html.find('id="gmail-view"')
    assert gmail_start != -1
    assert staff_start < gmail_start

    # Between staff_start and gmail_start, verify that staff-view closing tag exists
    between = html[staff_start:gmail_start]
    # The subtabs must NOT be inside staff-view
    assert 'id="sms-config-view"' not in between
    assert 'id="customer-onboarding-view"' not in between
    assert 'id="intents-view"' not in between
    assert 'id="keys-view"' not in between


def test_enable_agent_selection_checkbox_present_in_index_html():
    """Verify that enable-agent-selection checkbox exists in index.html."""
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="enable-agent-selection"' in html


def test_app_js_load_gmail_config_null_safety():
    """Verify that app.js safely accesses enable-agent-selection with null checks."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    # Must check enableAgentSelectEl existence before reading/setting .checked
    assert "enableAgentSelectEl" in js
    assert "if (enableAgentSelectEl)" in js


def test_portal_gmail_config_endpoint():
    """Test /api/v1/portal/gmail-config endpoint handles enable_agent_selection."""
    mock_config = {
        "gmail_enabled": True,
        "enable_agent_selection": True,
        "gmail_auth_type": "app_password",
        "gmail_sender": "test@example.com",
        "gmail_recipient": "admin@example.com",
        "gmail_password": "encrypted_dummy",
        "is_connected": False,
        "admin_phone_number": "+14242704893"
    }

    with patch("serviceBot.api.portal.load_config", return_value=mock_config), \
         patch("serviceBot.db.queries.get_sms_config", return_value={"admin_phone_number": "+14242704893"}), \
         patch("serviceBot.db.queries.update_sms_config"), \
         patch("serviceBot.api.portal.save_config") as mock_save:
        res = client.get("/api/v1/portal/gmail-config")
        assert res.status_code == 200
        data = res.json()
        assert data["enable_agent_selection"] is True
        assert data["gmail_enabled"] is True

        # Test POST update
        payload = {
            "gmail_enabled": True,
            "enable_agent_selection": False,
            "gmail_auth_type": "app_password",
            "gmail_sender": "test@example.com",
            "gmail_recipient": "admin@example.com"
        }
        post_res = client.post("/api/v1/portal/gmail-config", json=payload)
        assert post_res.status_code == 200
        assert mock_save.called
