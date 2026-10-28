"""Browser regressions for independent portal reads and responsive cached filtering."""

from datetime import timedelta
from contextlib import contextmanager

import pytest
from urllib.parse import parse_qs, urlparse

from e2e.browser_network import route_offline_browser_request
from e2e.test_workflows import PORTAL


def _request(service_type, status, created_at, **extra):
    return {
        "id": extra.pop("id", 1), "service_type": service_type, "status": status,
        "booking_type": "appointment", "created_at": created_at,
        "updated_at": created_at, "booking_time": created_at,
        "customer_name": "Alex", "phone": "+15550100001",
        "issue_description": service_type, **extra,
    }


def _call(call_id, created_at):
    return {"id": call_id, "call_id": call_id, "customer_name": "Alex",
            "phone": "+15550100001", "summary": str(call_id), "created_at": created_at}


def _fulfill_json(route, value):
    route.fulfill(status=200, content_type="application/json", body=__import__("json").dumps(value))


def _install_browser_routes(page, exact=None, prefixes=None):
    exact = exact or {}
    prefixes = prefixes or {}
    def dispatch(route):
        path = urlparse(route.request.url).path
        handler = exact.get(path)
        if handler is None:
            handler = next((candidate for prefix, candidate in prefixes.items() if path.startswith(prefix)), None)
        if handler is None:
            route_offline_browser_request(route)
        else:
            handler(route)
    page.route("**/*", dispatch)


_PAINT_INSTRUMENTATION = """
(() => {
  window.__portalFetches = [];
  window.__portalPaintBudgets = {};
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    window.__portalFetches.push(String(input));
    return nativeFetch(input, init);
  };
  const ends = {};
  const mapping = [
    ['/stats', 'stats', () => document.querySelector('#stat-total-calls')?.textContent !== '--'],
    ['/calls', 'calls', () => !/loading|failed to load/i.test(document.querySelector('#call-logs-list')?.innerText || '')],
    ['/service-requests', 'requests', () => !/loading|failed to load/i.test(document.querySelector('#service-requests-list')?.innerText || '')],
    ['/services', 'catalog', () => !/loading|failed to load/i.test(document.querySelector('#services-list-body')?.innerText || '') && !!document.querySelector('#services-list-body tr')],
  ];
  const resources = new PerformanceObserver(list => {
    for (const entry of list.getEntries()) {
      const path = new URL(entry.name).pathname;
      const match = mapping.find(([suffix]) => path.endsWith(suffix));
      if (match) { ends[match[1]] = entry.responseEnd; capture(); }
    }
  });
  resources.observe({type: 'resource', buffered: true});
  function capture() {
    for (const [suffix, key, ready] of mapping) {
      if (ends[key] === undefined || window.__portalPaintBudgets[key] !== undefined || !ready()) continue;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (window.__portalPaintBudgets[key] === undefined) {
          window.__portalPaintBudgets[key] = performance.now() - ends[key];
        }
      }));
    }
  }
  const mutations = new MutationObserver(capture);
  const observeDocument = () => {
    if (document.documentElement) mutations.observe(document.documentElement, {childList: true, subtree: true, characterData: true});
    else document.addEventListener('DOMContentLoaded', observeDocument, {once: true});
  };
  observeDocument();
})();
"""


