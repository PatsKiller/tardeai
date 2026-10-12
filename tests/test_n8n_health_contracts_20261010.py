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
import subprocess
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
LIVE_LANES = (
    "n8n-incident-fanin",
    "n8n-pilot-dispatch",
    "n8n-research-intake-consumer",
    "crontab-snapshot-for-health-agent",
)
GENERIC = (
    "tradeai-approval-router",
    "tradeai-digest-scheduler",
    "tradeai-dispatcher",
    "tradeai-event-router",
    "tradeai-heartbeat-watcher",
    "tradeai-incident-router",
)


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
    shadow = {
        r["lane_id"] for r in reg["lanes"] if (r.get("scheduler") or {}).get("stage") == "shadow" or "r1_pending" in r
    }
    # 55 shadow rows on 2026-10-10 (waves 1-3); #1674 (C1) moved hermes-config-governor into the hermes_learning
    # stage (dispatch_retired), leaving 54. W4 (2026-10-11) added 3 provider owners (57); the C1 premarket flip
    # (2026-10-11) moved 17 rows into premarket-data-pipeline (dispatch_retired), leaving 40. Every remaining shadow
    # row must still carry a contract.
    assert len(shadow) >= 40 and shadow <= ids


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


NEW_ROW = {
    "lane_id": "zz-new-lane",
    "owner": "platform",
    "state": "ACTIVE",
    "expected_cadence_hours": 1.0,
    "scheduler": {"kind": "cron", "expression": "0 * * * *", "match": "scripts/zz.py", "stage": "shadow"},
    "output_signal": {"kind": "json_key", "path": "data/runtime/zz-new-lane_last.json", "key": "ok_at"},
    "dispatch": {"mode": "dry_run", "class": "report"},
}


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
    assert any(
        e.startswith("DRAFT_AT_LIVE_STAGE fee-efficiency-analyzer") for e in H.check(doc, reg2, idx, TODAY)["errors"]
    )
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
    conn.execute(
        "CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
        "duration_s REAL, attempt INTEGER)"
    )
    for i in range(n):
        conn.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
            (f"r{i}", lane, "live", state, f"2026-10-10T00:{i:02d}:00", 1.0 + i, 1),
        )
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
    out = B.build(
        registry=_registry_with(reg, NEW_ROW),
        allowlist={"lanes": []},
        catalogue={"lanes": []},
        inventory={},
        index=idx,
        ledger=None,
        excluded=frozenset(),
        as_of=TODAY,
        existing=existing,
    )
    kept = next(c for c in out["contracts"] if c["id"] == "fee-efficiency-analyzer")
    assert kept["purpose"]["text"] == "owner-reviewed text"
    assert "zz-new-lane" not in out["grandfathered_draft"]
    assert any(
        e.startswith("DRAFT_NOT_GRANDFATHERED zz-new-lane")
        for e in H.check(out, _registry_with(reg, NEW_ROW), idx, TODAY)["errors"]
    )


def test_builder_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "contracts.json"
    assert B.main(["--dry-run", "--no-ledger", "--as-of", "2026-10-10", "--out", str(out)]) == 0
    assert not out.exists()


# Baseline regeneration uses public source declarations, not production observations.


def _workflow_fixture(wid, expression="*/5 * * * *", timeout=50):
    return {
        "id": wid,
        "settings": {"executionTimeout": timeout, "timezone": "America/New_York"},
        "nodes": [
            {
                "type": "n8n-nodes-base.scheduleTrigger",
                "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": expression}]}},
            }
        ],
    }


@pytest.mark.parametrize(
    "expression,timeout,degraded,failed",
    [
        ("* * * * *", 50, 0.033, 0.05),
        ("*/5 * * * *", 50, 0.167, 0.25),
        ("*/5 * * * *", 150, 0.167, 0.25),
    ],
)
def test_generic_builder_derives_bounded_provisional_defaults_from_graph(expression, timeout, degraded, failed):
    wf = {"id": "fixture-dispatcher", "kind": "dispatcher", "relay_calls": ["GET /due", "POST /run"]}
    contract = B.generic_contract(wf, TODAY, workflow_source=_workflow_fixture(wf["id"], expression, timeout))
    baseline = contract["baseline"]
    assert (baseline["timeout_s"], baseline["freshness_degraded_after_h"], baseline["freshness_failed_after_h"]) == (
        timeout,
        degraded,
        failed,
    )
    assert baseline["basis"] == "CLASS_DEFAULT_PROVISIONAL" and baseline["runs_considered"] is None
    assert "NOT_MEASURED" in baseline["source"]
    assert contract["status"] == "DRAFT"
    assert H.validate_contract(contract) == []


def test_generic_builder_never_invents_missing_or_invalid_source_limits():
    wf = {"id": "fixture-dispatcher", "kind": "dispatcher", "relay_calls": ["GET /due"]}
    for source in ({}, _workflow_fixture(wf["id"], "not a recurring cron", 0)):
        contract = B.generic_contract(wf, TODAY, workflow_source=source)
        assert contract["baseline"]["timeout_s"] is None
        assert contract["baseline"]["freshness_degraded_after_h"] is None
        assert contract["baseline"]["freshness_failed_after_h"] is None
        assert "Collect" in contract["baseline"]["collection_action"]
        assert contract["status"] == "DRAFT"


