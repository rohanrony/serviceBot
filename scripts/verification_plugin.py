"""Fresh, machine-readable pytest evidence; used only by the offline gate."""

import json
import os
from pathlib import Path
import socket
from datetime import datetime, timezone

import pytest

_reports = {}
_deselected = []
_collection_errors = []
_started = None
_network = []
_dns_original = None


def now():
    return datetime.now(timezone.utc).isoformat()


def pytest_sessionstart(session):
    global _started, _dns_original
    _started = now()
    if session.config.getini("addopts") or session.config.option.keyword or session.config.option.markexpr:
        raise pytest.UsageError("Offline verification forbids configured test filtering/addopts")
    # This also protects collection/imports, before autouse application fixtures.
    for name in ("connect", "connect_ex"):
        original = getattr(socket.socket, name)

        def guarded(sock, address, _original=original):
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
                raise AssertionError("Offline verification blocks external sockets")
            return _original(sock, address)

        _network.append((name, original))
        setattr(socket.socket, name, guarded)
    _dns_original = socket.getaddrinfo

    def local_dns(host, *args, **kwargs):
        if host not in {"127.0.0.1", "::1", "localhost", None}:
            raise AssertionError("Offline verification blocks external DNS")
        return _dns_original(host, *args, **kwargs)

    socket.getaddrinfo = local_dns


def pytest_deselected(items):
    _deselected.extend(item.nodeid for item in items)


def pytest_collectreport(report):
    if report.failed:
        _collection_errors.append(str(report.longrepr))


def pytest_runtest_logreport(report):
    _reports.setdefault(report.nodeid, []).append({
        "phase": report.when, "outcome": report.outcome,
        "wasxfail": hasattr(report, "wasxfail"),
    })


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.user_properties.extend([
        ("verification_run_id", os.environ["VERIFY_RUN_ID"]),
        ("verification_node_id", item.nodeid),
    ])


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("VERIFY_EVIDENCE_DIR")
    if not destination:
        return
    mode = "collection" if session.config.option.collectonly else "execution"
    # Root is explicit: tests/ and e2e/ must remain separate database lifecycles.
    suite = os.environ["VERIFY_SUITE"]
    items = []
    for item in session.items:
        browser = item.get_closest_marker("browser") is not None
        marker = item.get_closest_marker("test_layer")
        layer = str(marker.args[0]) if marker and marker.args else (
            "browser" if browser else "unit_integration" if suite == "tests" else "http_workflow")
        items.append({"id": item.nodeid, "browser": browser, "layer": layer})
    result = {
        "schema": 1, "run_id": os.environ["VERIFY_RUN_ID"], "suite": suite,
        "mode": mode, "started_at": _started, "finished_at": now(),
        "complete": True, "exit_code": int(exitstatus), "items": items,
        "deselected": _deselected, "collection_errors": _collection_errors,
        "reports": _reports, "args": session.config.invocation_params.args,
    }
    path = Path(destination) / f"{suite}-{mode}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    for name, original in _network:
        setattr(socket.socket, name, original)
    if _dns_original is not None:
        socket.getaddrinfo = _dns_original
