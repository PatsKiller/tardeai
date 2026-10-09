"""Breach triage code fixes (2026-10-09, ~/n8n-maturity-program/breach-triage-20261009.md).

1. One shared 5-field extractor (cron_schedule.cron_fields / cron_schedules) for every staleness path:
   cron_last_fire.parse, the breach detector, the job coverage monitor, scheduler operations and source
   clocks. Registry rows store "<5 fields> <command>" (101 of 421 ACTIVE cron lanes) and "a + b" for lanes
   run by several crontab lines (13); both fell back to the 3 x cadence rule before.
2. refresh_symbol_cards: endpoint timeout + retry from config/symbol_cards_refresh.yaml.
3. topic_curator --ensemble: no DB connection held across the LLM calls; its own per-run receipt.
4. stop_health_check: a per-run heartbeat, also under --quiet and on failure.
Hermetic: no DB, no network, no broker, no live stores (every output path is tmp_path).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts import job_coverage_monitor as jcm  # noqa: E402
from scripts import refresh_symbol_cards as rsc  # noqa: E402
from scripts import stop_health_check as shc  # noqa: E402
from scripts import supervisor_breach_detector as sbd  # noqa: E402
from scripts import topic_curator as tc  # noqa: E402
from scripts.lib import cio_source_clocks as csc  # noqa: E402
from scripts.lib import cron_last_fire as clf  # noqa: E402
from scripts.lib import cron_schedule as cs  # noqa: E402
from scripts.lib import scheduler_operations as so  # noqa: E402

NY = ZoneInfo("America/New_York")


# ── 1. shared extractor ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("expr,fields", [
    ("*/15 9-16 * * 1-5 portfolio_repricer.py", "*/15 9-16 * * 1-5"),
    ("0 6 * * MON-FRI cd $PROJ && x.py", "0 6 * * 1-5"),
    ("0 6 1 Jan *", "0 6 1 1 *"),
    ("@daily", "0 0 * * *"),
    ("@reboot cd /x && y", cs.REBOOT),
    ("@nonsense", None),
    ("0 6 *", None),
    ("", None),
])
def test_cron_fields(expr, fields):
    assert cs.cron_fields(expr) == fields
    assert sbd._cron_fields(expr) == fields  # the detector delegates to the shared extractor


def test_cron_schedules_splits_multi_line_lanes():
    assert cs.cron_schedules("45 20 * * 1-5 + 45 2 * * *") == ["45 20 * * 1-5", "45 2 * * *"]
    assert cs.cron_schedules("0 12,14,16 * * 1-5 + 30 17 * * 1-5 run_orchestrator_slot.sh") == [
        "0 12,14,16 * * 1-5", "30 17 * * 1-5"]
    assert cs.cron_schedules("*/5 * * * * x.py") == ["*/5 * * * *"]


def test_cron_schedule_parse_stays_strict():
    with pytest.raises(ValueError):
        cs.parse("*/15 9-16 * * 1-5 portfolio_repricer.py")


def test_cron_last_fire_reads_command_text_rows():
    now = dt.datetime(2026, 10, 9, 19, 45)  # Fri evening
    assert clf.last_fire("*/15 9-16 * * 1-5 portfolio_repricer.py", now) == dt.datetime(2026, 10, 9, 16, 45)
    assert clf.parse("@reboot") is None
    assert clf.parse("0 6 * * mon x.py")["dows"] == {1}


def _lane(expr, cad=0.25):
    return {"lane_id": "l", "state": "ACTIVE", "expected_cadence_hours": cad,
            "scheduler": {"kind": "cron", "expression": expr}}


def test_detector_command_text_row_uses_the_schedule_not_three_x_cadence():
    now = dt.datetime(2026, 10, 9, 19, 50, tzinfo=NY).astimezone(dt.timezone.utc)
    deadline, basis = sbd._expected_since(_lane("*/15 9-16 * * 1-5 portfolio_repricer.py"), now)
    assert basis == "cron:*/15 9-16 * * 1-5"
    assert deadline == dt.datetime(2026, 10, 9, 16, 45, tzinfo=NY).astimezone(dt.timezone.utc)


def test_detector_multi_schedule_row_takes_the_latest_fire_of_any_line():
    # 03:00 Saturday: the weekday 20:45 line last fired Fri 20:45, the daily 02:45 line fired at 02:45 today.
    now = dt.datetime(2026, 10, 10, 3, 0, tzinfo=NY).astimezone(dt.timezone.utc)
    deadline, basis = sbd._expected_since(_lane("45 20 * * 1-5 + 45 2 * * *", 24.0), now, max_run_s=0)
    assert basis == "cron:45 2 * * *"
    assert deadline == dt.datetime(2026, 10, 10, 2, 45, tzinfo=NY).astimezone(dt.timezone.utc)


def test_detector_reboot_lane_keeps_the_cadence_rule():
    now = dt.datetime(2026, 10, 9, 23, 50, tzinfo=dt.timezone.utc)
    _, basis = sbd._expected_since(_lane("@reboot x", 1.0), now)
    assert basis.startswith("cadence:")


def test_job_coverage_monitor_uses_the_shared_extractor():
    lines = ["0 6 * * MON-FRI cd /p && python3 scripts/a.py >> logs/a.log", "@reboot cd /p && python3 scripts/a.py",
             "@daily cd /p && python3 scripts/a.py", "*/5 * * * * python3 scripts/b.py"]
    assert jcm._cron_exprs("scripts/a.py", lines) == ["0 6 * * 1-5", "0 0 * * *"]


def test_scheduler_operations_matches_any_schedule_of_a_multi_line_lane():
    lane = {"scheduler": {"kind": "cron", "match": "x.py", "expression": "45 20 * * 1-5 + 45 2 * * * x.py"}}
    hit = {"expression": "45 2 * * *", "command": "cd /p && python3 x.py"}
    other = {"expression": "10 16 * * 1-5", "command": "cd /p && python3 x.py"}
    assert so._cron_matches(lane, hit) and so._cron_matches(lane, {**hit, "expression": "45 20 * * 1-5"})
    assert not so._cron_matches(lane, other)
    single = {"scheduler": {"kind": "cron", "match": "x.py", "expression": "*/15 9-16 * * 1-5 x.py"}}
    assert so._cron_matches(single, {"expression": "*/15 9-16 * * 1-5", "command": "x.py"})


def test_source_clocks_next_fire_reads_names_and_command_text():
    now = dt.datetime(2026, 10, 9, 19, 50, tzinfo=NY)  # Friday
    nxt = csc.next_cron_fire("30 6 * * MON-FRI scripts/x.py --flag", now)
    assert nxt == dt.datetime(2026, 10, 12, 6, 30, tzinfo=NY).astimezone(dt.timezone.utc)
    assert csc.next_cron_fire("@reboot x", now) is None


# ── 2. refresh_symbol_cards ─────────────────────────────────────────────────────────────────────────
def test_symbol_cards_policy_from_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("materialize_timeout_s: 240\nmaterialize_retries: 2\nretry_backoff_s: 5\nmin_cards: 10\n")
    assert rsc.load_policy(p) == {"materialize_timeout_s": 240.0, "materialize_retries": 2,
                                  "retry_backoff_s": 5.0, "min_cards": 10}
    shipped = rsc.load_policy()
    assert shipped["materialize_timeout_s"] >= 180 and shipped["materialize_retries"] >= 1


def _stub_cards(monkeypatch, tmp_path, outcomes):
    calls = []
    monkeypatch.setattr(rsc, "CARDS_FILE", tmp_path / "symbol_cards_latest.json")
    monkeypatch.setattr(rsc.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "ok", "stderr": ""})())
    monkeypatch.setattr(rsc.time, "sleep", lambda s: calls.append(("sleep", s)))
    monkeypatch.setattr(rsc, "load_policy", lambda: {"materialize_timeout_s": 180.0, "materialize_retries": 1,
                                                     "retry_backoff_s": 30.0, "min_cards": 30})

    def fetch(timeout_s, min_cards):
        calls.append(("fetch", timeout_s))
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o
    monkeypatch.setattr(rsc, "_fetch_cards", fetch)
    monkeypatch.setattr(sys, "argv", ["refresh_symbol_cards.py"])
    return calls


def test_symbol_cards_retry_once_after_a_timeout(monkeypatch, tmp_path):
    calls = _stub_cards(monkeypatch, tmp_path, [TimeoutError("timed out"), (b'{"data":{"cards":{}}}', 3329)])
    assert rsc.main() == 0
    assert calls == [("fetch", 180.0), ("sleep", 30.0), ("fetch", 180.0)]
    assert (tmp_path / "symbol_cards_latest.json").read_bytes() == b'{"data":{"cards":{}}}'


def test_symbol_cards_keeps_the_file_when_every_attempt_fails(monkeypatch, tmp_path):
    (tmp_path / "symbol_cards_latest.json").write_text("old")
    _stub_cards(monkeypatch, tmp_path, [TimeoutError("t1"), TimeoutError("t2")])
    assert rsc.main() == 1
    assert (tmp_path / "symbol_cards_latest.json").read_text() == "old"


# ── 3. topic curator ensemble ───────────────────────────────────────────────────────────────────────
class _Conn:
    def __init__(self, log, rows):
        self.log, self.rows, self.closed = log, rows, False

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                conn.log.append(("execute", sql.split()[0]))

            def fetchall(self):
                return conn.rows
        return C()

    def commit(self):
        self.log.append(("commit",))

    def close(self):
        self.closed = True
        self.log.append(("close",))


def test_ensemble_holds_no_connection_across_llm_calls(tmp_path, monkeypatch):
    log, conns = [], []
    rows = [(1, "a", "s", "t1"), (2, "b", None, "t1")]

    def connect():
        c = _Conn(log, rows); conns.append(c); log.append(("connect",)); return c

    def validate(text, **kw):
        assert all(c.closed for c in conns), "a connection was open during an LLM call"
        log.append(("llm",))
        return {"final_decision": "approve", "consensus_reached": True, "final_score": 7,
                "lanes_used": ["grok"]} if text.startswith("a") else {"final_decision": "reject"}

    import lib.writers.news_articles_writer as naw
    monkeypatch.setattr(naw, "set_rag_status", lambda cur, rid, st, reason: log.append(("set", rid, st)))
    rp = tmp_path / "ensemble.json"
    assert tc.ensemble_rescue(None, 5, connect=connect, validate=validate, receipt_path=rp) == 1
    assert [e[0] for e in log] == ["connect", "execute", "close", "llm", "llm", "connect", "set", "commit", "close"]
    rec = json.loads(rp.read_text())
    assert rec["status"] == "ok" and rec["candidates"] == 2 and rec["upgraded"] == 1 and rec["finished_at"]


def test_ensemble_failure_is_visible_in_its_receipt(tmp_path):
    def connect():
        raise RuntimeError("SSL connection has been closed unexpectedly")

    rp = tmp_path / "ensemble.json"
    assert tc.ensemble_rescue(None, 5, connect=connect, validate=lambda *a, **k: {}, receipt_path=rp) == 0
    rec = json.loads(rp.read_text())
    assert rec["status"] == "error" and rec["stage"] == "read" and "SSL" in rec["error"]


# ── 4. stop health heartbeat ────────────────────────────────────────────────────────────────────────
def test_stop_health_quiet_run_writes_a_heartbeat(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(shc, "run", lambda quiet=False: seen.setdefault("quiet", quiet) and {
        "summary": {"total": 12, "by_health": {"ok": 12}, "incident_recovery": {"ok": True}},
        "alert_count": 0, "telegram_fired": []})
    hb = tmp_path / "stop_health_last.json"
    shc.main(["--quiet"], heartbeat_path=hb)
    doc = json.loads(hb.read_text())
    assert seen["quiet"] is True
    assert doc["schema"] == "StopHealthRun@v1" and doc["status"] == "ok" and doc["stops"] == 12
    assert doc["alert_count"] == 0 and doc["finished_at"]


def test_stop_health_failure_still_writes_a_heartbeat_and_raises(tmp_path, monkeypatch):
    def boom(quiet=False):
        raise RuntimeError("scan failed")
    monkeypatch.setattr(shc, "run", boom)
    hb = tmp_path / "hb.json"
    with pytest.raises(RuntimeError):
        shc.main(["--quiet"], heartbeat_path=hb)
    assert json.loads(hb.read_text())["status"] == "error"


def test_stop_health_check_places_no_orders():
    src = (ROOT / "scripts" / "stop_health_check.py").read_text(encoding="utf-8")
    for token in ("place_order", "submit_order", "cancel_order", "replace_order"):
        assert token not in src


def test_registry_signals_point_at_the_new_receipts():
    lanes = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
    assert lanes["topic-curator-ensemble"]["output_signal"]["path"] == "data/runtime/topic_curator_ensemble_latest.json"
    assert lanes["stop-health-check"]["output_signal"]["path"] == "data/runtime/stop_health_last.json"
    assert str(tc.ENSEMBLE_RECEIPT).endswith("data/runtime/topic_curator_ensemble_latest.json")
    assert str(shc.HEARTBEAT_FILE).endswith("data/runtime/stop_health_last.json")
