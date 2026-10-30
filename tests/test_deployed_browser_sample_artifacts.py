"""A new sample captures a separate screenshot without replacing paid evidence."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from serviceBot.api.auth import COOKIE_NAME
from live_simulations.deployed_medium import Adapter


@pytest.mark.parametrize('sample,filename', [(None, 'C15-portal.png'), (1, 'C15-portal.png'), (2, 'C15-2-portal.png')])
def test_browser_screenshot_is_scoped_to_sample(monkeypatch, tmp_path, sample, filename):
    captured = []
    transferred_cookies = []

    class Page:
        def route(self, *args): pass
        def goto(self, *args, **kwargs): pass
        def reload(self, **kwargs): pass
        def wait_for_selector(self, *args, **kwargs): pass
        def screenshot(self, **kwargs): captured.append(kwargs)

    @contextmanager
    def playwright():
        context = SimpleNamespace(add_cookies=transferred_cookies.extend, new_page=Page)
        browser = SimpleNamespace(new_context=lambda: context, close=lambda: None)
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))

    monkeypatch.setattr('playwright.sync_api.sync_playwright', playwright)
    adapter = SimpleNamespace(config={'deployed_url': 'https://owned.example'},
                              client=SimpleNamespace(cookies={COOKIE_NAME: 'synthetic-session'}),
                              campaign=SimpleNamespace(folder=tmp_path))
    if sample is not None:
        adapter.artifact_sample = sample
    original = tmp_path / 'C15-portal.png'
    original.write_bytes(b'original-paid-evidence')
    checks = Adapter._browser_checks_owned(adapter, {'id': 'C15'}, [])
    assert all(check['passed'] for check in checks)
    assert captured == [{'path': str(tmp_path / filename), 'full_page': True}]
    assert transferred_cookies == [{
        'name': COOKIE_NAME, 'value': 'synthetic-session', 'domain': 'owned.example',
        'path': '/', 'httpOnly': True, 'secure': True, 'sameSite': 'Lax',
    }]
    assert original.read_bytes() == b'original-paid-evidence'
