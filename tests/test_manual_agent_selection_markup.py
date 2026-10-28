"""The delivered request form must provide the optional staff-selection control."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


class RequestForm(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.in_request = False
        self.controls = {}
        self.labels = set()
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_request = attrs.get("id") == "sr-form"
        if self.in_request:
            if tag == "select":
                self.controls[attrs.get("id")] = attrs
            elif tag == "label":
                self.labels.add(attrs.get("for"))

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_request = False


class ManualAgentSelectionMarkupTest(unittest.TestCase):
    def test_request_form_has_labeled_optional_staff_selector(self):
        root = Path(__file__).resolve().parents[1]
        form = RequestForm((root / "serviceBot/static/index.html").read_text())
        self.assertIn("sr-agent-select", form.controls)
        self.assertIn("sr-agent-select", form.labels)
        self.assertNotIn("required", form.controls["sr-agent-select"])


if __name__ == "__main__":
    unittest.main()
