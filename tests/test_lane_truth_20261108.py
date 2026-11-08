"""LQ-20261107-1003 step 3 — scripts/ops/lane_truth.py, the five-source reconciler (LaneTruth@v1).

A synthetic tree (made-up lanes, no holdings, no keys, no host paths) with a crontab file, an n8n snapshot and a
ledger SQLite. Proves: a host line no lane claims FAILs; an effect-claim line is attributed; a missing source is
NOT_MEASURED (exit 2), never PASS; PASS carries rows_read and an empty_reason; dry run writes nothing.
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

from scripts.ops import lane_truth as lt  # noqa: E402

NOW = "2026-11-08T12:00:00+00:00"
LEDGER_REL = Path("data/governance/n8n_coordination_ledger.sqlite")

REGISTRY = {
    "schema": "LaneRegistry@v1",
    "lanes": [
        {"lane_id": "alpha-sweep", "owner": "platform", "state": "ACTIVE",
         "scheduler": {"kind": "cron", "expression": "0 * * * *", "match": "scripts/alpha_sweep.py --apply"},
         "expected_cadence_hours": 1, "output_signal": {"kind": "db_max", "table": "alpha", "column": "ts"}},
        {"lane_id": "beta-brief", "owner": "research", "state": "ACTIVE",
         "scheduler": {"kind": "cron", "expression": "30 9 * * 1-5", "match": "scripts/beta_brief.py"},
         "dispatch": {"mode": "live", "cron": ["30 9 * * 1-5"], "tz": "America/New_York"},
         "expected_cadence_hours": 24, "output_signal": {"kind": "receipt", "path": "data/runtime/beta.json"}},
        {"lane_id": "gamma-old", "owner": "platform", "state": "RETIRED",
         "scheduler": {"kind": "cron", "expression": "0 2 * * *", "match": "scripts/gamma_old.py"},
         "expected_cadence_hours": 24, "output_signal": {"kind": "none"}},
    ],
}
ALLOWLIST = {"schema": "N8nRunAllowlist@v1", "lanes": [
    {"lane_id": "beta-brief", "command": ["$PY", "scripts/beta_brief.py"], "market_gate": True,
     "output_signal": "data/runtime/beta.json"}]}
CONTRACTS = {"contracts": []}
ALPHA_LINE = ("0 * * * * cd $PROJ && env TRADEAI_EFFECT_CLAIM=alpha-sweep bash scripts/effect_claim_cron.sh "
              "alpha-sweep $CURRENT/.venv/bin/python scripts/alpha_sweep.py --apply")
STRAY_LINE = "*/10 * * * * cd $PROJ && $CURRENT/.venv/bin/python scripts/stray_job.py"


def _tree(tmp: Path, *, cron_lines, ledger_rows=(("beta-brief", "live", "RUN_DONE", "2026-11-07T13:30:00+00:00"),),
          ledger=True, workflows=("tradeai-dispatcher",)) -> dict:
    root, state = tmp / "tree", tmp / "state"
    (root / "config").mkdir(parents=True)
    for name, doc in (("lane_registry.json", REGISTRY), ("n8n_run_allowlist.json", ALLOWLIST),
                      ("n8n_health_contracts.json", CONTRACTS)):
        (root / "config" / name).write_text(json.dumps(doc), encoding="utf-8")
    cron = tmp / "crontab.txt"
    cron.write_text("# header\nSHELL=/bin/bash\n" + "\n".join(cron_lines) + "\n", encoding="utf-8")
    snap = tmp / "n8n.json"
    snap.write_text(json.dumps([{"id": f"w{i}", "name": n, "active": True} for i, n in enumerate(workflows)]))
    if ledger:
        db = state / LEDGER_REL
        db.parent.mkdir(parents=True)
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE runs (lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT)")
        conn.executemany("INSERT INTO runs VALUES (?,?,?,?)", ledger_rows)
        conn.commit()
        conn.close()
    return {"root": root, "state": state, "cron": cron, "snap": snap}


def _run(t: dict, *extra: str) -> tuple[int, dict]:
    return lt.main(["--root", str(t["root"]), "--state-root", str(t["state"]), "--crontab-file", str(t["cron"]),
                    "--n8n-snapshot", str(t["snap"]), "--now", NOW, "--full", *extra]), None


def _out(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_clean_sources_pass_with_rows_read_and_empty_reason(tmp_path, capsys):
    t = _tree(tmp_path, cron_lines=[ALPHA_LINE])
    rc, _ = _run(t)
    v = _out(capsys)
    assert rc == 0 and v["verdict"] == "PASS", v["reason"]
    assert v["empty_reason"] and v["not_measured"] == []
    assert v["rows_read"] == {"registry": 3, "allowlist": 1, "contracts": 0, "crontab": 1, "n8n_db": 1, "ledger": 1}
    assert v["mode"].startswith("dry-run") and v["wrote"] == []
    assert not (t["state"] / lt.OUT_REL).exists()


def test_a_host_line_no_lane_claims_fails(tmp_path, capsys):
    t = _tree(tmp_path, cron_lines=[ALPHA_LINE, STRAY_LINE])
    rc, _ = _run(t, "--strict")
    v = _out(capsys)
    assert rc == 1 and v["verdict"] == "FAIL"
    und = [f for f in v["error_findings"] if f["code"] == "UNDECLARED_CRON_LINE"]
    assert len(und) == 1 and und[0]["evidence"]["scripts"] == ["scripts/stray_job.py"]
    assert "stray_job" not in und[0]["evidence"]["line"]  # the report names a hash, never the host line


def test_effect_claim_attribution_is_what_keeps_alpha_clean(tmp_path, capsys):
    t = _tree(tmp_path, cron_lines=[])
    _run(t)
    v = _out(capsys)
    assert v["verdict"] == "FAIL"
    assert [f["lane_id"] for f in v["error_findings"]] == ["alpha-sweep"]
    assert v["error_findings"][0]["code"] == "ACTIVE_CRON_NO_LINE"


def test_retired_lane_still_firing_and_still_running_fails(tmp_path, capsys):
    line = "0 2 * * * cd $PROJ && $CURRENT/.venv/bin/python scripts/gamma_old.py"
    t = _tree(tmp_path, cron_lines=[ALPHA_LINE, line],
              ledger_rows=(("beta-brief", "live", "RUN_DONE", "2026-11-07T13:30:00+00:00"),
                           ("gamma-old", "live", "RUN_DONE", "2026-11-08T02:00:00+00:00")))
    _run(t)
    v = _out(capsys)
    assert v["counts_by_code"]["RETIRED_STILL_ARMED"] == 1
    assert v["counts_by_code"]["LIVE_RUNS_FOR_UNARMED_LANE"] == 1


def test_n8n_live_lane_without_a_live_run_fails(tmp_path, capsys):
    t = _tree(tmp_path, cron_lines=[ALPHA_LINE], ledger_rows=(("beta-brief", "dry_run", "RUN_DONE", NOW),))
    _run(t)
    v = _out(capsys)
    assert [f["lane_id"] for f in v["error_findings"] if f["code"] == "N8N_LIVE_NO_RECENT_RUN"] == ["beta-brief"]


def test_a_missing_ledger_is_not_measured_never_pass(tmp_path, capsys):
    t = _tree(tmp_path, cron_lines=[ALPHA_LINE], ledger=False)
    rc, _ = _run(t)
    v = _out(capsys)
    assert rc == 2 and v["verdict"] == "NOT_MEASURED" and v["not_measured"] == ["ledger"]
    assert v["empty_reason"] is None


def test_apply_writes_latest_and_one_history_line(tmp_path, capsys):
    t = _tree(tmp_path, cron_lines=[ALPHA_LINE])
    _run(t, "--apply")
    _run(t, "--apply")
    capsys.readouterr()
    out = t["state"] / lt.OUT_REL
    latest = json.loads((out / "latest.json").read_text())
    assert latest["schema"] == "LaneTruth@v1" and latest["verdict"] == "PASS"
    hist = (out / "history.jsonl").read_text().splitlines()
    assert len(hist) == 2 and json.loads(hist[-1])["fingerprint"] == latest["fingerprint"]


def test_draft_workflow_is_inactive_every_15_minutes_dry_run():
    wf = json.loads((ROOT / "docs/ops/packets/lane-truth-20261108/lane-truth.workflow.DRAFT.json").read_text())
    assert wf["active"] is False and wf["meta"]["mode"] == "dry_run" and wf["meta"]["lane_id"] == "lane-truth"
    sched = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
    assert [i["expression"] for i in sched["parameters"]["rule"]["interval"]] == ["*/15 * * * *"]


@pytest.mark.parametrize("flag", ["--no-crontab", "--no-n8n", "--no-ledger"])
def test_each_skipped_source_is_named(tmp_path, capsys, flag):
    t = _tree(tmp_path, cron_lines=[ALPHA_LINE])
    rc, _ = _run(t, flag)
    v = _out(capsys)
    assert rc == 2 and v["verdict"] == "NOT_MEASURED" and len(v["not_measured"]) == 1