@pytest.mark.browser
def test_loaded_timeframe_filters_both_tables_without_dataset_fetch_and_meets_p95(page, api, scenario):
    """Twenty user changes paint from memory even while totals are pending."""
    start = scenario["start"]
    old = (start - timedelta(days=20)).isoformat(" ")
    recent = (start - timedelta(hours=2)).isoformat(" ")
    requests = [
        _request("Old history", "completed", old, id=11),
        _request("Recent history", "completed", recent, id=12),
        _request("Open operational", "pending", old, id=13),
    ]
    requests.extend(_request(f"History row {i}", "completed", recent, id=100 + i) for i in range(97))
    calls = [_call(i, old if i % 2 else recent) for i in range(100)]
    counts = {"calls": 0, "requests": 0, "stats": 0}
    held_stats = []
    hold_totals = {"enabled": False}

    def held(route):
        counts["stats"] += 1
        if hold_totals["enabled"]:
            held_stats.append(route)
        else:
            _fulfill_json(route, {"total_calls": 2, "total_callbacks": 0, "total_appointments": 1, "total_requests": 3, "pending_requests": 1, "open_slots": 0})

    _install_browser_routes(page, prefixes={
        PORTAL + "/stats": held,
        PORTAL + "/calls": lambda route: (counts.__setitem__("calls", counts["calls"] + 1), _fulfill_json(route, calls)),
        PORTAL + "/service-requests": lambda route: (counts.__setitem__("requests", counts["requests"] + 1), _fulfill_json(route, requests)),
    })
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.locator("#service-requests-list tr").filter(has_text="Open operational").wait_for()
    assert page.locator("#call-logs-list tr").count() > 0
    page.locator("#sr-next-page").click()
    assert page.locator("#sr-page-num").inner_text() == "Page 2 of 10"
    page.locator("#calls-timeframe-select").select_option("24h")
    assert page.locator("#sr-page-num").inner_text() == "Page 1 of 10"
    page.locator("#calls-timeframe-select").select_option("all")
    page.evaluate("window.__responsiveSamples = []")
    hold_totals["enabled"] = True
    initial_reads = (counts["calls"], counts["requests"])
    samples = page.evaluate("""async () => {
      const select = document.querySelector('#calls-timeframe-select');
      const values = ['24h', '7d', '30d', 'all'];
      const durations = [];
      for (let i = 0; i < 20; i++) {
        const value = values[i % values.length];
        const t0 = performance.now();
        select.value = value;
        select.dispatchEvent(new Event('change', {bubbles: true}));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        durations.push(performance.now() - t0);
      }
      return durations;
    }""")
    assert counts["calls"] == initial_reads[0]
    assert counts["requests"] == initial_reads[1]
    assert len(held_stats) >= 1
    assert page.locator("#service-requests-list tr").filter(has_text="Open operational").count() == 1
    assert page.locator("#service-requests-list tr").filter(has_text="Recent history").count() == 1
    assert page.locator("#service-requests-list tr").filter(has_text="Old history").count() == 1  # final timeframe is all
    assert sorted(samples)[18] <= 250, {"samples_ms": samples, "fixture": {"calls": len(calls), "requests": len(requests)}}
    print({"timeframe_paint_ms": samples, "p95_ms": sorted(samples)[18], "fixture": {"calls": len(calls), "requests": len(requests)}, "browser": page.context.browser.version, "platform": __import__("platform").platform()})
    for route in held_stats:
        route.abort()


