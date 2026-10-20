"""GET-only management continuation for retained fixture control intents."""

from types import SimpleNamespace

import httpx

from . import deployed_full_faults as faults
from . import deployed_full_negative as negative
from .core import SimulationError, fingerprint


def _pending(adapter):
    controls = []
    if negative.pending_owned_staff_recovery(adapter):
        controls.append("C23")
    controls.extend(
        cid for cid in ("C35", "C36") if faults.pending_control(adapter, cid)
    )
    return controls


def reconcile_campaign(campaign, provider):
    """Read original owned control outcomes without replaying any mutation.

    Each public control owner authenticates its retained stage and private intent.
    It alone may clear its matching blocked owner. This dispatcher never changes
    a blocked flag or persists returned private receipts.
    """
    state = campaign.manifest.get("deployed_medium", {})
    if not _pending(SimpleNamespace(state=state)):
        return
    if not campaign.manifest.get("stage_authorization"):
        raise SimulationError(
            "Retained fixture recovery requires its original stage claim"
        )
    from .deployed_full_adapter import Adapter

    summary = {"control_reconciled": False, "native_acceptance": "unverified"}
    campaign.manifest["fixture_reconciliation"] = summary
    failed = False
    try:
        with httpx.Client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            adapter = Adapter(campaign, client)
            adapter.fault_client = client
            adapter.simulation_staff_client = client
            unresolved_errors = set()
            for _ in range(2):
                before = fingerprint(adapter.state)
                for cid in _pending(adapter):
                    try:
                        if cid == "C23":
                            negative.recover_owned_staff(adapter)
                        else:
                            faults.recover_control(adapter, cid)
                        unresolved_errors.discard(cid)
                    except Exception:  # noqa: BLE001 - private control exceptions must not escape
                        unresolved_errors.add(cid)
                pending = _pending(adapter)
                after = fingerprint(adapter.state)
                if not pending or before == after:
                    break
            summary.update(
                control_reconciled=not pending and not unresolved_errors,
                pending_controls=pending,
                control_proof_sha256=after,
                fixture_mutation_blocked=adapter.state.get("blocked") is True,
            )
    except Exception:  # noqa: BLE001 - fixed diagnostic, no token/receipt persistence
        failed = True
    finally:
        campaign.save()
    if failed or not summary["control_reconciled"]:
        raise SimulationError(
            "Retained fixture control recovery remains incomplete; reconcile without replay"
        )
    return summary
