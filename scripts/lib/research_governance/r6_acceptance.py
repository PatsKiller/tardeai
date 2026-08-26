"""R6A-1 durable append-only store acceptance."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .decision_use_audit import DecisionUseLedger
from .durable_store import AUTHORITY, AppendOnlyStore, decision_use_event_payload
from .enums import GateState


def _pass(detail: str) -> tuple[str, str]:
    return GateState.PASS.value, detail


def _fail(detail: str) -> tuple[str, str]:
    return GateState.FAIL.value, detail


def check_durable_store() -> tuple[str, str]:
    if AUTHORITY != "READ_ONLY_ADVISORY":
        return _fail(f"authority drifted: {AUTHORITY}")

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "r6_governance.jsonl"
        store = AppendOnlyStore(path)
        store.append("family_freeze", {
            "family_id": "fam-r6",
            "hypothesis_id": "h-r6",
            "protocol_hash": "ph-r6",
            "planned_trials": [("t1", "cfg1"), ("t2", "cfg2")],
        })
        store.append("trial_record", {
            "family_id": "fam-r6",
            "trial_id": "t1",
            "config_hash": "cfg1",
            "result_payload": {"sharpe": 0.4},
        })
        store.append("trial_record", {
            "family_id": "fam-r6",
            "trial_id": "t2",
            "config_hash": "cfg2",
            "result_payload": {"sharpe": -0.2},
        })
        rec = DecisionUseLedger().record(
            decision_id="dec-r6",
            query={"src": "r6a-1"},
            evidence=[],
        )
        store.append("decision_use", decision_use_event_payload(rec))

        ok, reason = store.verify_chain()
        if not ok:
            return _fail(f"fresh chain must verify: {reason}")

        replayed = store.replay_trial_registry()
        if replayed.get_trial("fam-r6", "t1") is None or replayed.get_trial("fam-r6", "t2") is None:
            return _fail("replay registry missing recorded trials")

        ledger = store.replay_decision_ledger()
        rows = ledger.for_decision("dec-r6")
        if not rows or not rows[0].verify():
            return _fail("replayed decision_use is not authentic")

        if store.events()[-1].get("authority") != "READ_ONLY_ADVISORY":
            return _fail("stored authority is not READ_ONLY_ADVISORY")

        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) < 2:
            return _fail("expected at least two JSONL records")
        tampered = json.loads(lines[1])
        payload = dict(tampered.get("payload") or {})
        payload["config_hash"] = "TAMPERED"
        tampered["payload"] = payload
        lines[1] = json.dumps(tampered)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok_after, _ = store.verify_chain()
        if ok_after:
            return _fail("tampered middle line must fail verify_chain")

    return _pass("durable store hash-chain, replay, tamper-detect, READ_ONLY_ADVISORY")


CHECKS = {"R6A-1": check_durable_store}