@pytest.mark.browser
def test_dashboard_sections_paint_independently_and_catalog_paints_while_staff_pending(page, api):
    """A ready table/catalog paints while sibling requests remain unresolved."""
    held = {}
    def hold(key):
        def handler(route):
            held[key] = route
        return handler
    _install_browser_routes(page, prefixes={
        PORTAL + "/stats": hold("stats"), PORTAL + "/calls": hold("calls"),
        PORTAL + "/service-requests": hold("requests"), PORTAL + "/agents": hold("agents"),
        PORTAL + "/services": lambda route: _fulfill_json(route, services),
    })
    services = [{"id": i, "name": "Ready catalog row" if i == 1 else f"Catalog row {i}", "description": "Synthetic", "price_range": "$10", "duration_minutes": 30, "assigned_agent_names": ["Morgan"], "assigned_agent_ids": [1]} for i in range(1, 47)]
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.wait_for_function("window.__portalFetches.some(url => new URL(url, location.href).pathname.endsWith('/stats'))")
    started = page.evaluate("window.__portalFetches.map(url => new URL(url, location.href).pathname)")
    assert PORTAL + "/calls" in started and PORTAL + "/service-requests" in started, started
    assert {"stats", "calls", "requests"}.issubset(held)
    _fulfill_json(held.pop("stats"), {"total_calls": 1, "total_callbacks": 0, "total_appointments": 1, "total_requests": 1, "pending_requests": 1, "open_slots": 0})
    page.wait_for_function("window.__portalPaintBudgets.stats !== undefined")
    assert page.evaluate("window.__portalPaintBudgets.stats") <= 250
    _fulfill_json(held.pop("calls"), [_call("Ready call row", "2026-10-27 10:00:00")])
    page.wait_for_function("window.__portalPaintBudgets.calls !== undefined")
    assert page.evaluate("window.__portalPaintBudgets.calls") <= 250
    _fulfill_json(held.pop("requests"), [_request("Ready dashboard row", "pending", "2026-10-27 10:00:00")])
    page.locator("#service-requests-list .issue-desc-text").get_by_text("Ready dashboard row", exact=True).wait_for()
    page.wait_for_function("window.__portalPaintBudgets.requests !== undefined")
    assert page.evaluate("window.__portalPaintBudgets.requests") <= 250
    page.locator('[data-tab="services"]').click()
    catalog_row = page.locator("#services-list-body").get_by_text("Ready catalog row")
    catalog_row.wait_for()
    assert "Morgan" in page.locator("#services-list-body").inner_text()
    assert "agents" in held
    page.wait_for_function("window.__portalPaintBudgets.catalog !== undefined")
    catalog_ms = page.evaluate("window.__portalPaintBudgets.catalog")
    assert catalog_ms <= 250
    print({"initial_section_paint_ms": {key: page.evaluate(f"window.__portalPaintBudgets.{key}") for key in ("stats", "calls", "requests")}, "catalog_paint_ms": catalog_ms, "fixture": {"calls": 1, "requests": 1, "services": len(services), "staff": 2}, "browser": page.context.browser.version, "platform": __import__("platform").platform()})
    for route in held.values():
        route.abort()


@pytest.mark.browser
def test_timeframe_change_on_dashboard_does_not_reload_hidden_analytics(page, api):
    """Analytics is requested only when its actual pane is visible."""
    analytics_hits = []
    _install_browser_routes(page, prefixes={PORTAL + "/analytics/": lambda route: (analytics_hits.append(route.request.url), _fulfill_json(route, {}))})
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.locator('[data-tab="config"]').click()
    page.locator("[data-subtab='analytics']").click()
    page.wait_for_function("document.querySelector('#analytics-view')?.classList.contains('active')")
    page.locator("[data-tab='dashboard']").click()
    count = len(analytics_hits)
    page.locator("#calls-timeframe-select").select_option("30d")
    assert len(analytics_hits) == count


@pytest.mark.browser
def test_visible_analytics_refreshes_for_latest_timeframe(page, api):
    """Visible Analytics follows timeframe changes and ignores obsolete held responses."""
    held = {}
    analytics_hits = []
    def analytics(route):
        query = parse_qs(urlparse(route.request.url).query)
        timeframe = query.get("timeframe", ["7d"])[0]
        path = urlparse(route.request.url).path.rsplit("/", 1)[-1]
        analytics_hits.append(timeframe)
        if timeframe == "7d":
            held[path] = route
        else:
            _fulfill_json(route, {"sla_on_time_pct": 30 if timeframe == "30d" else 24, "on_time_confirmed": 0, "escalations_resolved": 0, "escalations_reassigned": 0, "avg_response_minutes": 1, "total_escalated": 0, "escalations_active": 0})
    _install_browser_routes(page, prefixes={PORTAL + "/analytics/": analytics})
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.locator('[data-tab="config"]').click()
    page.locator("[data-subtab='analytics']").click()
    page.wait_for_function("window.__portalFetches.filter(url => new URL(url, location.href).pathname.includes('/analytics/')).length >= 4")
    page.locator("#calls-timeframe-select").select_option("24h")
    page.locator("#calls-timeframe-select").select_option("30d")
    page.wait_for_function("window.__portalFetches.some(url => url.includes('/analytics/overview?timeframe=30d'))")
    page.locator("#kpi-sla-compliance").get_by_text("30%", exact=True).wait_for()
    for route in held.values():
        _fulfill_json(route, {"sla_on_time_pct": 7, "on_time_confirmed": 0, "escalations_resolved": 0, "escalations_reassigned": 0, "avg_response_minutes": 1, "total_escalated": 0, "escalations_active": 0})
    assert page.locator("#kpi-sla-compliance").inner_text() == "30%"
    assert "30d" in analytics_hits


