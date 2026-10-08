"""Per-lane n8n cutover readiness (2026-10-08): GO only when the row is ACTIVE, the host scheduler is
present exactly once, the output_signal is fresh within 2× cadence, the lane's safe_flock history is
clean and both a shadow (dry_run) and a canary (live) RunReceipt exist with exit 0. Hermetic: tmp
state root, fixture crontab text, tmp sqlite ledger / receipt files, --host-state-json for timers.

COVERS = ["scripts/report_n8n_lane_readiness.py"]
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

import scripts.report_n8n_lane_readiness as R  # noqa: E402
from scripts.lib.lane_registry import n8n_ledger_path, n8n_runs_dir  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
LANE = "fixture-warm"
MATCH = "scripts/fixture_warm.py"
LINE = f"*/8 * * * * cd $PROJ && bash scripts/safe_flock.sh /tmp/fixture_warm.lock $PY {MATCH} >> logs/fixture_warm.log 2>&1"
LINE_NOLOCK = f"*/8 * * * * cd $PROJ && $PY {MATCH} >> logs/fixture_warm.log 2>&1"
OTHER = "0 9 * * 1-5 cd $PROJ && $PY scripts/untouched.py >> logs/untouched.log 2>&1"


def _reg(state="ACTIVE", kind="cron", match=MATCH, expression="*/8 * * * * fixture_warm.py"):
    row = {
        "lane_id": LANE,
        "owner": "platform",
        "scheduler": {"kind": kind, "expression": expression, "match": match},
        "expected_cadence_hours": 1.0,
        "state": state,
        "output_signal": {"kind": "file_mtime", "path": "data/runtime/fixture_warm.json"},
    }
    if state != "ACTIVE":
        row.update(
            {
                "state_reason": "fixture",
                "state_since": "2026-10-01",
                "reason_confidence": "ESTABLISHED",
                "review_by": "2026-11-01",
            }
        )
    return {"schema": "LaneRegistry@v1", "lanes": [row], "undeclared_baseline": []}


def _state(
    tmp_path: Path, *, signal_age_h=0.3, flock_exits=(0, 0, 0), receipts=("dry_run", "live"), via="receipts"
) -> Path:
    st = tmp_path / "state"
    (st / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    (st / "logs").mkdir(parents=True, exist_ok=True)
    if signal_age_h is not None:
        p = st / "data" / "runtime" / "fixture_warm.json"
        p.write_text("{}")
        t = (NOW - timedelta(hours=signal_age_h)).timestamp()
        os.utime(p, (t, t))
    with (st / "logs" / "safe_flock_events.jsonl").open("w") as fh:
        fh.write('{"ts":"2026-10-08T01:00:00-04:00","component":"other","event_type":"completed","exit_code":7}\n')
        for i, rc in enumerate(flock_exits):
            fh.write(
                json.dumps(
                    {
                        "ts": f"2026-10-08T0{i + 1}:00:00-04:00",
                        "component": "fixture_warm",
                        "event_type": "completed",
                        "severity": "INFO",
                        "exit_code": rc,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            fh.write(
                json.dumps(
                    {"ts": f"2026-10-08T0{i + 1}:00:00-04:00", "component": "fixture_warm", "event_type": "started"},
                    separators=(",", ":"),
                )
                + "\n"
            )
    runs = [
        (f"run-{i}", LANE, mode, "RUN_DONE", (NOW - timedelta(hours=2 - i)).isoformat(), 0)
        for i, mode in enumerate(receipts)
    ]
    if via == "ledger":
        p = n8n_ledger_path(st)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p)
        conn.execute(
            "CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id, mode, state, requested_by, caller_id, requested_at, "
            "started_at, finished_at, exit_code, duration_s, receipt_json)"
        )
        for run_id, lane_id, mode, state, finished_at, exit_code in runs:
            conn.execute(
                "INSERT INTO runs(run_id, lane_id, mode, state, finished_at, exit_code) VALUES (?,?,?,?,?,?)",
                (run_id, lane_id, mode, state, finished_at, exit_code),
            )
        conn.commit()
        conn.close()
    else:
        d = n8n_runs_dir(st)
        d.mkdir(parents=True, exist_ok=True)
        for run_id, lane_id, mode, state, finished_at, exit_code in runs:
            (d / f"{run_id}.json").write_text(
                json.dumps(
                    {
                        "schema": "RunReceipt@v1",
                        "run_id": run_id,
                        "lane_id": lane_id,
                        "mode": mode,
                        "state": state,
                        "exit_code": exit_code,
                        "finished_at": finished_at,
                    }
                )
            )
    return st


@pytest.fixture(autouse=True)
def _no_live_ledger(monkeypatch):
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)


def test_go_when_every_check_holds_from_receipt_files_and_from_the_ledger(tmp_path):
    for via in ("receipts", "ledger"):
        st = _state(tmp_path / via, via=via)
        r = R.assess_lane(LANE, reg=_reg(), text="\n".join([OTHER, LINE]) + "\n", state=st, now=NOW)
        assert r["verdict"] == "GO", r
        assert r["blockers"] == [] and r["notes"] == []
        assert r["host_scheduler"]["present_once"] and r["safe_flock"]["component"] == "fixture_warm"
        assert [c["exit_code"] for c in r["safe_flock"]["completions"]] == [0, 0, 0]
        assert r["run_receipts"]["shadow_ok"] and r["run_receipts"]["canary_ok"] and r["run_receipts"]["count"] == 2


def test_no_go_names_each_blocker(tmp_path):
    st = _state(tmp_path, signal_age_h=5.0, flock_exits=(0, 1, 0), receipts=("dry_run",))
    r = R.assess_lane(LANE, reg=_reg(), text="\n".join([LINE, LINE.replace("*/8", "*/9")]) + "\n", state=st, now=NOW)
    assert r["verdict"] == "NO_GO"
    joined = " | ".join(r["blockers"])
    assert "not present exactly once (live_count=2)" in joined
    assert "output_signal stale: 5.0h > 2×1.0h" in joined
    assert "no canary RunReceipt" in joined and "no shadow RunReceipt" not in joined
    assert r["safe_flock"] is None  # an ambiguous host line names no lock to judge
    r = R.assess_lane(LANE, reg=_reg(), text=LINE + "\n", state=st, now=NOW)
    assert r["verdict"] == "NO_GO" and any(
        "fixture_warm: a recent completion exited non-zero" in b for b in r["blockers"]
    )
    r = R.assess_lane("no-such-lane", reg=_reg(), text=LINE + "\n", state=st, now=NOW)
    assert r["verdict"] == "NO_GO" and r["blockers"] == ["no registry row"]
    r = R.assess_lane(LANE, reg=_reg(state="PAUSED"), text=LINE + "\n", state=st, now=NOW)
    assert any("not ACTIVE" in b for b in r["blockers"])
    st2 = _state(tmp_path / "absent", signal_age_h=None)
    r = R.assess_lane(LANE, reg=_reg(), text=LINE + "\n", state=st2, now=NOW)
    assert any("absent" in b for b in r["blockers"])


def test_notes_without_blockers_are_go_with_notes(tmp_path):
    st = _state(tmp_path, flock_exits=(0, 0))
    r = R.assess_lane(LANE, reg=_reg(), text=LINE_NOLOCK + "\n", state=st, now=NOW)
    assert r["verdict"] == "GO_WITH_NOTES" and r["safe_flock"] is None
    assert any("no lock named" in n for n in r["notes"])
    r = R.assess_lane(LANE, reg=_reg(), text=LINE + "\n", state=st, now=NOW)
    assert r["verdict"] == "GO_WITH_NOTES" and any("only 2 completion(s)" in n for n in r["notes"])


def test_a_lane_already_on_n8n_is_judged_on_the_double_scheduler(tmp_path):
    st = _state(tmp_path)
    reg = _reg(kind="n8n", expression="wf-abc123")
    r = R.assess_lane(LANE, reg=reg, text=LINE + "\n", state=st, now=NOW)
    assert r["verdict"] == "NO_GO" and any("double scheduler" in b for b in r["blockers"])
    r = R.assess_lane(LANE, reg=reg, text=f"# RETIRED 2026-10-08 n8n-cutover {LANE} {LINE}\n", state=st, now=NOW)
    assert r["verdict"] == "GO_WITH_NOTES" and any("already kind n8n" in n for n in r["notes"])


def test_a_systemd_lane_reads_the_timer_from_host_state(tmp_path):
    st = _state(tmp_path)
    reg = _reg(kind="systemd", expression="x-fixture.timer", match="x-fixture.timer")
    host = {
        "timers": {
            "x-fixture.timer": {
                "unit_file_state": "enabled",
                "sub_state": "waiting",
                "next_elapse": "Thu",
                "recurring": True,
            }
        }
    }
    r = R.assess_lane(LANE, reg=reg, text=OTHER + "\n", state=st, now=NOW, host_state=host)
    assert r["verdict"] == "GO_WITH_NOTES" and r["host_scheduler"]["present_once"] is True  # no lock to judge
    r = R.assess_lane(LANE, reg=reg, text=OTHER + "\n", state=st, now=NOW, host_state={"timers": {}})
    assert r["verdict"] == "NO_GO" and any("not measurable" in b for b in r["blockers"])


def test_cli_dry_run_writes_nothing_and_write_produces_the_receipt(tmp_path, capsys):
    st = _state(tmp_path)
    root = tmp_path / "code"
    (root / "config").mkdir(parents=True)
    (root / "config" / "lane_registry.json").write_text(json.dumps(_reg()))
    cf = tmp_path / "crontab.txt"
    cf.write_text("\n".join([OTHER, LINE]) + "\n")
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"timers": {}}))
    common = [
        "--lane",
        LANE,
        "--crontab-file",
        str(cf),
        "--state-root",
        str(st),
        "--code-root",
        str(root),
        "--now",
        NOW.isoformat(),
        "--host-state-json",
        str(host),
    ]
    assert R.main(["--dry-run", *common]) == 0
    out = capsys.readouterr().out
    assert f"lane {LANE}: GO" in out and "dry-run: nothing written" in out
    assert not (st / R.RECEIPT_REL).exists()
    assert R.main(["--write", "--json", *common]) == 0
    doc = json.loads((st / R.RECEIPT_REL).read_text())
    assert (
        doc["schema"] == "N8nLaneReadiness@v1" and doc["authority"] == "READ_ONLY_ADVISORY" and doc["verdict"] == "GO"
    )
    assert doc["lane"]["run_receipts"]["schema"] == "RunReceipt@v1"