@pytest.mark.parametrize(
    "lane,timeout", [("incident-notifier", 120), ("n8n-failure-diagnosis", 600), ("n8n-siem-bridge", 120)]
)
def test_host_builder_uses_public_install_line_timeout_without_db(lane, timeout, committed, monkeypatch):
    _, registry, _ = committed
    row = next(row for row in registry["lanes"] if row["lane_id"] == lane)
    monkeypatch.setattr(B.sqlite3, "connect", lambda *a, **k: pytest.fail("pure host generation opened a DB"))
    contract = B.host_contract(lane, row, TODAY)
    assert contract["baseline"]["timeout_s"] == timeout
    assert contract["baseline"]["freshness_degraded_after_h"] == round(2 * row["expected_cadence_hours"], 3)
    assert contract["baseline"]["freshness_failed_after_h"] == round(3 * row["expected_cadence_hours"], 3)
    assert contract["baseline"]["runs_considered"] is None
    assert contract["status"] == "DRAFT"


def _build_public_catalogue(doc, registry, index):
    return B.build(
        registry=registry,
        allowlist=H.load_json(B.ALLOWLIST_PATH),
        catalogue=H.load_json(B.CATALOGUE_PATH),
        inventory={},
        index=index,
        ledger=None,
        excluded=frozenset(),
        as_of=date(2026, 10, 12),
        existing=doc,
    )


def test_regeneration_preserves_corrected_draft_limits_history_and_owner(committed, monkeypatch):
    doc, registry, index = committed
    original = copy.deepcopy(doc)
    monkeypatch.setattr(B.sqlite3, "connect", lambda *a, **k: pytest.fail("no-ledger generation opened a DB"))
    out = _build_public_catalogue(doc, registry, index)
    by_id = {row["id"]: row for row in out["contracts"]}
    affected = (*GENERIC, *H.HOST_MONITOR_LANES)
    assert len(affected) == 9
    for previous in (row for row in doc["contracts"] if row["id"] in affected):
        generated = by_id[previous["id"]]
        assert generated["baseline"] == previous["baseline"]
        assert generated["owner"] == previous["owner"]
        assert generated["status"] == previous["status"]
        old_review, new_review = copy.deepcopy(previous.get("review")), copy.deepcopy(generated.get("review"))
        if isinstance(old_review, dict):
            old_review.pop("proposed_contract_body_sha256", None)
            new_review.pop("proposed_contract_body_sha256", None)
        assert new_review == old_review
    assert doc == original
    assert out["grandfathered_draft"] == sorted(original["grandfathered_draft"])


def test_builder_keeps_entire_reviewed_rows_observer_and_retired_history(committed):
    doc, registry, index = committed
    original_registry = copy.deepcopy(registry)
    out = _build_public_catalogue(doc, registry, index)
    by_id = {row["id"]: row for row in out["contracts"]}
    assert set(by_id) == {row["id"] for row in doc["contracts"]}
    for reviewed in (row for row in doc["contracts"] if row["status"] == "REVIEWED"):
        assert by_id[reviewed["id"]] == reviewed
    assert by_id["tradeai-momentum-lifecycle-candidate"] == _contract(doc, "tradeai-momentum-lifecycle-candidate")
    assert "tradeai-momentum-lifecycle-candidate" not in {row["lane_id"] for row in registry["lanes"]}
    assert registry == original_registry


def test_draft_owner_numbers_and_review_history_cannot_be_replaced_by_defaults():
    previous = {
        "id": "fixture-dispatcher",
        "kind": "generic_workflow",
        "status": "DRAFT",
        "owner": "fixture-owner",
        "ownership_confirmation": "NOT_MEASURED",
        "baseline": {
            "basis": "OPERATOR_SLO",
            "timeout_s": 123,
            "freshness_degraded_after_h": 63.25,
            "freshness_failed_after_h": 63.5,
        },
        "review": {
            "status": "PENDING_BODY_REVIEW",
            "previous_review": {"metadata": {"decision_ref": "fixture://historical"}},
            "proposed_contract_body_sha256": "stale-proposal",
        },
    }
    wf = {"id": previous["id"], "kind": "dispatcher", "relay_calls": ["GET /due"]}
    out = B.build(
        registry={"lanes": []},
        allowlist={"lanes": []},
        catalogue={"lanes": []},
        inventory={},
        index={"workflows": [wf]},
        ledger=None,
        excluded=frozenset(),
        as_of=TODAY,
        existing={"contracts": [previous], "grandfathered_draft": []},
        workflow_sources={wf["id"]: _workflow_fixture(wf["id"], "* * * * *", 50)},
    )["contracts"][0]
    from scripts.lib.n8n_momentum_lifecycle import contract_body_digest, contract_review_proven

    assert out["baseline"] == previous["baseline"]
    assert out["owner"] == "fixture-owner" and out["ownership_confirmation"] == "NOT_MEASURED"
    assert out["review"]["previous_review"] == previous["review"]["previous_review"]
    assert out["review"]["proposed_contract_body_sha256"] == contract_body_digest(out)
    assert out["status"] == "DRAFT" and not contract_review_proven(out)


def test_explicit_no_ledger_write_to_owned_fixture_retains_limits_and_review_history(tmp_path, committed):
    doc, _, _ = committed
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps(doc))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_n8n_health_contracts.py"),
            "--write",
            "--no-ledger",
            "--as-of",
            "2026-10-12",
            "--out",
            str(path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ledger_present"] is False
    written = json.loads(path.read_text())
    for cid in (*GENERIC, *H.HOST_MONITOR_LANES):
        before, after = _contract(doc, cid), _contract(written, cid)
        assert after["baseline"] == before["baseline"]
        assert after["owner"] == before["owner"]
        assert after["status"] == before["status"]
    assert {row["id"] for row in written["contracts"]} == {row["id"] for row in doc["contracts"]}
