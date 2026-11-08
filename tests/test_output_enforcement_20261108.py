"""LQ-20261107-1004 (Fable audit LQ-984 #7, Q3.1-3.3): close the output false-green paths.

* an ``empty_allowed`` verdict must cite an upstream count from the receipt (``upstream_count_field``), else the
  contract that names the field fails the run, and an uncited empty is a gap;
* ``declared_not_enforced`` and an uncited empty fail after the 72 h grace (``enforcement_decision``);
* scripts/ops/output_enforcement_plan.py lists the lanes that will turn red and proposes a stronger signal for every
  ACTIVE file_mtime lane. Synthetic lanes only: no holdings, no keys, no host paths.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_n8n_workflow_framework as fw  # noqa: E402
from scripts.lib import n8n_output_verdict as ov  # noqa: E402
from scripts.ops import output_enforcement_plan as oep  # noqa: E402

T = "2026-11-08T12:00:00+00:00"


def _rule(**extra):
    return {"schema": ov.EXPECTED_OUTPUT_SCHEMA, "unit": "rows", "rule": "empty_allowed", "produced_field":
            "produced_count", "fatal_skip_reasons": ["source_down"], "empty_allowed_reasons": ["no_new_input"],
            "evidence": [{"kind": "receipt_field", "ref": "produced_count"}]} | extra


def _doc(**extra):
    return {"schema": ov.LANE_RECEIPT_V2, "run_id": "r1", "lane_id": "lane-a", "produced_count": 0,
            "attempted_count": 0, "skipped_reasons": {}, "status": "ok", "mode": "live", "run_mode": "live",
            "finished_at": T, "ok_at": T, "empty_reason": "no_new_input"} | extra


def _eval(rule, doc):
    return ov.evaluate(rule, doc, run_id="r1", lane_id="lane-a", mode="live")


POLICY = {"schema": ov.ENFORCEMENT_SCHEMA, "grace_hours": 72, "grace_starts_at": "2026-11-10T22:00:00+00:00"}


# ── upstream citation ────────────────────────────────────────────────────


def test_an_empty_with_its_upstream_count_is_cited():
    v = _eval(_rule(upstream_count_field="rows_seen"), _doc(rows_seen=41))
    assert v["verdict"] == "empty_allowed" and v["upstream_cited"] is True and v["upstream_count"] == 41
    assert ov.gap_of(v) is None


def test_a_zero_upstream_count_is_still_a_citation():
    v = _eval(_rule(upstream_count_field="rows_seen"), _doc(rows_seen=0))
    assert v["verdict"] == "empty_allowed" and v["upstream_count"] == 0


@pytest.mark.parametrize("bad", [None, "41", -1, True, 4.0])
def test_a_named_upstream_count_that_is_missing_or_malformed_fails_the_run(bad):
    doc = _doc() if bad is None else _doc(rows_seen=bad)
    v = _eval(_rule(upstream_count_field="rows_seen"), doc)
    assert v["verdict"] == "unverifiable" and v["why"] == "upstream_count_missing"
    assert ov.FAILING[v["verdict"]] == "output_unverifiable"


def test_the_upstream_count_may_live_in_the_receipt_summary():
    v = _eval(_rule(upstream_count_field="summary.checked_count"), _doc(summary={"checked_count": 7}))
    assert v["upstream_cited"] is True and v["upstream_count"] == 7


def test_an_empty_without_a_named_field_is_allowed_but_uncited():
    v = _eval(_rule(), _doc())
    assert v["verdict"] == "empty_allowed" and v["upstream_cited"] is False
    assert ov.gap_of(v) == "empty_uncited"


@pytest.mark.parametrize("field,ok", [("rows_seen", True), ("summary.checked_count", True),
                                      ("produced_count", False), ("a.b.c.d", False), ("Rows", False), (3, False)])
def test_the_upstream_field_is_a_validated_name(field, ok):
    probs = ov.validate_expected_output(_rule(upstream_count_field=field))
    assert (probs == []) is ok, probs


def test_the_framework_checker_accepts_the_new_key():
    assert "upstream_count_field" in fw.EXPECTED_OUTPUT_KEYS


# ── grace-gated enforcement ──────────────────────────────────────────────


def test_no_gap_is_never_enforced():
    d = ov.enforcement_decision({"verdict": "produced"}, POLICY, now="2026-12-01T00:00:00+00:00")
    assert d["phase"] == "none" and d["failing_reason"] is None


def test_declared_not_enforced_warns_inside_the_grace_and_fails_after():
    v = {"verdict": "declared_not_enforced"}
    before = ov.enforcement_decision(v, POLICY, now="2026-11-13T21:59:59+00:00")
    at = ov.enforcement_decision(v, POLICY, now="2026-11-13T22:00:00+00:00")
    assert before == {"gap": "declared_not_enforced", "phase": "grace", "deadline": "2026-11-13T22:00:00+00:00",
                      "failing_reason": None}
    assert at["phase"] == "enforced" and at["failing_reason"] == "output_not_enforced"


def test_an_uncited_empty_fails_after_the_grace():
    v = _eval(_rule(), _doc())
    d = ov.enforcement_decision(v, POLICY, now="2026-11-14T00:00:00+00:00")
    assert d["gap"] == "empty_uncited" and d["failing_reason"] == "empty_upstream_uncited"


@pytest.mark.parametrize("policy", [None, {}, POLICY | {"grace_starts_at": None},
                                    POLICY | {"grace_starts_at": "2026-11-10T22:00:00"}, POLICY | {"grace_hours": -1},
                                    POLICY | {"extra": 1}])
def test_a_broken_policy_never_buys_grace(policy):
    d = ov.enforcement_decision({"verdict": "declared_not_enforced"}, policy, now="2026-11-01T00:00:00+00:00")
    assert d["phase"] == "enforced" and d["failing_reason"] == "output_not_enforced" and d["policy_problems"]


def test_the_repo_policy_is_valid_and_72_hours():
    doc = json.loads((ROOT / "config/n8n_output_enforcement.json").read_text())
    assert ov.validate_enforcement_policy(doc) == [] and doc["grace_hours"] == 72


# ── the plan: who turns red, and the file_mtime proposals ─────────────────


def _ov_json(v: dict) -> str:
    return json.dumps({"output_verdict": v})


def _tree(tmp: Path, *, ledger: bool = True) -> tuple[Path, Path]:
    root, state = tmp / "tree", tmp / "state"
    (root / "config").mkdir(parents=True)
    contracts = {"contracts": [
        {"id": "lane-dne", "kind": "lane", "expected_output": _rule(rule="min_produced", min_produced=1)},
        {"id": "lane-empty", "kind": "lane", "expected_output": _rule()},
        {"id": "lane-cited", "kind": "lane", "expected_output": _rule(upstream_count_field="rows_seen")},
        {"id": "lane-store", "kind": "lane", "expected_output": _rule(evidence=[
            {"kind": "store_rows", "ref": "Postgres widget_rows INSERT scripts/widget.py:10"}])},
    ]}
    allow = {"lanes": [{"lane_id": "lane-v2", "output_receipt": "v2"}]}
    reg = {"lanes": [
        {"lane_id": "lane-v2", "state": "ACTIVE", "output_signal": {"kind": "file_mtime", "path": "logs/v2.log"}},
        {"lane_id": "lane-json", "state": "ACTIVE",
         "output_signal": {"kind": "file_mtime", "path": "data/runtime/widget.json"}},
        {"lane_id": "lane-store", "state": "ACTIVE", "output_signal": {"kind": "file_mtime", "path": "logs/s.log"}},
        {"lane_id": "lane-log", "state": "ACTIVE", "output_signal": {"kind": "file_mtime", "path": "logs/x.log"}},
        {"lane_id": "lane-db", "state": "ACTIVE", "output_signal": {"kind": "db_max", "table": "t", "column": "c"}},
        {"lane_id": "lane-gone", "state": "RETIRED", "output_signal": {"kind": "file_mtime", "path": "logs/g.log"}},
    ]}
    for rel, doc in ((oep.CONTRACTS_REL, contracts), (oep.ALLOWLIST_REL, allow), (oep.REGISTRY_REL, reg)):
        (root / rel).write_text(json.dumps(doc))
    (root / oep.POLICY_REL).write_text(json.dumps(POLICY))
    (state / "data/runtime").mkdir(parents=True)
    (state / "data/runtime/widget.json").write_text(json.dumps({"generated_at": T, "rows": 3}))
    att = state / oep.ATTEMPTS_REL / "lane-empty"
    att.mkdir(parents=True)
    (att / "r9.json").write_text(json.dumps({"produced_count": 0, "summary": {"checked_count": 12, "done": 0}}))
    if ledger:
        db = state / oep.rrt.LEDGER_REL
        db.parent.mkdir(parents=True)
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE runs (lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, receipt_json TEXT)")
        uncited = {"verdict": "empty_allowed", "empty_reason": "no_new_input"}
        conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?)", [
            ("lane-dne", "live", "RUN_DONE", "2026-11-08T10:00:00+00:00", _ov_json({"verdict":
                                                                                     "declared_not_enforced"})),
            ("lane-empty", "live", "RUN_DONE", "2026-11-08T10:00:00+00:00", _ov_json(uncited)),
            ("lane-empty", "live", "RUN_DONE", "2026-11-08T11:00:00+00:00", _ov_json({"verdict": "produced"})),
            ("lane-cited", "live", "RUN_DONE", "2026-11-08T10:00:00+00:00", _ov_json(uncited)),
            ("lane-ok", "live", "RUN_DONE", "2026-11-08T10:00:00+00:00", _ov_json({"verdict": "produced"})),
            ("lane-dry", "dry_run", "RUN_DONE", "2026-11-08T10:00:00+00:00", _ov_json(
                {"verdict": "declared_not_enforced"})),
            ("lane-old", "live", "RUN_DONE", "2026-10-01T10:00:00+00:00", _ov_json(
                {"verdict": "declared_not_enforced"})),
        ])
        conn.commit()
        conn.close()
    return root, state


def _main(root, state, *extra):
    return oep.main(["--root", str(root), "--state-root", str(state), "--now", T, *extra])


def test_the_red_list_is_exactly_the_unproven_live_lanes(tmp_path, capsys):
    root, state = _tree(tmp_path)
    out = tmp_path / "plan.json"
    assert _main(root, state, "--out", str(out)) == 0
    capsys.readouterr()
    doc = json.loads(out.read_text())
    red = {(r["lane_id"], r["gap"]): r for r in doc["red"]}
    assert set(red) == {("lane-dne", "declared_not_enforced"), ("lane-empty", "empty_uncited")}
    assert red[("lane-dne", "declared_not_enforced")]["failing_reason"] == "output_not_enforced"
    assert red[("lane-empty", "empty_uncited")]["upstream_candidates"] == ["summary.checked_count"]
    assert all(r["red_from"] == "2026-11-13T22:00:00+00:00" for r in doc["red"])
    assert doc["verdict_totals"] == {"declared_not_enforced": 1, "empty_allowed": 2, "produced": 2}


def test_file_mtime_lanes_get_the_strongest_signal_their_artifacts_support(tmp_path, capsys):
    root, state = _tree(tmp_path)
    out = tmp_path / "plan.json"
    _main(root, state, "--out", str(out))
    capsys.readouterr()
    fm = {r["lane_id"]: r["proposed"] for r in json.loads(out.read_text())["file_mtime"]["lanes"]}
    assert fm == {
        "lane-v2": {"kind": "json_key", "path": "data/runtime/lane-v2_last.json", "key": "ok_at"},
        "lane-json": {"kind": "json_key", "path": "data/runtime/widget.json", "key": "generated_at"},
        "lane-store": {"kind": "db_max", "table": "widget_rows", "column": None},
        "lane-log": None,
    }


def test_an_unreadable_ledger_is_not_measured_never_an_empty_red_list(tmp_path, capsys):
    root, state = _tree(tmp_path, ledger=False)
    assert _main(root, state) == 2
    shown = json.loads(capsys.readouterr().out)
    assert shown["red_counts"] is None and shown["ledger"]["status"] == "unavailable"


def test_the_dry_run_writes_nothing(tmp_path, capsys):
    root, state = _tree(tmp_path)
    before = sorted(p for p in tmp_path.rglob("*"))
    _main(root, state)
    assert json.loads(capsys.readouterr().out)["wrote"] == []
    assert sorted(p for p in tmp_path.rglob("*")) == before
