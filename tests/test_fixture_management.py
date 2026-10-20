"""Management dispatch for retained fixture controls, with captured read owners."""

import json
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import (
    deployed,
    deployed_full_adapter,
    deployed_full_faults as faults,
)
from live_simulations import deployed_full_negative as negative, runner
from live_simulations.core import SimulationError, private_json


@pytest.fixture
def setup_and_cleanup_test_db():
    """Captured control boundaries do not need PostgreSQL."""
    yield


@pytest.mark.parametrize(
    "scenario",
    ["none", "staff", "faults", "mixed", "two_pass", "stalled", "unsafe_error"],
)
def test_manage_continues_only_retained_fixture_controls(
    tmp_path, monkeypatch, scenario
):
    from live_simulations import deployed_full_fixture_recovery as recovery

    folder = tmp_path / "run"
    manifest = {
        "run_id": "run",
        "invocations": [],
        "stage_authorization": {"authorization_id": "owned"},
    }
    ops = []
    if scenario != "none":
        if scenario in ("staff", "mixed", "two_pass", "stalled", "unsafe_error"):
            ops.append(
                {
                    "owned_staff_action": "create",
                    "status": "unknown",
                    "intent_id": "a" * 32,
                    "run_id": "run",
                    "body_fingerprint": "staff-hash",
                }
            )
        if scenario in ("faults", "mixed", "two_pass"):
            for cid in ("C35", "C36"):
                ops.append(
                    {
                        "fault_case": cid,
                        "fault_action": "create",
                        "status": "unknown",
                        "operation_id": cid,
                        "body_fingerprint": cid + "-hash",
                    }
                )
        manifest["deployed_medium"] = {
            "operations": ops,
            "owned_request_ids": [],
            "blocked": True,
            "services": {},
            "current_request_ids": [],
        }
    if scenario == "two_pass":
        manifest["deployed_medium"]["blocked_operation_owner"] = {
            key: ops[0][key]
            for key in ("owned_staff_action", "run_id", "intent_id", "body_fingerprint")
        } | {"kind": "staff"}
    private_json(folder / "manifest.json", manifest)
    private_json(tmp_path / "usage-ledger.json", {"entries": []})
    campaign = SimpleNamespace(
        root=tmp_path,
        folder=folder,
        run_id="run",
        config={},
        manifest=manifest,
        report=lambda: None,
    )
    campaign.save = lambda: private_json(folder / "manifest.json", campaign.manifest)
    monkeypatch.setattr(deployed, "Campaign", lambda *a, **kw: campaign)
    monkeypatch.setattr(runner, "ElevenLabs", lambda *a: object())
    monkeypatch.setattr(runner, "secret", lambda *a: "captured")
    monkeypatch.setattr(runner, "write_report", lambda *a: None)
    clients = []
    adapters = []
    original_client = httpx.Client
    original_adapter = deployed_full_adapter.Adapter

    def client(**options):
        assert options["trust_env"] is False and options["follow_redirects"] is False

        def transport(request):
            assert request.method == "GET"
            return httpx.Response(200, json={"success": True})

        value = original_client(**options, transport=httpx.MockTransport(transport))
        clients.append(value)
        return value

    def adapter(*args):
        value = original_adapter(*args)
        adapters.append(value)
        return value

    monkeypatch.setattr(recovery.httpx, "Client", client)
    monkeypatch.setattr(deployed_full_adapter, "Adapter", adapter)
    recovered = []

    def recover_staff(adapter):
        assert adapter.simulation_staff_client is clients[0]
        assert adapter.fault_client is clients[0]
        adapter.simulation_staff_client.get("https://owned.invalid/staff/recover")
        recovered.append("staff")
        if scenario == "unsafe_error":
            raise RuntimeError("PRIVATE-RECEIPT-AND-TOKEN")
        if scenario != "stalled":
            for operation in adapter.state["operations"]:
                if operation.get("owned_staff_action"):
                    operation["status"] = "observed"
        if scenario == "two_pass" and not any(
            op.get("fault_case") and op["status"] != "observed"
            for op in adapter.state["operations"]
        ):
            adapter.state["blocked"] = False
            adapter.state.pop("blocked_operation_owner", None)
        adapter._save()
        return {
            "receipt": "PRIVATE-RECEIPT-AND-TOKEN",
            "email": "private@example.invalid",
        }

    def recover_fault(adapter, cid):
        adapter.fault_client.get("https://owned.invalid/fault/recover")
        recovered.append(cid)
        for operation in adapter.state["operations"]:
            if operation.get("fault_case") == cid:
                operation["status"] = "observed"
        adapter._save()
        return {
            "control_reconciled": True,
            "case_verified": False,
            "native_acceptance": "unverified",
            "lease_token": "PRIVATE-RECEIPT-AND-TOKEN",
        }

    monkeypatch.setattr(negative, "recover_owned_staff", recover_staff)
    monkeypatch.setattr(faults, "recover_control", recover_fault)
    if scenario in ("stalled", "unsafe_error"):
        with pytest.raises(SimulationError) as error:
            deployed.manage({}, "run", "reconcile")
        assert "PRIVATE" not in str(error.value)
    else:
        assert deployed.manage({}, "run", "reconcile") == 0
    if scenario == "none":
        assert not clients and not adapters and not recovered
        assert "deployed_medium" not in manifest
    else:
        assert len(clients) == len(adapters) == 1
        assert clients[0].is_closed
        assert manifest["deployed_medium"]["blocked"] is (scenario != "two_pass")
        assert all(op["status"] == "observed" for op in ops) is (
            scenario not in ("stalled", "unsafe_error")
        )
        summary = manifest["fixture_reconciliation"]
        assert summary["native_acceptance"] == "unverified"
        assert summary["control_reconciled"] is (
            scenario not in ("stalled", "unsafe_error")
        )
        serialized = json.dumps(summary)
        assert (
            "PRIVATE" not in serialized
            and "private@" not in serialized
            and "lease_token" not in serialized
        )
    # Every helper invocation retains the same original operations and ownership.
    if scenario != "none":
        assert manifest["deployed_medium"]["operations"] is ops
    if scenario == "two_pass":
        assert recovered == ["staff", "C35", "C36", "staff"]
