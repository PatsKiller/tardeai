"""Maturity proof must not equate attempts or cleared notification sources with recovered output.

Only temporary file sources and the actual pure classifier are exercised. No host command,
provider, credentials, broker or production ledger is consulted. Current producers have no
trusted run/attempt/generation linkage, so there is deliberately no invented passing proof.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from scripts.lib.n8n_maturity import core
from scripts.lib.n8n_maturity import dims_healing as h

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 19, 3, 0, tzinfo=dt.timezone.utc)
LEGACY_PREDICATES = {
    "n8n_incident_fanin": {
        "description": "an incident observed recovering (recovered list non-empty) after routing",
        "field": "recovered",
        "nonempty": True,
        "min_count": 1,
    },
    "supervisor_recovery_ladder": {
        "description": "a recovery action actually executed (executed=true)",
        "field": "executed",
        "equals": True,
        "min_count": 1,
    },
}
OLD_READER_SOURCE = 'def load_inventory(probe: core.Probe, rel: str = INVENTORY_REL) -> "tuple[Optional[dict], Optional[str]]":\n    doc = probe.json(probe.proj / rel)\n    if not isinstance(doc, dict):\n        return None, f"inventory {rel} missing or not JSON"\n    if doc.get("schema") != INVENTORY_SCHEMA:\n        return None, f"inventory schema {doc.get(\'schema\')!r} != {INVENTORY_SCHEMA}"\n    if not isinstance(doc.get("mechanisms"), list) or not doc["mechanisms"]:\n        return None, "inventory has no mechanisms"\n    return doc, None'
OLD_READER_SHA256 = "9911ef7cf0c0b9d5565336c103abda10c453f8a682de02c62a772a7f8ea150b8"
UNRELATED44_SHA256 = "3bfd96937beb6a361ed52c6c23badb450ccc309f0d9c85d63c184c412e211786"


def inventory():
    return json.loads((ROOT / h.INVENTORY_REL).read_text())


def mechanism(mid, *, legacy=False):
    out = next(copy.deepcopy(m) for m in inventory()["mechanisms"] if m["id"] == mid)
    if legacy:
        out["success_predicate"] = copy.deepcopy(LEGACY_PREDICATES[mid])
    return out


def probe(tmp_path, *, proj=ROOT):
    def refuse_command(*_a, **_kw):
        raise AssertionError("a pure evidence classification must never run a host command")

    return core.Probe(
        root=tmp_path / "state",
        proj=proj,
        now=NOW,
        env={"HOME": str(tmp_path / "home")},
        config={},
        runner=refuse_command,
    )


def classify(tmp_path, mid, record, *, legacy=True, age_hours=0):
    p = probe(tmp_path)
    m = mechanism(mid, legacy=legacy)
    ev = m["evidence_source"]
    row = copy.deepcopy(record)
    row[ev["ts_key"]] = (NOW - dt.timedelta(hours=age_hours)).isoformat()
    path = p.root / ev["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n")
    return h.evaluate_mechanism(
        p,
        {"schema": "SelfHealingMechanisms@v1" if legacy else inventory()["schema"]},
        m,
        default_window_h=48,
        default_tail=1,
    )


def test_failed_restart_never_proves_recovery(tmp_path):
    r = classify(
        tmp_path,
        "supervisor_recovery_ladder",
        {
            "lane_id": "fixture-output",
            "breach_id": "fixture-breach",
            "executed": True,
            "attempted": True,
            "rc": 7,
            "action_succeeded": False,
            "business_recovered": False,
        },
    )
    assert r["state"] == h.RAN_NOT_HEALED, "a failed restart attempt is not recovered business output"
    assert r["successes_window"] == 0


def test_source_disappearance_never_proves_recovery(tmp_path):
    r = classify(
        tmp_path,
        "n8n_incident_fanin",
        {
            "mode": "dry-run",
            "recovered": [{"state": "DRY_RUN", "idempotency_key": "fixture-source-clear"}],
        },
    )
    assert r["state"] == h.RAN_NOT_HEALED, "dry source disappearance is not recovered business output"
    assert r["successes_window"] == 0


@pytest.mark.parametrize("outcome, expected", [("recovered", "PROVEN"), ("gave_up", "RAN_NOT_HEALED")])
def test_unrelated_retry_predicate_retains_meaning(tmp_path, outcome, expected):
    r = classify(tmp_path, "llm_call_retry_wrapper", {"outcome": outcome}, legacy=False)
    assert r["state"] == expected


@pytest.mark.parametrize("mid", sorted(LEGACY_PREDICATES))
@pytest.mark.parametrize("age", [0, -24, 72])
def test_unknown_future_stale_and_bare_success_are_unproven(tmp_path, mid, age):
    r = classify(
        tmp_path,
        mid,
        {
            "executed": True,
            "action_succeeded": True,
            "business_recovered": True,
            "mode": "apply",
            "recovered": [{"state": "CONSUMED"}],
            "recovery_evidence": {"run_id": "invented", "attempt": 1, "output_verdict": {"verdict": "produced"}},
        },
        legacy=False,
        age_hours=age,
    )
    assert r["state"] == h.RAN_NOT_HEALED
    assert r["successes"] == r["successes_window"] == 0
    assert "business_recovery_unproven" in r["note"]
    assert r["last_success_ts"] is None


def test_inventory_v2_preserves_all46_and_unrelated44():
    doc = inventory()
    assert doc["schema"] == "SelfHealingMechanisms@v2"
    assert len(doc["mechanisms"]) == 46
    unrelated = [m for m in doc["mechanisms"] if m["id"] not in LEGACY_PREDICATES]
    assert len(unrelated) == 44
    assert (
        hashlib.sha256(json.dumps(unrelated, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        == UNRELATED44_SHA256
    )
    assert h.inventory_problems(doc, ROOT) == []


def write_inventory(p, doc):
    target = p.proj / h.INVENTORY_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc))


def test_old_reader_refuses_new_major_producer(tmp_path):
    assert hashlib.sha256(OLD_READER_SOURCE.encode()).hexdigest() == OLD_READER_SHA256
    ns = {"core": core, "INVENTORY_SCHEMA": "SelfHealingMechanisms@v1", "INVENTORY_REL": h.INVENTORY_REL}
    exec(OLD_READER_SOURCE, ns)
    p = probe(tmp_path, proj=tmp_path / "old-reader")
    write_inventory(p, inventory())
    doc, reason = ns["load_inventory"](p)
    assert doc is None, "an old reader must hold rather than ignore the new recovery requirement"
    assert "schema" in reason


def test_new_reader_accepts_old_producer_but_holds_two_unsafe_predicates(tmp_path):
    legacy = inventory()
    legacy["schema"] = "SelfHealingMechanisms@v1"
    for m in legacy["mechanisms"]:
        if m["id"] in LEGACY_PREDICATES:
            m["success_predicate"] = copy.deepcopy(LEGACY_PREDICATES[m["id"]])
    p = probe(tmp_path, proj=tmp_path / "new-reader")
    write_inventory(p, legacy)
    doc, reason = h.load_inventory(p)
    assert doc is not None and reason is None
    for mid in LEGACY_PREDICATES:
        result = classify(tmp_path / mid, mid, {"executed": True, "recovered": [1]}, legacy=True)
        assert result["state"] == h.RAN_NOT_HEALED
        assert "business_recovery_unproven" in result["note"]


@pytest.mark.parametrize("schema", [None, "SelfHealingMechanisms@v3", "other@v2"])
def test_unsupported_inventory_versions_are_unavailable(tmp_path, schema):
    doc = inventory()
    doc["schema"] = schema
    p = probe(tmp_path, proj=tmp_path / "unsupported-reader")
    write_inventory(p, doc)
    loaded, reason = h.load_inventory(p)
    assert loaded is None and "schema" in reason


@pytest.mark.parametrize("change", ["unknown_field", "wrong_kind", "wrong_reason"])
def test_v2_blocked_predicate_is_closed_and_cannot_widen_proof(change):
    doc = inventory()
    m = next(m for m in doc["mechanisms"] if m["id"] == "supervisor_recovery_ladder")
    if change == "unknown_field":
        m["success_predicate"]["equals"] = True
    elif change == "wrong_kind":
        m["success_predicate"]["kind"] = "executed_is_recovered"
    else:
        m["success_predicate"]["blocked_reason"] = ""
    assert h.inventory_problems(doc, ROOT), "unsupported recovery semantics must be refused before scoring"