@pytest.mark.browser
def test_failed_dashboard_refresh_retains_rows_and_does_not_report_success(page, api):
    """Refresh feedback follows completion; a failed section keeps usable old data."""
    calls = {"count": 0}
    def call_route(route):
        calls["count"] += 1
        if calls["count"] == 1:
            _fulfill_json(route, [_call("Saved call row", "2026-10-27 10:00:00")])
        elif calls["count"] == 2:
            route.fulfill(status=503, body="synthetic outage")
        else:
            _fulfill_json(route, [_call("Recovered call row", "2026-10-27 10:00:00")])
    _install_browser_routes(page, prefixes={PORTAL + "/calls": call_route})
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.locator("#call-logs-list").get_by_text("Saved call row").wait_for()
    page.locator("#refresh-data-btn").click()
    status = page.locator("#calls-read-status")
    status.get_by_role("button", name="Retry").wait_for()
    assert "Saved call row" in page.locator("#call-logs-list").inner_text()
    assert "refreshed" not in page.locator("#app-toast").inner_text().lower()
    status.get_by_role("button", name="Retry").click()
    page.locator("#calls-read-status").wait_for(state="hidden")
    page.locator("#call-logs-list").get_by_text("Recovered call row").wait_for()


@pytest.mark.browser
def test_repeated_refresh_keeps_only_one_inflight_read_per_resource(page, api):
    """Repeated clicks do not fan out unbounded identical dashboard requests."""
    pending = {"stats": [], "calls": [], "requests": []}
    _install_browser_routes(page, prefixes={
        PORTAL + "/stats": lambda route: pending["stats"].append(route),
        PORTAL + "/calls": lambda route: pending["calls"].append(route),
        PORTAL + "/service-requests": lambda route: pending["requests"].append(route),
    })
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.wait_for_function("window.__portalFetches.some(url => new URL(url, location.href).pathname.endsWith('/stats'))")
    for _ in range(5):
        page.locator("#refresh-data-btn").click()
    assert len(pending["stats"]) == 1
    for route in pending["stats"]:
        _fulfill_json(route, {"total_calls": 0, "total_callbacks": 0, "total_appointments": 0, "total_requests": 0, "pending_requests": 0, "open_slots": 0})
    page.wait_for_function("window.__portalFetches?.some(url => new URL(url, location.href).pathname.endsWith('/calls'))", timeout=2000)
    assert len(pending["calls"]) <= 1
    assert len(pending["requests"]) <= 1
    for key, routes in pending.items():
        if key == "stats":
            continue
        for route in routes:
            _fulfill_json(route, [])


@pytest.mark.browser
def test_dashboard_latest_timeframe_stats_response_wins_when_requests_finish_in_reverse(page, api):
    """A late response for an older timeframe cannot replace the latest badge or totals."""
    pending = {}
    stats_count = {"value": 0}
    def stats(route):
        stats_count["value"] += 1
        timeframe = parse_qs(urlparse(route.request.url).query).get("calls_timeframe", ["7d"])[0]
        if timeframe == "7d":
            _fulfill_json(route, {"total_calls": 7, "total_callbacks": 0, "total_appointments": 0, "total_requests": 0, "pending_requests": 0, "open_slots": 0})
        else:
            pending[timeframe] = route
    _install_browser_routes(page, prefixes={PORTAL + "/stats": stats})
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.locator("#stat-calls-badge").get_by_text("Past 7 days").wait_for()
    page.locator("#calls-timeframe-select").select_option("24h")
    page.locator("#calls-timeframe-select").select_option("all")
    page.wait_for_function("window.__portalFetches.filter(url => new URL(url, location.href).pathname.endsWith('/stats')).length >= 3")
    assert set(pending) == {"24h", "all"}
    _fulfill_json(pending["all"], {"total_calls": 99, "total_callbacks": 0, "total_appointments": 0, "total_requests": 0, "pending_requests": 0, "open_slots": 0})
    page.locator("#stat-total-calls").get_by_text("99").wait_for()
    _fulfill_json(pending["24h"], {"total_calls": 24, "total_callbacks": 0, "total_appointments": 0, "total_requests": 0, "pending_requests": 0, "open_slots": 0})
    assert "All time" in page.locator("#stat-calls-badge").inner_text()
    assert page.locator("#stat-total-calls").inner_text() == "99"
    return


