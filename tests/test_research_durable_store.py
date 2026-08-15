"""R6 append-only governance store — hash-chain, tamper, truncate, replay."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance.decision_use_audit import (  # noqa: E402
    DecisionUseLedger,
    is_authentic_audit,
)
from scripts.lib.research_governance.durable_store import (  # noqa: E402
    AUTHORITY,
    EVENT_DECISION_USE,
    EVENT_FAMILY_FREEZE,
    EVENT_OOS_WINDOW,
    EVENT_TRIAL_RECORD,
    GENESIS,
    AppendOnlyStore,
    decision_use_event_payload,
)
from scripts.lib.research_governance.enums import GateState  # noqa: E402
from scripts.lib.research_governance.r6_acceptance import check_durable_store  # noqa: E402
from scripts.lib.research_governance.receipts import ReceiptAuthority  # noqa: E402


def _freeze_payload(family_id: str = "fam") -> dict:
    return {
        "family_id": family_id,
        "hypothesis_id": "h1",
        "protocol_hash": "ph",
        "planned_trials": [("t1", "cfg1"), ("t2", "cfg2")],
    }


def _trial_payload(trial_id: str, config_hash: str, family_id: str = "fam", **extra) -> dict:
    body = {
        "family_id": family_id,
        "trial_id": trial_id,
        "config_hash": config_hash,
        "result_payload": extra.pop("result_payload", {"sharpe": 0.1}),
    }
    body.update(extra)
    return body


def _decision_payload(decision_id: str = "dec-1") -> dict:
    rec = DecisionUseLedger().record(
        decision_id=decision_id,
        query={"q": "seasonality"},
        evidence=[],
    )
    return decision_use_event_payload(rec)


def _seed(store: AppendOnlyStore) -> None:
    store.append(EVENT_FAMILY_FREEZE, _freeze_payload())
    store.append(EVENT_TRIAL_RECORD, _trial_payload("t1", "cfg1", result_payload={"sharpe": 0.5}))
    store.append(EVENT_TRIAL_RECORD, _trial_payload("t2", "cfg2", result_payload={"sharpe": -0.1}))
    store.append(EVENT_DECISION_USE, _decision_payload())


def test_happy_chain(tmp_path):
    path = tmp_path / "gov.jsonl"
    store = AppendOnlyStore(path)
    _seed(store)
    ok, reason = store.verify_chain()
    assert ok, reason
    evs = store.events()
    assert len(evs) == 4
    assert evs[0]["prev_hash"] == GENESIS
    assert evs[0]["seq"] == 1
    assert evs[1]["prev_hash"] == evs[0]["record_digest"]
    assert evs[2]["prev_hash"] == evs[1]["record_digest"]
    assert evs[3]["prev_hash"] == evs[2]["record_digest"]
    assert evs[0]["authority"] == "READ_ONLY_ADVISORY"
    assert AUTHORITY == "READ_ONLY_ADVISORY"
    assert all(ev["signature"] for ev in evs)
    assert all(ev["record_digest"] for ev in evs)
    # Reopen with the shared module authority must still verify.
    reopened = AppendOnlyStore(path)
    ok2, reason2 = reopened.verify_chain()
    assert ok2, reason2


def test_tamper_breaks_chain(tmp_path):
    path = tmp_path / "gov.jsonl"
    store = AppendOnlyStore(path)
    _seed(store)
    assert store.verify_chain()[0] is True

    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["payload"]["config_hash"] = "TAMPERED"
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, reason = store.verify_chain()
    assert ok is False
    assert "digest" in reason or "signature" in reason or "prev_hash" in reason


def test_missing_signature_fails_verify(tmp_path):
    path = tmp_path / "gov.jsonl"
    store = AppendOnlyStore(path)
    _seed(store)
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["signature"] = ""
    lines[0] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, reason = store.verify_chain()
    assert ok is False
    assert "signature" in reason


def test_truncate_detection(tmp_path):
    path = tmp_path / "gov.jsonl"
    store = AppendOnlyStore(path)
    _seed(store)
    original = path.read_text(encoding="utf-8")
    # Drop the last committed line — size shrinks, tip digest no longer matches.
    kept = original.splitlines()[:-1]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="truncated|rewritten|digest"):
        store.append(EVENT_OOS_WINDOW, {
            "family_id": "fam",
            "oos_window_id": "w1",
            "oos_generation": 1,
        })


def test_rewrite_detection(tmp_path):
    path = tmp_path / "gov.jsonl"
    store = AppendOnlyStore(path)
    store.append(EVENT_FAMILY_FREEZE, _freeze_payload())
    store.append(EVENT_TRIAL_RECORD, _trial_payload("t1", "cfg1"))
    # Same-size-ish rewrite of the last line with a different digest.
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1])
    rec["record_digest"] = "f" * 64
    rec["payload"]["result_payload"] = {"sharpe": 99}
    path.write_text("\n".join(lines[:-1] + [json.dumps(rec)]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="rewritten|digest|truncated"):
        store.append(EVENT_TRIAL_RECORD, _trial_payload("t2", "cfg2"))


def test_replay(tmp_path):
    path = tmp_path / "gov.jsonl"
    store = AppendOnlyStore(path)
    store.append(EVENT_FAMILY_FREEZE, _freeze_payload())
    store.append(EVENT_TRIAL_RECORD, _trial_payload("t1", "cfg1", result_payload={"sharpe": 0.5}))
    store.append(EVENT_TRIAL_RECORD, _trial_payload("t2", "cfg2", result_payload={"sharpe": -0.2}))
    store.append(EVENT_OOS_WINDOW, {
        "family_id": "fam",
        "oos_window_id": "w1",
        "oos_generation": 1,
        "segment_start": "2020-01-01",
        "segment_end": "2020-12-31",
        "dataset_id": "ds",
        "dataset_hash": "d" * 64,
    })
    store.append(EVENT_DECISION_USE, _decision_payload("dec-replay"))

    reg = store.replay_trial_registry()
    assert reg.is_frozen("fam")
    t1 = reg.get_trial("fam", "t1")
    t2 = reg.get_trial("fam", "t2")
    assert t1 is not None and t2 is not None
    assert t1.config_hash == "cfg1"
    assert t2.config_hash == "cfg2"
    assert reg.get_oos_window("fam", "w1") is not None

    ledger = store.replay_decision_ledger()
    rows = ledger.for_decision("dec-replay")
    assert len(rows) == 1
    assert rows[0].verify()
    assert is_authentic_audit(rows[0])


def test_no_delete_surface(tmp_path):
    store = AppendOnlyStore(tmp_path / "gov.jsonl")
    assert not hasattr(store, "clear")
    assert not hasattr(store, "truncate")
    public = {n for n in dir(store) if not n.startswith("_")}
    banned = {"clear", "truncate", "delete", "reset", "rewrite", "remove", "pop"}
    assert banned.isdisjoint(public)


def test_authority_constant():
    assert AUTHORITY == "READ_ONLY_ADVISORY"
    assert len(GENESIS) == 64
    assert set(GENESIS) == {"0"}


def test_injectable_authority(tmp_path):
    auth = ReceiptAuthority(key=b"r6-test-key-32-bytes-long!!!!!!", issuer_id="r6-test")
    path = tmp_path / "gov.jsonl"
    store = AppendOnlyStore(path, authority=auth)
    store.append(EVENT_FAMILY_FREEZE, _freeze_payload())
    ev = store.events()[0]
    assert ev["issuer_id"] == "r6-test"
    assert store.verify_chain()[0] is True
    # Different authority cannot verify the chain.
    other = AppendOnlyStore(path, authority=ReceiptAuthority(key=b"other-key-32-bytes-long!!!!!!!!"))
    assert other.verify_chain()[0] is False


def test_r6_acceptance():
    state, detail = check_durable_store()
    assert state == GateState.PASS.value, detail
