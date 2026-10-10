"""Cron -> n8n migration tracker (2026-10-09): stage classification, line accounting, ETA, outputs.

Hermetic: tmp state root (sqlite ledger + cutover receipts), crontab text passed in, fixed clock.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import report_cron_migration_tracker as t  # noqa: E402

NOW = dt.datetime(2026, 10, 10, 1, 30, tzinfo=dt.timezone.utc)


def _row(lane_id, kind="cron", state="ACTIVE", match=None, rec=None, **extra):
    r = {"lane_id": lane_id, "owner": "platform", "state": state, "expected_cadence_hours": 24,
         "scheduler": {"kind": kind, "expression": "0 6 * * *", "match": match or f"scripts/{lane_id}.py"},
         "output_signal": {"kind": "file", "path": "x"}}
    if rec:
        r["recommendation"] = rec
    r.update(extra)
    return r


def _ledger(root: Path, rows):
    p = root / t.LEDGER_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
                "finished_at TEXT)")
    for i, (lane, mode, state, req, fin) in enumerate(rows):
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (f"r{i}", lane, mode, state, req, fin))
    con.commit()
    con.close()
    return p


def _receipt(root: Path, lane: str, at: str, action="cutover"):
    d = root / t.CUTOVER_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lane}-{action}.json").write_text(json.dumps(
        {"schema": "CutoverReceipt@v1", "lane_id": lane, "action": action, "at": at, "applied": True}))


@pytest.fixture()
def cfg():
    return t.load_config()


def _report(tmp_path, cfg, rows, crontab, ledger_rows=(), receipts=()):
    _ledger(tmp_path, list(ledger_rows))
    for lane, at in receipts:
        _receipt(tmp_path, lane, at)
    runs = t.ledger_runs(tmp_path / t.LEDGER_REL, cfg)
    cuts = t.cutover_receipts(tmp_path / t.CUTOVER_REL)
    return t.build(registry={"lanes": rows}, cfg=cfg, crontab_text=crontab, runs=runs, cuts=cuts, now=NOW,
                   registry_sha="0" * 64, sources={})


def test_every_stage_is_classified_from_evidence(tmp_path, cfg):
    wf = "n8n:workflow:abc"
    rows = [
        _row("gone", state="RETIRED", rec="R0_ELIMINATE"),
        _row("broker-sync", rec="KEEP_ON_CRON"),
        _row("dead-job", rec="R0_ELIMINATE"),
        _row("digest-a", rec="MERGE_INTO:P11"),
        _row("quote-b", rec="PIPELINE:P01"),
        _row("poller-c", rec="EVENT_DRIVEN_CANDIDATE"),
        _row("orphan-d"),
        _row("shadow-e", rec="MERGE_INTO:P13", dispatch={"mode": "dry_run", "wave": "W1"}),
        _row("canary-f", rec="MERGE_INTO:P13", dispatch={"mode": "live", "wave": "W1"}),
        _row("moved-g", kind="n8n", rec="KEEP_ON_CRON"),
        _row("moved-h", kind="n8n", rec="KEEP_ON_CRON"),
        _row("double-i", kind="n8n", rec="KEEP_ON_CRON"),
    ]
    rows[9]["scheduler"]["expression"] = "wf1"
    rows[10]["scheduler"]["expression"] = "wf2"
    rows[11]["scheduler"]["expression"] = "wf3"
    crontab = "\n".join(f"0 6 * * * $PY scripts/{x}.py" for x in (
        "broker-sync", "dead-job", "digest-a", "quote-b", "poller-c", "orphan-d", "shadow-e", "canary-f",
        "double-i")) + "\n# RETIRED 2026-10-09 n8n-cutover moved-g 0 6 * * * $PY scripts/moved-g.py\n"
    fires = [f"2026-10-09T0{i}:00:00+00:00" for i in range(3, 7)]
    ledger = ([("moved-g", "live", "RUN_DONE", wf, f) for f in fires]
              + [("moved-h", "live", "RUN_DONE", wf, fires[0])]
              + [("moved-h", "live", "RUN_DONE", "n8n:workflow:agentA-smoke", f) for f in fires]
              + [("moved-g", "live", "RUN_DONE", wf, "2026-10-08T00:00:00+00:00")])  # before cutover
    rep = _report(tmp_path, cfg, rows, crontab, ledger, [("moved-g", "2026-10-09T02:00:00+00:00"),
                                                        ("moved-h", "2026-10-09T02:00:00+00:00")])
    st = {ln["lane_id"]: ln for ln in rep["lanes"]}
    assert {k: v["stage"] for k, v in st.items()} == {
        "gone": "RETIRED", "broker-sync": "KEEP_ON_CRON", "dead-job": "R0_PENDING",
        "digest-a": "MERGE_PENDING", "quote-b": "PIPELINE_PENDING", "poller-c": "STANDALONE_PENDING",
        "orphan-d": "ON_CRON_UNPLANNED", "shadow-e": "DISPATCH_DRY_RUN", "canary-f": "LIVE_WITH_CRON",
        "moved-g": "VALIDATED", "moved-h": "CUT_OVER", "double-i": "LIVE_WITH_CRON"}
    # smoke-requested runs never count as natural fires; the pre-cutover run does not validate
    assert st["moved-h"]["live_fires"] == 1
    assert st["moved-g"]["live_fires_after_cutover"] == 4
    assert "double_scheduled:cron_line_still_active" in st["double-i"]["flags"]
    assert "no_cutover_receipt" in st["double-i"]["flags"]
    assert st["digest-a"]["target"] == "P11" and st["digest-a"]["wave"] == "R1"
    assert st["quote-b"]["wave"] == "R4" and st["broker-sync"]["wave"] == "W5"
    s = rep["summary"]
    assert (s["moved_lanes"], s["validated_lanes"], s["cron_lines_moved_to_n8n"]) == (2, 1, 1)
    assert s["live_cron_lines"] == 9


def test_crontab_lines_take_their_lane_stage_and_unregistered_lines_are_unplanned(tmp_path, cfg):
    rows = [_row("keep-a", rec="KEEP_ON_CRON"), _row("pipe-b", rec="PIPELINE:P10")]
    crontab = ("PATH=/usr/bin\n0 6 * * * $PY scripts/keep-a.py\n*/5 * * * * $PY scripts/pipe-b.py --x\n"
               "0 7 * * * $PY scripts/pipe-b.py --y\n0 8 * * * $PY scripts/nobody.py\n# 0 9 * * * old\n")
    rep = _report(tmp_path, cfg, rows, crontab)
    lines = rep["summary"]["cron_lines_by_stage"]
    assert lines["KEEP_ON_CRON"] == 1 and lines["PIPELINE_PENDING"] == 2 and lines["ON_CRON_UNPLANNED"] == 1
    assert rep["summary"]["unregistered_cron_lines"] == 1


def test_crontab_absent_is_reported_not_guessed(tmp_path, cfg):
    rep = _report(tmp_path, cfg, [_row("x", rec="PIPELINE:P10")], None)
    assert rep["summary"]["live_cron_lines"] is None
    assert rep["summary"]["cron_lines_by_stage"] is None
    assert rep["lanes"][0]["on_cron"] is None


def test_market_days_skip_weekends_and_nyse_holidays():
    # Fri 2026-11-20 + 1 market day = Mon 11-23; Wed 11-25 + 1 = Fri 11-27 (Thanksgiving 11-26)
    assert t.add_market_days(dt.date(2026, 11, 20), 1) == dt.date(2026, 11, 23)
    assert t.add_market_days(dt.date(2026, 11, 25), 1) == dt.date(2026, 11, 27)
    assert t.add_market_days(dt.date(2026, 11, 20), 3) == dt.date(2026, 11, 25)


def test_scalp_class_wave_waits_three_market_days(cfg):
    wave = {"id": "X", "build_days": 0, "ladder": "dispatch"}
    lane = {"lane_id": "l", "stage": "PIPELINE_PENDING", "cadence_hours": 0.25, "scalp_class": False}
    start = dt.date(2026, 10, 12)  # Monday
    plain = t.wave_eta(wave, [lane], start, cfg)
    scalp = t.wave_eta(wave, [dict(lane, scalp_class=True)], start, cfg)
    assert dt.date.fromisoformat(scalp["cutover"]) > dt.date.fromisoformat(plain["cutover"])
    assert any("3 market day" in x for x in scalp["steps"])
    assert plain["cutover"] <= plain["end"]


def test_waves_are_sequential_on_cutover_and_done_waves_have_no_remaining(tmp_path, cfg):
    rows = [_row("w1lane", rec="MERGE_INTO:P13"), _row("r1lane", rec="PIPELINE:P12")]
    cfg = dict(cfg, waves=[
        {"id": "A", "title": "a", "select": {"lane_ids": ["w1lane"]}, "build_days": 2, "ladder": "dispatch"},
        {"id": "B", "title": "b", "select": {"pipelines": ["P12"]}, "build_days": 2, "ladder": "dispatch"},
        {"id": "Z", "title": "z", "select": {"fallback": True}, "build_days": 0, "ladder": "unplanned"}])
    rep = _report(tmp_path, cfg, rows, "")
    a, b = rep["waves"][0]["eta"], rep["waves"][1]["eta"]
    assert b["start"] == a["cutover"]
    assert rep["summary"]["eta_all_waves_done"] == max(a["end"], b["end"])


def test_config_plan_covers_all_sixteen_pipelines_and_unique_waves(cfg):
    ids = [w["id"] for w in cfg["waves"]]
    assert len(ids) == len(set(ids))
    pipes = {p for w in cfg["waves"] for p in (w.get("select") or {}).get("pipelines") or []}
    assert {f"P{i:02d}" for i in range(1, 17)} <= pipes
    assert sum(1 for w in cfg["waves"] if (w.get("select") or {}).get("fallback")) == 1


def test_main_writes_doc_and_receipt_and_check_detects_staleness(tmp_path, monkeypatch):
    reg = tmp_path / "lane_registry.json"
    reg.write_text(json.dumps({"lanes": [_row("pipe-b", rec="PIPELINE:P10")]}))
    cron = tmp_path / "crontab.txt"
    cron.write_text("0 7 * * * $PY scripts/pipe-b.py\n")
    state = tmp_path / "state"
    _ledger(state, [])
    led = state / t.LEDGER_REL
    before = led.stat().st_mtime_ns
    doc, receipt = tmp_path / "MIGRATION_TRACKER.md", tmp_path / "r.json"
    rc = t.main(["--registry", str(reg), "--state-root", str(state), "--crontab", str(cron), "--write",
                 "--doc", str(doc), "--receipt", str(receipt), "--now", NOW.isoformat()])
    assert rc == 0
    body = json.loads(receipt.read_text())
    assert body["schema"] == "CronMigrationTracker@v1" and body["authority"] == "READ_ONLY_ADVISORY"
    md = doc.read_text()
    for heading in ("## Headline", "## Summary by stage", "## Waves", "## ETA", "## Lanes"):
        assert heading in md
    assert "`pipe-b`" in md
    assert led.stat().st_mtime_ns == before  # ledger opened read-only
    monkeypatch.setattr(t, "DOC_REL", doc.relative_to(tmp_path))
    monkeypatch.setattr(t, "PROJ", tmp_path)
    assert t.main(["--check", "--registry", str(reg)]) == 0
    reg.write_text(json.dumps({"lanes": []}))
    assert t.main(["--check", "--registry", str(reg)]) == 1


def test_script_never_writes_crontab_or_registry():
    src = (ROOT / "scripts" / "report_cron_migration_tracker.py").read_text()
    assert "crontab -" not in src.replace("crontab -l", "")
    assert '"crontab", "-l"' in src
    assert "lane_registry.json\").write" not in src and "mode=ro" in src


def test_same_second_rollback_then_recut_resolves_to_last_mirror(tmp_path):
    d = tmp_path / t.CUTOVER_REL
    d.mkdir(parents=True)
    at = "2026-10-09T02:01:45+00:00"
    for name, action in (("lane-x-cutover.json", "cutover"), ("lane-x-rollback.json", "rollback"),
                         ("n8n_cutover_last.json", "cutover")):
        (d / name).write_text(json.dumps({"schema": "CutoverReceipt@v1", "lane_id": "lane-x", "action": action,
                                          "at": at, "applied": True}))
    (d / "crontab-20261009T020135Z-pre-cutover-lane-lane-y.txt").write_text("x")
    cuts = t.cutover_receipts(d)
    assert cuts["lane-x"]["action"] == "cutover" and cuts["lane-x"]["source"] == "n8n_cutover_last.json"
    assert cuts["lane-y"]["kind"] == "backup_only" and cuts["lane-y"]["at"].startswith("2026-10-09T02:01:35")