@pytest.mark.browser
def test_pre_mutation_request_read_cannot_overwrite_successful_create(page, live_server, api, scenario):
    """A held pre-save request list cannot replace the post-save authoritative read."""
    held = []
    reads = {"count": 0}
    def requests(route):
        reads["count"] += 1
        if reads["count"] == 2:
            held.append((route, route.fetch()))
        else:
            route.continue_()
    _install_browser_routes(page, prefixes={PORTAL + "/service-requests": requests})
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(f"{live_server}/portal/", wait_until="domcontentloaded")
    page.locator("#service-requests-list").wait_for()
    page.locator("#refresh-data-btn").click()
    page.wait_for_function("window.__portalFetches.filter(url => new URL(url, location.href).pathname.endsWith('/service-requests')).length >= 2")
    page.locator("#btn-new-request").click()
    page.locator("#sr-cust-name").fill("Post mutation fresh row")
    page.locator("#sr-cust-phone").fill("+15550100010")
    page.locator("#sr-veh-make").fill("Honda")
    page.locator("#sr-veh-model").fill("Civic")
    page.locator("#sr-veh-year").fill("2021")
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-issue-desc").fill("Fresh read race regression")
    page.locator("#sr-booking-date").fill(scenario["date"])
    page.locator("#sr-check-slots-btn").click()
    page.locator("#sr-slots-dropdown").select_option(scenario["start"].strftime("%Y-%m-%d %H:%M:%S"))
    page.locator("#sr-save-btn").click()
    with page.expect_response(lambda response: response.url.endswith("/portal/service-requests") and response.request.method == "POST"):
        page.locator("#confirm-modal-yes").click()
    page.locator("#service-requests-list").get_by_text("Post mutation fresh row").wait_for()
    assert len(held) == 1
    old_route, old_response = held.pop()
    old_route.fulfill(response=old_response)
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    assert page.locator("#service-requests-list").get_by_text("Post mutation fresh row").count() == 1



@pytest.mark.browser
def test_catalog_staff_failure_does_not_enable_empty_tag_submission_or_clear_saved_tags(page, api):
    """Unknown staff state keeps catalog visible and prevents accidental tag clearing."""
    _install_browser_routes(page, prefixes={
        PORTAL + "/agents": lambda route: route.fulfill(status=503, body="unavailable"),
        PORTAL + "/services": lambda route: _fulfill_json(route, [{"id": 1, "name": "Tagged service", "description": "Synthetic", "price_range": "$10", "duration_minutes": 30, "assigned_agent_names": ["Morgan"], "assigned_agent_ids": [2]}]),
    })
    page.goto(str(api.base_url).rstrip("/") + "/portal/#services", wait_until="domcontentloaded")
    page.locator("#services-list-body").get_by_text("Tagged service").wait_for()
    assert "Morgan" in page.locator("#services-list-body").inner_text()
    assert page.locator("#add-service-form button[type='submit']").is_disabled()
    assert "unavailable" in page.locator("#new-service-agents-list").inner_text().lower()
    assert page.locator("#new-service-agents-list").get_by_role("button", name="Retry staff").is_visible()
    page.locator(".edit-service-btn[data-id='1']").click()
    submit = page.locator("#edit-service-form button[type='submit']")
    page.locator("#edit-service-drawer.active").wait_for()
    page.locator("#edit-service-agents-list").get_by_text("unavailable", exact=False).wait_for()
    assert submit.is_disabled()
    assert "unavailable" in page.locator("#edit-service-agents-list").inner_text().lower()


