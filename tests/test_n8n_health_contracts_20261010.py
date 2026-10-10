"""Workflow health contracts (N8nHealthContract@v1), operator 2026-10-10 ~16:45 ET.

"What is it supposed to do? What does it connect to? What does positive mean? What does degraded mean? What is it
measuring against if it doesn't know?" — every n8n lane and workflow answers those in
config/n8n_health_contracts.json, and scripts/check_n8n_health_contracts.py fails a lane that enters n8n without one.

Hermetic: synthetic registries and a tmp_path sqlite ledger; the committed-file tests read repo files only. No DB, no
n8n, no network, no send.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import build_n8n_health_contracts as B  # noqa: E402
from scripts import check_n8n_health_contracts as C  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402

TODAY = date(2026, 10, 10)
LIVE_LANES = ("n8n-incident-fanin", "n8n-pilot-dispatch", "n8n-research-intake-consumer",
              "crontab-snapshot-for-health-agent")
GENERIC = ("tradeai-approval-router", "tradeai-digest-scheduler", "tradeai-dispatcher", "tradeai-event-router",
           "tradeai-heartbeat-watcher", "tradeai-incident-router")


@pytest.fixture(scope="module")
def committed():
    return (H.load_json(H.CONTRACTS_PATH), H.load_json(H.REGISTRY_PATH), H.load_json(H.GENERIC_INDEX_PATH))


def _contract(doc, cid):
    return copy.deepcopy(next(c for c in doc["contracts"] if c["id"] == cid))


# ------------------------------------------------------------------------------------------- committed file


def test_committed_contracts_pass_the_gate(committed):
    doc, reg, idx = committed
    res = H.check(doc, reg, idx, today=TODAY)
    assert res["errors"] == [], res["errors"][:5]


def test_every_n8n_lane_workflow_and_host_monitor_has_a_contract(committed):
    doc, reg, idx = committed
    ids = {c["id"] for c in doc["contracts"]}
    assert set(LIVE_LANES) <= ids
    assert set(GENERIC) <= ids
    assert set(H.HOST_MONITOR_LANES) <= ids
    shadow = {r["lane_id"] for r in reg["lanes"]
              if (r.get("scheduler") or {}).get("stage") == "shadow" or "r1_pending" in r}
    assert len(shadow) >= 55 and shadow <= ids


def test_contracts_answer_the_five_questions(committed):
    doc, _reg, _idx = committed
    for c in doc["contracts"]:
        assert c["purpose"]["text"].strip(), c["id"]
        assert c["connects_to"], c["id"]
        assert c["healthy"] and c["degraded"] and c["failed"], c["id"]
        assert c["baseline"]["basis"] in H.BASELINE_BASES, c["id"]


def test_inferred_facts_are_marked_draft_and_free_text_edges_say_so(committed):
    doc, _reg, _idx = committed
    assert all(c["status"] in H.STATUSES for c in doc["contracts"])
    for c in doc["contracts"]:
        for e in c["connects_to"]:
            if e["kind"] == "inventory_text":
                assert "DRAFT" in e["source"], (c["id"], e)


def test_live_lanes_have_a_learned_baseline_only_from_enough_live_runs(committed):
    doc, _reg, _idx = committed
    for c in doc["contracts"]:
        b = c["baseline"]
        if b["basis"] == "LEARNED_PROVISIONAL":
            assert b["runs_considered"] >= H.MIN_LEARNED_RUNS and b["duration_p95_s"] >= b["duration_p50_s"]


def test_function_severity_mirrors_the_catalogue():
    from scripts.lib import n8n_remediation_catalogue as CAT

    assert B.FUNCTION_SEVERITY == dict(CAT.FUNCTION_SEVERITY)


def test_scalp_lane_contract_if_present_is_diagnosis_excluded(committed):
    doc, _reg, _idx = committed
    for c in doc["contracts"]:
        if c["id"] == "trade-ai-scalp-live":
            assert c["remediation"]["diagnosis_excluded"] is True


# ------------------------------------------------------------------------------------------------- the gate


def _registry_with(reg, row):
    r = copy.deepcopy(reg)
    r["lanes"].append(row)
    return r


NEW_ROW = {"lane_id": "zz-new-lane", "owner": "platform", "state": "ACTIVE", "expected_cadence_hours": 1.0,
           "scheduler": {"kind": "cron", "expression": "0 * * * *", "match": "scripts/zz.py", "stage": "shadow"},
           "output_signal": {"kind": "json_key", "path": "data/runtime/zz-new-lane_last.json", "key": "ok_at"},
           "dispatch": {"mode": "dry_run", "class": "report"}}


def test_a_new_shadow_lane_without_a_contract_fails(committed):
    doc, reg, idx = committed
    res = H.check(doc, _registry_with(reg, NEW_ROW), idx, today=TODAY)
    assert any(e.startswith("MISSING_CONTRACT zz-new-lane") for e in res["errors"])


def test_a_new_lane_with_a_draft_contract_fails_until_reviewed(committed):
    doc, reg, idx = committed
    d = copy.deepcopy(doc)
    c = _contract(doc, "fee-efficiency-analyzer")
    c["id"] = "zz-new-lane"
    d["contracts"].append(c)
    reg2 = _registry_with(reg, NEW_ROW)
    assert any(e.startswith("DRAFT_NOT_GRANDFATHERED zz-new-lane") for e in H.check(d, reg2, idx, TODAY)["errors"])
    c["status"] = "REVIEWED"
    assert not [e for e in H.check(d, reg2, idx, TODAY)["errors"] if "zz-new-lane" in e]


def test_canary_needs_a_reviewed_contract_without_unknowns(committed):
    doc, reg, idx = committed
    reg2 = copy.deepcopy(reg)
    row = next(r for r in reg2["lanes"] if r["lane_id"] == "fee-efficiency-analyzer")
    row["scheduler"]["stage"] = "canary"
    assert any(e.startswith("DRAFT_AT_LIVE_STAGE fee-efficiency-analyzer") for e in
               H.check(doc, reg2, idx, TODAY)["errors"])
    d = copy.deepcopy(doc)
    c = next(c for c in d["contracts"] if c["id"] == "fee-efficiency-analyzer")
    c["status"] = "REVIEWED"
    c["upstream_note"] = "UNKNOWN — needs owner"
    assert any("DRAFT_AT_LIVE_STAGE" in e for e in H.check(d, reg2, idx, TODAY)["errors"])


@pytest.mark.parametrize("field", ["healthy", "degraded", "failed", "connects_to"])
def test_empty_criteria_or_edges_are_invalid(committed, field):
    doc, _reg, _idx = committed
    c = _contract(doc, "fee-efficiency-analyzer")
    c[field] = []
    assert any(field in e for e in H.validate_contract(c))


def test_a_baseline_needs_a_basis_and_a_provisional_one_a_review_date(committed):
    doc, _reg, _idx = committed
    c = _contract(doc, "fee-efficiency-analyzer")
    c["baseline"]["basis"] = ""
    assert any("baseline.basis" in e for e in H.validate_contract(c))
    c = _contract(doc, "fee-efficiency-analyzer")
    c["review_by"] = ""
    assert any("review_by" in e for e in H.validate_contract(c))


def test_an_orphan_lane_contract_fails(committed):
    doc, reg, idx = committed
    d = copy.deepcopy(doc)
    c = _contract(doc, "fee-efficiency-analyzer")
    c["id"] = "zz-ghost"
    d["contracts"].append(c)
    d["grandfathered_draft"] = list(d["grandfathered_draft"]) + ["zz-ghost"]
    assert any(e.startswith("ORPHAN_CONTRACT zz-ghost") for e in H.check(d, reg, idx, TODAY)["errors"])


def test_cli_exit_codes(tmp_path, committed):
    doc, _reg, _idx = committed
    assert C.main([]) == 0
    bad = copy.deepcopy(doc)
    bad["contracts"] = [c for c in bad["contracts"] if c["id"] != "tradeai-dispatcher"]
    p = tmp_path / "c.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    assert C.main(["--contracts", str(p)]) == 1
    assert C.main(["--contracts", str(tmp_path / "missing.json")]) == 2


# ---------------------------------------------------------------------------------------------- the builder


def _ledger(path: Path, lane: str, n: int, state: str = "RUN_DONE") -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
                 "duration_s REAL, attempt INTEGER)")
    for i in range(n):
        conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                     (f"r{i}", lane, "live", state, f"2026-10-10T00:{i:02d}:00", 1.0 + i, 1))
    conn.execute("INSERT INTO runs VALUES ('d','%s','dry_run','RUN_DONE','2026-10-10T01:00:00',99,1)" % lane)
    conn.commit()
    conn.close()
    return path


def test_baseline_is_learned_from_fourteen_live_runs_and_never_from_dry_runs(tmp_path):
    runs = B.ledger_runs(_ledger(tmp_path / "l.sqlite", "x", 14), "x")
    assert len(runs) == 14 and all(r["mode"] == "live" for r in runs)
    b = B.baseline(runs, cadence_h=0.25, timeout_s=180, cls="report", as_of=TODAY)
    assert b["basis"] == "LEARNED_PROVISIONAL" and b["duration_p50_s"] == 7.5 and b["freshness_degraded_after_h"] == 0.5
    b13 = B.baseline(runs[:13], cadence_h=0.25, timeout_s=180, cls="report", as_of=TODAY)
    assert b13["basis"] == "CLASS_DEFAULT_PROVISIONAL" and b13["duration_degraded_above_s"] == 144.0


def test_builder_never_invents_a_purpose(committed):
    _doc, reg, _idx = committed
    row = copy.deepcopy(NEW_ROW)
    c = B.lane_contract("zz-new-lane", "stage:shadow", row, None, None, None, frozenset(), [], TODAY)
    assert c["purpose"]["text"] == H.UNKNOWN and c["status"] == "DRAFT"
    assert H.unknown_fields(c)


def test_builder_keeps_reviewed_contracts_and_does_not_grandfather_new_lanes(committed):
    doc, reg, idx = committed
    existing = copy.deepcopy(doc)
    rev = next(c for c in existing["contracts"] if c["id"] == "fee-efficiency-analyzer")
    rev["status"] = "REVIEWED"
    rev["purpose"]["text"] = "owner-reviewed text"
    out = B.build(registry=_registry_with(reg, NEW_ROW), allowlist={"lanes": []}, catalogue={"lanes": []},
                  inventory={}, index=idx, ledger=None, excluded=frozenset(), as_of=TODAY, existing=existing)
    kept = next(c for c in out["contracts"] if c["id"] == "fee-efficiency-analyzer")
    assert kept["purpose"]["text"] == "owner-reviewed text"
    assert "zz-new-lane" not in out["grandfathered_draft"]
    assert any(e.startswith("DRAFT_NOT_GRANDFATHERED zz-new-lane") for e in
               H.check(out, _registry_with(reg, NEW_ROW), idx, TODAY)["errors"])


def test_builder_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "contracts.json"
    assert B.main(["--dry-run", "--no-ledger", "--as-of", "2026-10-10", "--out", str(out)]) == 0
    assert not out.exists()
