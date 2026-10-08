"""Lane monitor rendering for scheduler kind n8n (observability gaps PR, 2026-10-08).

`evaluate_lane` already emits `scheduler_label` and `n8n_last_run`; until this PR no printing surface
showed them, so an n8n-scheduled lane read like a cron lane with no expression. The renderers in
scripts.lib.lane_registry (format_lane_line / render_lane_table / lane_scheduler_text) print the label
and, for kind n8n, the last run (mode/state/finished_at) with FRESH or ORPHANED READ from
`scheduler_present` — never re-derived. research_lane_health (`--lanes`, alert body) and the governance
packet (`detail`, which rendered blank before) use them. Hermetic: tmp registry, tmp sqlite ledger,
injected crontab text, no systemd probe.

COVERS = ["scripts/lib/lane_registry.py", "scripts/research_lane_health.py", "scripts/report_lane_governance_packet.py"]
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import report_lane_governance_packet as GP  # noqa: E402
from scripts import research_lane_health as RLH  # noqa: E402
from scripts.lib import lane_registry as lr  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
CRON_LINE = "*/8 * * * * cd $PROJ && $PY scripts/fixture_cron.py >> logs/fixture_cron.log 2>&1"


def _lane(lane_id, kind, expression, match, cadence=1.0, signal=None):
    return {
        "lane_id": lane_id,
        "owner": "platform",
        "state": "ACTIVE",
        "expected_cadence_hours": cadence,
        "scheduler": {"kind": kind, "expression": expression, "match": match},
        "output_signal": {"kind": "file_mtime", "path": signal or f"data/runtime/{lane_id}.json"},
    }


def _signal(root: Path, lane_id: str, age_h: float) -> None:
    p = root / "data" / "runtime" / f"{lane_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    t = (NOW - timedelta(hours=age_h)).timestamp()
    os.utime(p, (t, t))


def _ledger(root: Path, rows: list[tuple]) -> None:
    p = lr.n8n_ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id, mode, state, requested_by, caller_id, requested_at, "
        "started_at, finished_at, exit_code, duration_s, receipt_json)"
    )
    for run_id, lane_id, mode, state, finished_at, exit_code in rows:
        conn.execute(
            "INSERT INTO runs(run_id, lane_id, mode, state, finished_at, exit_code) VALUES (?,?,?,?,?,?)",
            (run_id, lane_id, mode, state, finished_at, exit_code),
        )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _no_live_ledger(monkeypatch):
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)


@pytest.fixture
def world(tmp_path):
    """Three lanes: n8n FRESH (RUN_DONE 20 min ago, cadence 1 h), n8n ORPHANED (last RUN_DONE 5 h ago,
    newest run RUN_FAILED), cron LIVE (its line is in the injected crontab)."""
    reg = {
        "schema": "LaneRegistry@v1",
        "lanes": [
            _lane("n8n-fresh", "n8n", "wf-fresh01", "scripts/fixture_fresh.py"),
            _lane("n8n-orphan", "n8n", "wf-orphan1", "scripts/fixture_orphan.py"),
            _lane("cron-lane", "cron", CRON_LINE, "scripts/fixture_cron.py", cadence=24.0),
        ],
    }
    regp = tmp_path / "lane_registry.json"
    regp.write_text(json.dumps(reg))
    for lane_id in ("n8n-fresh", "n8n-orphan", "cron-lane"):
        _signal(tmp_path, lane_id, 0.2)
    _ledger(
        tmp_path,
        [
            ("r-fresh", "n8n-fresh", "live", "RUN_DONE", (NOW - timedelta(minutes=20)).isoformat(), 0),
            ("r-old", "n8n-orphan", "live", "RUN_DONE", (NOW - timedelta(hours=5)).isoformat(), 0),
            ("r-bad", "n8n-orphan", "dry_run", "RUN_FAILED", (NOW - timedelta(minutes=9)).isoformat(), 2),
        ],
    )
    return tmp_path, regp


def _report(world):
    root, regp = world
    return lr.collect_lane_registry_report(
        now=NOW, registry_path=regp, root=root, cron_text=CRON_LINE + "\n", include_systemd=False
    )


# ── the renderer prints the label and, for n8n, the last run with FRESH/ORPHANED as evaluated ─────


def test_the_table_shows_the_n8n_label_and_last_run_instead_of_a_cron_expression(world):
    rep = _report(world)
    by = {r["lane_id"]: r for r in rep["lanes"]}
    assert by["n8n-fresh"]["verdict"] == lr.LIVE and by["n8n-orphan"]["verdict"] == lr.ORPHANED
    table = lr.render_lane_table(rep["lanes"])
    lines = {ln.split()[0]: ln for ln in table.splitlines()}
    fresh = lines["n8n-fresh"]
    assert "n8n:wf-fresh01" in fresh and "live/RUN_DONE 2026-10-08T13:40:00+00:00" in fresh
    assert "[FRESH within 1.0h]" in fresh and "*/8" not in fresh
    orphan = lines["n8n-orphan"]
    # ORPHANED exactly as evaluate_lane decided, and the newest run of ANY state is named (RUN_FAILED here)
    assert "ORPHANED" in orphan.split()[1] and "n8n:wf-orphan1" in orphan
    assert "dry_run/RUN_FAILED" in orphan and "[ORPHANED within 1.0h]" in orphan
    cron = lines["cron-lane"]
    assert cron.split()[1] == lr.LIVE and f"cron:{CRON_LINE}" in cron and "last" not in cron.split("output")[0][-6:]
    assert cron.endswith("output 0.2h/24.0h")


def test_fresh_or_orphaned_is_read_from_scheduler_present_never_re_derived():
    stale = {"mode": "live", "state": "RUN_DONE", "finished_at": "2026-01-01T00:00:00+00:00"}
    row = {
        "lane_id": "x",
        "verdict": lr.LIVE,
        "scheduler": {"kind": "n8n", "expression": "wf"},
        "scheduler_label": "n8n:wf",
        "scheduler_present": True,
        "expected_cadence_hours": 1.0,
        "n8n_last_run": stale,
        "output_age_hours": 0.1,
    }
    assert "[FRESH within 1.0h]" in lr.lane_scheduler_text(row)  # evaluate_lane said present: we print it
    row["scheduler_present"] = False
    assert "[ORPHANED within 1.0h]" in lr.lane_scheduler_text(row)
    row["n8n_last_run"] = None
    assert "no run (no ledger row, no RunReceipt)" in lr.format_lane_line(row)
    assert lr.lane_scheduler_text({"scheduler": {"kind": "cron", "expression": "5 * * * * x"}}) == "cron:5 * * * * x"
    assert lr.format_lane_line({"lane_id": "y", "verdict": lr.SILENT, "scheduler": {"kind": "none"}}).endswith(
        "none  output none"
    )


# ── research_lane_health: --lanes table and the alert body ──────────────────────────────────────


def test_research_lane_health_lanes_table_and_alert_body_name_the_finding_lanes(world, monkeypatch, capsys):
    rep = _report(world)
    report = {"as_of": NOW.isoformat(), "lanes": [{"lane": "deepseek", "ok": True}, rep]}
    text = RLH.lane_table_text(report)
    assert text.splitlines()[0].startswith("lane-registry ORPHANED=1  declared=3")
    assert "n8n-orphan" in text and "[ORPHANED within 1.0h]" in text and "n8n:wf-fresh01" in text
    assert RLH.lane_table_text({"lanes": []}).startswith("lane-registry: not collected")
    extra = RLH.lane_registry_findings_text(rep)
    assert extra.startswith("\n      n8n-orphan") and "dry_run/RUN_FAILED" in extra and "n8n-fresh" not in extra
    assert RLH.lane_registry_findings_text({"findings": []}) == ""
    many = {
        "findings": [
            {"lane_id": f"l{i}", "verdict": "SILENT", "scheduler": {"kind": "cron", "expression": "x"}}
            for i in range(10)
        ]
    }
    assert "… 2 more (see the JSON report)" in RLH.lane_registry_findings_text(many)
    # --lanes prints the table, not JSON; collect_report is replaced so nothing on the host is probed
    monkeypatch.setattr(RLH, "collect_report", lambda: report)
    monkeypatch.setattr(sys, "argv", ["research_lane_health.py", "--lanes"])
    assert RLH.main() == 0
    out = capsys.readouterr().out
    assert out.startswith("lane-registry ORPHANED=1") and "n8n-orphan" in out and not out.lstrip().startswith("{")


# ── governance packet: `detail` was blank because evaluate_lane never emits a `detail` key ───────


def test_the_governance_packet_findings_carry_the_scheduler_column_and_last_run(world):
    root, regp = world
    sec = GP.lanes_section(now=NOW, registry_path=regp, root=root, cron_text=CRON_LINE + "\n", include_systemd=False)
    assert sec["declared"] == 3 and sec["verdict_counts"] == {lr.LIVE: 2, lr.ORPHANED: 1}
    (f,) = sec["findings"]
    assert f["lane_id"] == "n8n-orphan" and f["verdict"] == lr.ORPHANED and f["scheduler_label"] == "n8n:wf-orphan1"
    assert f["n8n_last_run"]["state"] == "RUN_FAILED" and f["n8n_last_run"]["run_id"] == "r-bad"
    assert (
        f["detail"].startswith("n8n:wf-orphan1 last dry_run/RUN_FAILED")
        and "[ORPHANED within 1.0h]; output 0.2h" in f["detail"]
    )
    md = GP.render_markdown(
        {
            "period": "weekly",
            "period_key": "2026-W41",
            "as_of": NOW.isoformat(),
            "served_sha": "x",
            "sections": {
                "lanes": sec,
                "ledger": {"per_lane": {}},
                "incidents": {},
                "releases": {},
                "retention": {"last_run": {}, "hygiene": {"items": []}},
            },
            "summary": {
                "lanes_declared": 3,
                "lane_verdicts": sec["verdict_counts"],
                "ledger_by_state": {},
                "ledger_refusals": {},
                "incidents_open": 0,
                "incidents_by_severity": {},
                "release": {"sha": None, "at": None, "ok": None},
            },
        }
    )
    assert "- ORPHANED `n8n-orphan` — n8n:wf-orphan1 last dry_run/RUN_FAILED" in md