@pytest.mark.browser
def test_superseded_staff_response_cannot_replace_revalidated_staff(page, api):
    """A late stale staff response cannot overwrite the latest catalog controls."""
    pending = []
    count = {"value": 0}
    def agents(route):
        count["value"] += 1
        if count["value"] == 1:
            pending.append(route)
        else:
            _fulfill_json(route, [{"id": 2, "name": "Fresh staff", "role": "technician", "is_active": True}])
    _install_browser_routes(page, prefixes={PORTAL + "/agents": agents})
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(str(api.base_url).rstrip("/") + "/portal/#services", wait_until="domcontentloaded")
    page.wait_for_function("window.__portalFetches.filter(url => new URL(url, location.href).pathname.endsWith('/agents')).length >= 1")
    page.locator('[data-tab="dashboard"]').click()
    page.locator('[data-tab="services"]').click()
    page.wait_for_function("window.__portalFetches.filter(url => new URL(url, location.href).pathname.endsWith('/agents')).length >= 2")
    page.locator("#new-service-agents-list").get_by_text("Fresh staff").wait_for()
    assert len(pending) == 1
    _fulfill_json(pending.pop(), [{"id": 1, "name": "Stale staff", "role": "technician", "is_active": True}])
    assert page.locator("#new-service-agents-list").get_by_text("Fresh staff").count() == 1
    assert page.locator("#new-service-agents-list").get_by_text("Stale staff").count() == 0


@pytest.mark.browser
def test_catalog_edit_delete_is_fresh_after_api_read_and_full_reload(page, api):
    """Catalog mutations invalidate UI data and persist through independent reads."""
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.locator('[data-tab="services"]').click()
    row = page.locator("#services-list-body tr").filter(has_text="Oil Change")
    row.wait_for()
    service_id = int(row.locator(".edit-service-btn").get_attribute("data-id"))
    row.locator(".edit-service-btn").click()
    page.locator("#edit-service-drawer.active").wait_for()
    page.locator("#edit-service-form button[type='submit']").wait_for(state="visible")
    page.wait_for_function("!document.querySelector('#edit-service-form button[type=submit]').disabled")
    page.locator("#edit-service-name").fill("Oil Change Revised E2E")
    page.locator("#edit-service-form button[type='submit']").click()
    page.locator("#services-list-body").get_by_text("Oil Change Revised E2E").wait_for()
    persisted = api.get(PORTAL + "/services").json()
    assert sum(item["id"] == service_id and item["name"] == "Oil Change Revised E2E" for item in persisted) == 1
    page.reload(wait_until="domcontentloaded")
    page.locator('[data-tab="services"]').click()
    page.locator("#services-list-body").get_by_text("Oil Change Revised E2E").wait_for()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(f".delete-service-btn[data-id='{service_id}']").click()
    page.locator("#services-list-body").get_by_text("Oil Change Revised E2E").wait_for(state="detached")
    assert all(item["id"] != service_id for item in api.get(PORTAL + "/services").json())


@pytest.mark.browser
def test_old_catalog_response_cannot_resurrect_service_after_delete(page, api):
    """A pre-delete GET finishing late cannot restore the removed catalog row."""
    calls = {"count": 0}
    held = []
    def services(route):
        calls["count"] += 1
        if calls["count"] == 2:
            held.append((route, route.fetch()))
        else:
            route.continue_()
    _install_browser_routes(page, prefixes={PORTAL + "/services": services})
    page.add_init_script(_PAINT_INSTRUMENTATION)
    page.goto(str(api.base_url).rstrip("/") + "/portal/", wait_until="domcontentloaded")
    page.locator('[data-tab="services"]').click()
    row = page.locator("#services-list-body tr").filter(has_text="Oil Change")
    row.wait_for()
    service_id = int(row.locator(".delete-service-btn").get_attribute("data-id"))
    page.locator('[data-tab="dashboard"]').click()
    page.locator('[data-tab="services"]').click()
    page.wait_for_function("window.__portalFetches.filter(url => new URL(url, location.href).pathname.endsWith('/services')).length >= 2")
    assert calls["count"] >= 2
    assert len(held) == 1
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(f".delete-service-btn[data-id='{service_id}']").click()
    page.wait_for_function("window.__portalFetches.filter(url => new URL(url, location.href).pathname.endsWith('/services')).length >= 3")
    page.locator("#services-list-body").get_by_text("Oil Change", exact=True).wait_for(state="detached")
    old_route, old_response = held.pop()
    old_route.fulfill(response=old_response)
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    assert page.locator("#services-list-body tr").filter(has_text="Oil Change").count() == 0
    assert all(item["id"] != service_id for item in api.get(PORTAL + "/services").json())


