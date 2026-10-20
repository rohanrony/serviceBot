"""Offline composed C33 foreign booking observation regression."""

import copy

import pytest

from live_simulations.core import SimulationError
from live_simulations.deployed_full_native import NativeBridge
from tests.test_deployed_full_native import adapter


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    yield


class ForeignReader:
    def __init__(self):
        self.request = {
            "id": 77,
            "customer_id": 12,
            "staff_agent_id": 4,
            "service_type": "Oil Change",
            "status": "pending",
        }
        self.customers = [
            {"id": 9, "phone": "+14242704893", "sms_opt_in": True},
            {"id": 12, "phone": "+14242704894", "sms_opt_in": True},
        ]

    def rows(self, query, params=()):
        if "native:condition_poll" in query:
            return []
        key = query.split("/* conditions:")[1].split(" */")[0]
        return copy.deepcopy(
            {
                "clock": [{"observed_at_unix": 100}],
                "customers": self.customers,
                "requests": [self.request] if params == (77,) else [],
                "staff": [{"id": 4}],
                "policy": [],
            }.get(key, [])
        )

    def request_rows(self, ids):
        return copy.deepcopy([self.request] if self.request["id"] in ids else [])


def fixture_bridge(tmp_path):
    a = adapter(tmp_path)
    a.owned_ids = {31}
    a.state["owned_request_ids"] = [31]
    a._register = lambda *args: pytest.fail("Foreign booking adopted")
    reader = ForeignReader()
    bridge = NativeBridge(a, object(), reader=reader, monotonic=lambda: 100)
    return bridge, reader, a, {"other_request_id": 77, "other_customer_id": 12}


def test_c33_foreign_booking_binds_readonly_and_observes_twice(tmp_path):
    bridge, reader, a, values = fixture_bridge(tmp_path)
    bridge.arrange_conditions("C33", values)
    for _ in range(2):
        report = bridge.observe_conditions("C33", values)
        assert report["evidence_complete"] is True
    assert a.owned_ids == {31}
    assert a.state["owned_request_ids"] == [31]
    assert a.original_ids == {10}


@pytest.mark.parametrize("change", ["request", "customer", "config", "missing"])
def test_c33_rejects_foreign_baseline_drift_without_adoption(tmp_path, change):
    bridge, reader, a, values = fixture_bridge(tmp_path)
    bridge.arrange_conditions("C33", values)
    if change == "request":
        reader.request["status"] = "cancelled"
    elif change == "customer":
        reader.customers[1]["phone"] = "+14242704895"
    elif change == "config":
        values["other_request_id"] = 78
    else:
        reader.request["id"] = 78
    with pytest.raises(SimulationError):
        bridge.observe_conditions("C33", values)
    assert a.owned_ids == {31}


@pytest.mark.parametrize("change", ["missing", "mismatch", "same_customer", "owned"])
def test_c33_rejects_invalid_foreign_pre_submission_baseline(tmp_path, change):
    bridge, reader, a, values = fixture_bridge(tmp_path)
    if change == "missing":
        reader.request["id"] = 78
    elif change == "mismatch":
        reader.request["customer_id"] = 13
    elif change == "same_customer":
        values["other_customer_id"] = 9
    else:
        a.owned_ids.add(77)
    before = set(a.owned_ids)
    with pytest.raises(SimulationError):
        bridge.arrange_conditions("C33", values)
    assert a.owned_ids == before
    assert "C33" not in a.state.get("full_condition_prepared", {})
