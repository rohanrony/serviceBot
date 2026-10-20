"""The management ledger delegates C48 to its retained phase owner."""

import json
from types import SimpleNamespace

import pytest

from live_simulations import runner
from live_simulations.core import SimulationError, private_json

pytestmark = pytest.mark.test_layer("composed")


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    yield


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    run = SimpleNamespace(
        root=tmp_path,
        run_id="a" * 32,
        config={},
        manifest={"invocations": []},
        save=lambda: None,
    )
    monkeypatch.setattr(runner, "secret", lambda *a: "synthetic")
    monkeypatch.setattr(runner, "write_report", lambda *a: None)
    monkeypatch.setattr(
        runner,
        "ElevenLabs",
        lambda *a: SimpleNamespace(
            request=lambda *a: pytest.fail("C48 generic discovery forbidden"),
            get=lambda *a: pytest.fail("C48 generic polling forbidden"),
        ),
    )
    return run


@pytest.mark.parametrize("settled", [False, True])
def test_phase_reconciliation_precedes_generic_and_resumes_settled_entries(
    runtime, settled
):
    path = runtime.root / "usage-ledger.json"
    entries = [
        dict(
            run_id=runtime.run_id,
            case_id="C48",
            phase=phase,
            unsettled=not settled,
            **({"credits": "3"} if settled else {}),
        )
        for phase in ("interruption", "recovery")
    ]
    foreign = dict(run_id="b" * 32, case_id="C48", phase="interruption", unsettled=True)
    private_json(path, {"entries": entries + [foreign]})
    calls = []

    def recover(actual, provider):
        with runner.campaign_lock(actual.root):
            calls.append(actual.run_id)
            ledger = json.loads(path.read_text())
            for row in ledger["entries"][:2]:
                row.update(unsettled=False, credits="3")
            private_json(path, ledger)

    for _ in range(2):
        runner.reconcile(runtime, phase_reconcile=recover)
        assert runtime.manifest["spent_credits"] == "6"
        assert runtime.manifest["unsettled_usage"] is False
        assert runtime.manifest["phase_reconciliation_pending"] is False
    assert calls == [runtime.run_id, runtime.run_id]
    assert json.loads(path.read_text())["entries"][-1] == foreign


def test_phase_reconciliation_failure_preserves_partial_billing(runtime):
    path = runtime.root / "usage-ledger.json"
    private_json(
        path,
        {
            "entries": [
                dict(
                    run_id=runtime.run_id,
                    case_id="C48",
                    phase="interruption",
                    unsettled=True,
                )
            ]
        },
    )

    def recover(actual, provider):
        ledger = json.loads(path.read_text())
        ledger["entries"][0].update(unsettled=False, credits="4")
        private_json(path, ledger)
        raise SimulationError("Native phase still pending")

    with pytest.raises(SimulationError, match="Native phase still pending"):
        runner.reconcile(runtime, phase_reconcile=recover)
    assert runtime.manifest["spent_credits"] == "4"
    assert runtime.manifest["phase_reconciliation_pending"] is True


@pytest.mark.parametrize("fails", [False, True])
def test_fixture_reconciliation_runs_with_owned_lock_and_preserves_billing(
    runtime, fails
):
    private_json(
        runtime.root / "usage-ledger.json",
        {
            "entries": [
                dict(run_id=runtime.run_id, case_id="C17", unsettled=False, credits="7")
            ]
        },
    )
    calls = []

    def recover(actual, provider):
        with runner.campaign_lock(actual.root):
            calls.append(actual.run_id)
            if fails:
                raise SimulationError("Owned fixture remains unknown")

    if fails:
        with pytest.raises(SimulationError, match="Owned fixture remains unknown"):
            runner.reconcile(runtime, fixture_reconcile=recover)
    else:
        runner.reconcile(runtime, fixture_reconcile=recover)
    assert calls == [runtime.run_id]
    assert runtime.manifest["spent_credits"] == "7"