def test_agent_and_request_whatsapp_enrichment_is_batched_and_fresh(api, db, monkeypatch):
    """Each response uses one whitelist read regardless of phone count."""
    from serviceBot.db import connection

    db("UPDATE service_requests SET status='completed', duration_minutes=30, staff_agent_id=1 WHERE id=1")
    db("INSERT INTO service_requests(customer_id, service_type, status, duration_minutes, staff_agent_id) VALUES (1,'Second assigned','completed',30,1),(1,'Third assigned','completed',30,2)")
    db("INSERT INTO sms_whitelist(phone_number, friendly_name, twilio_verified, whatsapp_onboarded) VALUES ('5550100003','Synthetic staff',TRUE,TRUE) ON CONFLICT (phone_number) DO UPDATE SET whatsapp_onboarded=TRUE")

    original = connection.dict_cursor
    statements = []

    class CursorProxy:
        def __init__(self, cursor):
            self.cursor = cursor
        def execute(self, statement, params=None):
            if str(statement).lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(str(statement).split()).lower())
            return self.cursor.execute(statement, params) if params is not None else self.cursor.execute(statement)
        def __getattr__(self, name):
            return getattr(self.cursor, name)

    @contextmanager
    def traced(conn):
        with original(conn) as cursor:
            yield CursorProxy(cursor)

    monkeypatch.setattr(connection, "dict_cursor", traced)
    requests = api.get(PORTAL + "/service-requests")
    assert requests.status_code == 200
    request_rows = requests.json()
    assert [row["staff_agent_whatsapp_connected"] for row in request_rows] == [False, True, True]
    request_reads = list(statements)
    assert len(request_reads) <= 2, request_reads
    assert sum("sms_whitelist" in statement for statement in request_reads) == 1

    statements.clear()
    agents = api.get(PORTAL + "/agents")
    assert agents.status_code == 200
    assert [agent["whatsapp_connected"] for agent in agents.json()] == [True, False]
    agent_reads = list(statements)
    assert len(agent_reads) <= 2, agent_reads
    assert sum("sms_whitelist" in statement for statement in agent_reads) == 1

    db("UPDATE sms_whitelist SET whatsapp_onboarded=FALSE WHERE phone_number='5550100003'")
    statements.clear()
    refreshed = api.get(PORTAL + "/agents").json()
    assert refreshed[0]["whatsapp_connected"] is False
    assert sum("sms_whitelist" in statement for statement in statements) == 1


@pytest.mark.parametrize("path", [
    "/stats", "/calls", "/services", "/agents", "/service-requests",
    "/analytics/overview", "/analytics/sla", "/analytics/escalations", "/analytics/technicians",
])
def test_held_changed_read_does_not_block_health(api, monkeypatch, path):
    """Blocking DB work in a worker must leave the async server loop available."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from serviceBot.db import connection

    entered, release = Event(), Event()
    target = connection
    if path.startswith("/analytics/"):
        from serviceBot.services import analytics
        target = analytics
    original = target.get_db_connection

    def held_connection(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test failed to release held dashboard read"
        return original(*args, **kwargs)

    monkeypatch.setattr(target, "get_db_connection", held_connection)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(api.get, PORTAL + path)
        assert entered.wait(2)
        try:
            assert api.get("/health", timeout=1).json() == {"status": "healthy"}
            assert not pending.done()
        finally:
            release.set()
        assert pending.result(timeout=2).status_code == 200

