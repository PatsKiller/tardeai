"""scripts/monitor_fold_parity.py — the W1-9 parallel-run compare (rulings R1/R11, 2026-10-11).

Log fixtures are copied from the shapes the monitors print (job_coverage_monitor.py:300-303,
pipeline_freshness_monitor.py:188-194, pipeline_liveness_report.py:77). Ledger rows are produced by the detector's
own pure functions. Everything lives under tmp_path; no live log, ledger or DB is read.

COVERS = ["scripts/monitor_fold_parity.py"]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import monitor_fold_parity as mfp  # noqa: E402

import supervisor_breach_detector as sbd  # noqa: E402

NOW = datetime(2026, 10, 13, 1, 0, tzinfo=timezone.utc)
JOBS = [{"name": "hermes_analyst_signal_discovery", "schedule_match": "hermes_analyst_signal_discovery.py",
         "signal": ("log", "hermes_analyst_signal.log")},
        {"name": "drive_sync", "schedule_match": "drive_syncs.sh", "signal": ("log", "drive_sync.log")},
        {"name": "catalyst_momentum_engine", "schedule_match": "catalyst_momentum_engine.py", "signal": ("db", "SELECT 1")}]
LANES = [{"lane_id": "hermes-analyst-signal-discovery", "state": "ACTIVE",
          "exec_start": "$PY scripts/hermes_analyst_signal_discovery.py"},
         {"lane_id": "old-drive-sync", "state": "RETIRED", "exec_start": "drive_syncs.sh"}]
LOG_LANES = {"hermes_analyst_signal_discovery": {"hermes-analyst-signal-discovery"}, "drive_sync": set()}
KEYS = {"jcm.catalyst_momentum_engine", "jcm.process_watchlist_agent_jobs", "jcm.news_ingestion",
        "pfm.morning_synthesis", "pfm.trade_closed", "sfm.news_articles"}


def _jcm_block(rows: list[tuple[str, str]]) -> str:
    icon = {"OK": "✅", "STALE": "🔴", "NOT_SCHEDULED": "⛔", "NO_SIGNAL": "🟡"}
    body = "".join(f"  {icon[s]} [{s:13}] {j:28} detail\n" for j, s in rows)
    return f"Job coverage / heartbeat:\n{body}\n0 FAIL (0/0 OK)\n"


def _pfm_block(stale: list[str], missing: list[str] = (), ok: list[str] = ("hermes_canonical",)) -> str:
    out = f"[pipeline-freshness] {len(ok)} fresh · {len(stale)} STALE · {len(missing)} missing\n"
    out += "".join(f"  ⚠ STALE  {n:22s} 2.5d old (>2.0d) → x\n" for n in stale)
    out += "".join(f"  ? MISSING {n:22s} absent → x\n" for n in missing)
    return out + "".join(f"    ok     {n:22s} 0.1d\n" for n in ok)


def _plr_run(statuses: dict[str, str]) -> str:
    mark = {"LIVE": "ok  ", "STARVED": "STARVED", "NO_ELIGIBLE_INPUT": "NO-INPUT", "UNKNOWN": "UNKNOWN", "QUIET": "quiet"}
    out = "".join(f"{mark[s]:8} {lane:34} produced 0/3 attempted in 24h — x\n" for lane, s in statuses.items())
    if any(s != "LIVE" for s in statuses.values()):
        out += "\nFINDING  lane: 3 attempted, 0 produced.\n"
    return out


def _stale(keys: list[str], at: datetime = NOW) -> list[dict]:
    contracts = [{"key": k, "signal": {"kind": "file_mtime", "path": f"data/{k}"}, "max_age_hours": 24,
                  "basis": "wall_clock", "severity": "P2"} for k in keys]
    return sbd.detect_freshness(contracts=contracts, lanes=[], sla_by_lane={},
                                observe=lambda _s: {"readable": True, "last_output_at": None}, now=at)


def _starved(pairs: list[tuple[str, str]]) -> list[dict]:
    return sbd.detect_input_starvation(liveness={"lanes": [{"lane": lane, "status": s} for lane, s in pairs]}, now=NOW)


def _no_output(lane_id: str) -> dict:
    return {"kind": "NO_OUTPUT", "lane_id": lane_id, "detected_at": NOW.isoformat(), "evidence": {"signal": {}}}


# ── parsers ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_job_coverage_parser_reads_only_the_last_runs_blocks():
    text = _jcm_block([("news_ingestion", "STALE")]) + _jcm_block([("catalyst_momentum_engine", "STALE"),
                                                                    ("aegis_overnight", "NOT_SCHEDULED"),
                                                                    ("drive_sync", "NO_SIGNAL")])
    assert mfp.parse_job_coverage(text, 1) == {"runs": 1, "flagged": {"catalyst_momentum_engine": "STALE",
                                                                      "aegis_overnight": "NOT_SCHEDULED"}}
    assert mfp.parse_job_coverage(text, 2)["flagged"]["news_ingestion"] == "STALE"
    assert mfp.parse_job_coverage("", 2) == {"runs": 0, "flagged": {}}


def test_pipeline_freshness_parser_takes_stale_and_missing():
    text = _pfm_block(["trade_closed"]) + "[pipeline-freshness] unchanged stale set — suppressed (ongoing)\n"
    text += _pfm_block(["morning_synthesis"], missing=["rotation_summary"])
    assert mfp.parse_pipeline_freshness(text, 1) == {"runs": 1, "flagged": {"morning_synthesis": "STALE",
                                                                           "rotation_summary": "MISSING"}}
    assert set(mfp.parse_pipeline_freshness(text, 6)["flagged"]) == {"trade_closed", "morning_synthesis", "rotation_summary"}


def test_pipeline_liveness_parser_windows_by_lane_count():
    old = _plr_run({"a": "STARVED", "b": "LIVE"})
    new = _plr_run({"a": "LIVE", "b": "NO_ELIGIBLE_INPUT"}) + _plr_run({"a": "LIVE", "b": "LIVE"})
    p = mfp.parse_pipeline_liveness(old + new, 2)
    assert p["runs"] == 2 and p["lanes"] == ["a", "b"] and p["flagged"] == [("b", "NO_ELIGIBLE_INPUT")]
    assert mfp.parse_pipeline_liveness(old + new, 3)["flagged"] == [("a", "STARVED"), ("b", "NO_ELIGIBLE_INPUT")]


def test_ledger_window_drops_rows_outside_it():
    rows = _stale(["pfm.trade_closed"], NOW - timedelta(hours=25)) + _stale(["pfm.morning_synthesis"])
    rows.append({"kind": "STALE_OUTPUT", "detected_at": "garbage"})
    assert [r["evidence"]["contract"] for r in mfp.ledger_window(rows, NOW, 24)] == ["pfm.morning_synthesis"]


# ── compares ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_job_coverage_match_like_the_2026_10_11_measurement():
    parsed = mfp.parse_job_coverage(_jcm_block([("catalyst_momentum_engine", "STALE"),
                                                ("process_watchlist_agent_jobs", "STALE"),
                                                ("hermes_analyst_signal_discovery", "STALE"),
                                                ("aegis_overnight", "NOT_SCHEDULED")]), 2)
    rows = _stale(["jcm.catalyst_momentum_engine", "jcm.process_watchlist_agent_jobs", "sfm.news_articles"])
    rows.append(_no_output("hermes-analyst-signal-discovery"))
    doc = mfp.compare_job_coverage(parsed, rows, contract_keys=KEYS, log_lanes=LOG_LANES)
    assert doc["verdict"] == "MATCH", doc
    assert doc["monitor_stale_log"] == ["hermes_analyst_signal_discovery"]
    assert doc["not_compared"] == ["aegis_overnight:NOT_SCHEDULED"]


def test_job_coverage_mismatch_both_directions_and_uncovered_log_job():
    parsed = mfp.parse_job_coverage(_jcm_block([("catalyst_momentum_engine", "STALE"),
                                                ("hermes_analyst_signal_discovery", "STALE")]), 2)
    rows = _stale(["jcm.news_ingestion"])
    doc = mfp.compare_job_coverage(parsed, rows, contract_keys=KEYS, log_lanes=LOG_LANES)
    assert doc["verdict"] == "MISMATCH"
    assert doc["monitor_only"] == ["catalyst_momentum_engine"] and doc["plane_only"] == ["news_ingestion"]
    assert doc["log_without_no_output"] == ["hermes_analyst_signal_discovery"] and doc["uncovered"] == []


def test_a_db_job_without_a_contract_is_uncovered_not_a_log_job():
    # a release from before W1-9: no jcm.* contracts in its registry
    parsed = mfp.parse_job_coverage(_jcm_block([("catalyst_momentum_engine", "STALE")]), 2)
    doc = mfp.compare_job_coverage(parsed, [], contract_keys=set(), log_lanes=LOG_LANES)
    assert doc["verdict"] == "MISMATCH" and doc["uncovered"] == ["catalyst_momentum_engine"]
    assert doc["log_without_no_output"] == []


def test_no_monitor_run_is_never_a_match():
    doc = mfp.compare_job_coverage({"runs": 0, "flagged": {}}, [], contract_keys=KEYS, log_lanes=LOG_LANES)
    assert doc["verdict"] == "MISMATCH" and doc["note"] == "no monitor run in the log window"


def test_pipeline_freshness_compare_scopes_to_pfm_contracts():
    parsed = mfp.parse_pipeline_freshness(_pfm_block(["morning_synthesis"], missing=["rotation_summary"]), 6)
    doc = mfp.compare_pipeline_freshness(parsed, _stale(["pfm.morning_synthesis", "sfm.news_articles"]), contract_keys=KEYS)
    assert doc["verdict"] == "MATCH" and doc["not_compared"] == ["rotation_summary:MISSING"]
    doc = mfp.compare_pipeline_freshness(parsed, _stale(["pfm.trade_closed"]), contract_keys=KEYS)
    assert doc["monitor_only"] == ["morning_synthesis"] and doc["plane_only"] == ["trade_closed"]


def test_pipeline_liveness_compare_matches_lane_and_status():
    parsed = mfp.parse_pipeline_liveness(_plr_run({"lineage_completions": "STARVED", "memory_admissions": "LIVE"}), 48)
    assert mfp.compare_pipeline_liveness(parsed, _starved([("lineage_completions", "STARVED")]))["verdict"] == "MATCH"
    doc = mfp.compare_pipeline_liveness(parsed, _starved([("lineage_completions", "UNKNOWN")]))
    assert doc["monitor_only"] == ["lineage_completions:STARVED"] and doc["plane_only"] == ["lineage_completions:UNKNOWN"]


# ── run / main (fixture root only) ───────────────────────────────────────────────────────────────────────────
def _root(tmp_path: Path, rows: list[dict]) -> Path:
    root = tmp_path / "release"
    for rel, text in ((mfp.JCM_LOG, _jcm_block([("catalyst_momentum_engine", "STALE")])),
                      (mfp.PFM_LOG, _pfm_block([])),
                      (mfp.PLR_LOG, _plr_run({"lineage_completions": "LIVE"}))):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    (root / mfp.LEDGER).parent.mkdir(parents=True, exist_ok=True)
    (root / mfp.LEDGER).write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    (root / mfp.REGISTRY).parent.mkdir(parents=True, exist_ok=True)
    (root / mfp.REGISTRY).write_text(json.dumps({"freshness_contracts": [{"key": k} for k in sorted(KEYS)], "lanes": LANES}))
    return root


def test_main_match_writes_the_dated_document_outside_the_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mfp, "_jcm_jobs", lambda: JOBS)
    root = _root(tmp_path, _stale(["jcm.catalyst_momentum_engine"]))
    out = tmp_path / "parity"
    rc = mfp.main(["--root", str(root), "--now", NOW.isoformat(), "--out", str(out)])
    doc = json.loads((out / "parity-2026-10-13.json").read_text())
    assert rc == 0 and doc["status"] == "MATCH" and doc["schema"] == mfp.SCHEMA and doc["errors"] == []
    assert json.loads(capsys.readouterr().out) == doc


def test_main_mismatch_exits_3_and_refuses_an_out_dir_under_root(tmp_path, monkeypatch):
    monkeypatch.setattr(mfp, "_jcm_jobs", lambda: JOBS)
    root = _root(tmp_path, [])
    assert mfp.main(["--root", str(root), "--now", NOW.isoformat()]) == 3
    assert mfp.main(["--root", str(root), "--now", NOW.isoformat(), "--out", str(root / "x")]) == 2
    assert not (root / "x").exists()


def test_unreadable_input_is_status_unreadable(tmp_path):
    doc = mfp.run(tmp_path / "missing", NOW, window_hours=24, runs=mfp.DEFAULT_RUNS, jobs=JOBS)
    assert doc["status"] == "UNREADABLE" and any(mfp.LEDGER in e for e in doc["errors"])


def test_job_log_lanes_maps_active_lanes_by_schedule_match():
    assert mfp.job_log_lanes(JOBS, LANES) == LOG_LANES  # db jobs skipped, RETIRED lanes ignored


def test_every_live_log_job_maps_to_an_active_lane_in_this_checkout():
    reg = json.loads((ROOT / mfp.REGISTRY).read_text())
    lanes = mfp.job_log_lanes(mfp._jcm_jobs(), reg["lanes"])
    assert lanes and all(lanes.values()), sorted(j for j, v in lanes.items() if not v)


def test_job_log_lanes_follows_superseded_by_to_the_active_family_lane():
    jobs = [{"name": "topic_ingestion", "schedule_match": "topic_ingestion.py", "signal": ("log", "topic_ingestion.log")}]
    lanes = [
        {"lane_id": "topic-ingestion-cron-lines", "state": "RETIRED", "superseded_by": "topic-ingestion",
         "scheduler": {"command_text": "$PY scripts/topic_ingestion.py"}},
        {"lane_id": "topic-ingestion", "state": "ACTIVE", "scheduler": {"command_text": "run_family_slot.py"}},
        {"lane_id": "old", "state": "RETIRED", "superseded_by": "gone", "scheduler": {"command_text": "topic_ingestion.py"}},
    ]
    assert mfp.job_log_lanes(jobs, lanes) == {"topic_ingestion": {"topic-ingestion"}}
