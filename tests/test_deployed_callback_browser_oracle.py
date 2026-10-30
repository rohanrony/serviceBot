"""Pure captured browser contracts for the callback fields rendered by app.js."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from live_simulations import deployed_medium as medium
from serviceBot.api.auth import COOKIE_NAME

ISSUE = 'Intermittent whooshing spaceship sound'


def row(**updates):
    return {'id': 56, 'service_type': 'Repair', 'booking_type': 'callback',
            'status': 'pending', 'issue_description': ISSUE, **updates}


@pytest.mark.parametrize('description', [ISSUE, 'Callback requested: ' + ISSUE,
    'Appointment booked: ' + ISSUE + '. Preferred time: Monday 14:00',
    ISSUE + ' scheduled for Monday', ISSUE + ' (2021 Toyota Camry)',
    ISSUE + ' for 2021 Toyota Camry'])
def test_callback_matches_exact_visible_issue_and_badge_after_portal_formatting(description):
    assert medium._callback_browser_matches(row(issue_description=description), 'Callback' + ISSUE, 'Callback')
    assert medium._callback_browser_matches(row(issue_description=description), 'Callback\n' + ISSUE, 'Callback')


@pytest.mark.parametrize('updates,text,badge', [
    ({'issue_description': None}, 'Callback' + ISSUE, 'Callback'),
    ({'issue_description': ''}, 'Callback' + ISSUE, 'Callback'),
    ({'issue_description': '   '}, 'Callback' + ISSUE, 'Callback'),
    ({'issue_description': 'Callback requested: '}, 'Callback requested:', 'Callback'),
    ({'issue_description': 'Repair'}, 'CallbackRepair', 'Callback'),
    ({}, 'CallbackOther issue', 'Callback'),
    ({}, 'Callback' + ISSUE + ' extra', 'Callback'),
    ({}, ISSUE, ''),
    ({}, 'Callback' + ISSUE, 'Appointment'),
    ({'booking_type': 'appointment'}, 'Callback' + ISSUE, 'Callback'),
    ({'booking_type': None}, 'Callback' + ISSUE, 'Callback'),
])
def test_missing_or_mismatched_issue_or_callback_identity_fails(updates, text, badge):
    assert medium._callback_browser_matches(row(**updates), text, badge) is False


def browser_checks(monkeypatch, tmp_path, persisted, *, issue_text='Callback' + ISSUE,
                   badge='Callback', status='pending', count=1, whole_text=None):
    class Badge:
        def count(self): return 1 if badge else 0
        def inner_text(self): return badge
    class Issue:
        def count(self): return 1
        def inner_text(self): return issue_text
        def locator(self, selector):
            assert selector == '.booking-type-tag.callback'
            return Badge()
    class Row:
        def count(self): return count
        def inner_text(self): return whole_text or 'Synthetic 2021 Toyota Camry ' + issue_text
        def locator(self, selector):
            assert selector == '.issue-desc-text'
            return Issue()
    class Edit:
        def locator(self, selector):
            assert selector == 'xpath=ancestor::tr'
            return Row()
    class Page:
        def route(self, *args): pass
        def goto(self, *args, **kwargs): pass
        def reload(self, **kwargs): pass
        def wait_for_selector(self, *args, **kwargs): pass
        def screenshot(self, **kwargs): pass
        def locator(self, selector):
            if selector == '.edit-sr-btn[data-id="56"]': return Edit()
            assert selector == '.status-select-badge[data-id="56"]'
            return SimpleNamespace(input_value=lambda: status)
    @contextmanager
    def playwright():
        context = SimpleNamespace(add_cookies=lambda cookies: None, new_page=Page)
        browser = SimpleNamespace(new_context=lambda: context, close=lambda: None)
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
    monkeypatch.setattr('playwright.sync_api.sync_playwright', playwright)
    campaign = SimpleNamespace(config={'deployed_url': 'https://owned.example'}, folder=tmp_path,
        manifest={'baseline': [], 'deployed_medium': {'services': {}, 'operations': [],
                  'owned_request_ids': [], 'blocks': [], 'blocked': False}})
    client = SimpleNamespace(cookies={COOKIE_NAME: 'synthetic-session'})
    return medium.Adapter(campaign, client)._browser_checks_owned({'id': 'C12' if persisted['booking_type'] == 'callback' else 'C11'}, [persisted])


def test_real_oracle_accepts_owned_callback_issue_without_internal_repair_label(monkeypatch, tmp_path):
    checks = browser_checks(monkeypatch, tmp_path, row())
    assert checks and all(check['passed'] for check in checks)


@pytest.mark.parametrize('kind', ['missing_row', 'duplicate_row', 'wrong_status', 'wrong_issue', 'missing_badge'])
def test_real_callback_oracle_keeps_owned_row_status_and_identity_guards(monkeypatch, tmp_path, kind):
    kwargs = {'count': 0 if kind == 'missing_row' else 2} if kind in ('missing_row', 'duplicate_row') else {}
    if kind == 'wrong_status': kwargs['status'] = 'confirmed'
    if kind == 'wrong_issue': kwargs['issue_text'] = 'CallbackDifferent issue'
    if kind == 'missing_badge': kwargs['badge'] = ''
    checks = browser_checks(monkeypatch, tmp_path, row(), **kwargs)
    assert any(not check['passed'] for check in checks)


@pytest.mark.parametrize('service_matches', [False, True])
def test_appointment_catalog_service_assertion_remains_strong(monkeypatch, tmp_path, service_matches):
    service = 'LIVE TEST canonical Oil Change'
    persisted = row(booking_type='appointment', service_type=service)
    checks = browser_checks(monkeypatch, tmp_path, persisted,
        whole_text=service if service_matches else 'Some unrelated service')
    assert next(check for check in checks if check['name'] == 'reloaded browser owned row 56')['passed'] is service_matches


def test_fixed_native_query_retains_callback_issue_description(monkeypatch):
    seen = []
    monkeypatch.setattr(medium, '_read', lambda config, query, args: seen.append((query, args)) or [])
    assert medium._request_rows({}, [56]) == []
    assert 's.issue_description' in seen[0][0]
    assert seen[0][1] == ([56],)


def test_actual_native_css_transformed_callback_badge_matches_exact_issue(monkeypatch, tmp_path):
    # Read-only deployed DOM56: innerText includes CSS text-transform: uppercase.
    checks = browser_checks(monkeypatch, tmp_path, row(status='cancelled'),
        issue_text='CALLBACK' + ISSUE, badge='CALLBACK', status='cancelled')
    assert checks and all(check['passed'] for check in checks)


def test_css_badge_normalization_does_not_change_issue_case_or_content():
    assert not medium._callback_browser_matches(row(), 'CALLBACK' + ISSUE.lower(), 'CALLBACK')
    assert not medium._callback_browser_matches(row(), 'CALLBACK' + ISSUE + ' extra', 'CALLBACK')
