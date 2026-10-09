"""n8n maturity B4 (2026-10-09): ScalpCycleReceipt@v1 ledger, market-hours-aware monitor, fan-in source 3h.

Why: audit D finding 2.9 counted 25 cron invocations of trade-ai-scalp-live but 3 heartbeats, and could not say
why — a cycle killed by `timeout 295` left no receipt and lost its block-buffered log lines. Fakes only: no
network, no database, no Telegram (run_live_cycle is replaced; the fan-in never sends).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import scalp_cycle_monitor as scm  # noqa: E402
import scalp_cycle_receipt as scr  # noqa: E402

ET = ZoneInfo("America/New_York")
DAY = "2026-10-09"


def regular(dt):  # a normal trading day: regular session 09:30-16:00 ET
    t = dt.astimezone(ET)
    return "regular" if (9 * 60 + 30) <= t.hour * 60 + t.minute < 16 * 60 else "closed"


def early_close(dt):
    t = dt.astimezone(ET)
    return "regular" if (9 * 60 + 30) <= t.hour * 60 + t.minute < 13 * 60 else "closed"


def holiday(_dt):
    return "holiday"


def at(h, m, s=0, day=DAY):
    return datetime.fromisoformat(day).replace(hour=h, minute=m, second=s, tzinfo=ET)


def ok_rec(h, m, seconds=140.0, status="ok", **kw):
    t0 = at(h, m, 5)
    return scr.build(status, day=DAY, slot=f"{h:02d}:{m:02d}", started_at=t0,
                     finished_at=t0 + timedelta(seconds=seconds), deadline_s=295, **kw)


def full_day(until=(16, 0), skip=()):
    out, t = [], at(9, 30)
    while t < at(*until):
        if (t.hour, t.minute) not in skip:
            out.append(ok_rec(t.hour, t.minute))
        t += timedelta(minutes=5)
    return out


# ── receipt ledger ──────────────────────────────────────────────────────────────────────────────────────────


def test_build_has_every_v1_field_and_rejects_unknown_status():
    d = ok_rec(10, 0, seconds=150, symbols_scanned=68, signals=1, triggers=2, alerts_sent=2, alerts_deduped=1,
               errors=["catalysts: Timeout"])
    for k in ("schema", "lane_id", "cycle_id", "slot", "status", "phase", "started_at", "finished_at", "seconds",
              "symbols_scanned", "signals", "alerts_sent", "alerts_deduped", "budget", "errors", "scheduler"):
        assert k in d, k
    assert d["schema"] == "ScalpCycleReceipt@v1" and d["cycle_id"] == "trade-ai-scalp-live:2026-10-09:1000"
    assert d["budget"]["used_pct"] == round(100 * 150 / 295, 1) and d["budget"]["deadline_s"] == 295
    try:
        scr.build("maybe", day=DAY, slot="10:00", started_at=at(10, 0))
    except ValueError:
        pass
    else:
        raise AssertionError("unknown status accepted")


def test_slot_floors_to_the_cadence():
    assert scr.slot_of(at(9, 34, 59)) == "09:30" and scr.slot_of(at(15, 55, 1)) == "15:55"


def test_append_read_fold(tmp_path):
    started = scr.build("started", day=DAY, slot="10:00", started_at=at(10, 0, 5))
    scr.append(started, tmp_path)
    scr.append(ok_rec(10, 0), tmp_path)
    scr.append(scr.build("error", day=DAY, slot="10:00", started_at=at(10, 1), finished_at=at(10, 2)), tmp_path)
    scr.append(scr.build("started", day=DAY, slot="10:05", started_at=at(10, 5, 5)), tmp_path)
    with open(scr.ledger_path(DAY, tmp_path), "a", encoding="utf-8") as fh:
        fh.write("{torn\n")
    recs = scr.read_day(DAY, tmp_path)
    assert len(recs) == 4
    folded = scr.fold(recs)
    assert folded["10:00"]["status"] == "ok"            # a later failed retry never hides the slot's ok
    assert folded["10:05"]["status"] == "started"       # lost cycle (SIGKILL / crash)
    assert scr.read_day("2026-10-08", tmp_path) == []


# ── monitor ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_clean_full_day():
    doc = scm.evaluate(full_day(), at(16, 30), day=DAY, session_fn=regular)
    assert doc["slots_total"] == 78 and doc["slots_ok"] == 78 and doc["ok_rate"] == 1.0
    assert doc["clean_day"] is True and doc["incidents"] == [] and doc["stale"] is False
    assert doc["summary_line"].startswith("Scalp lane 2026-10-09: 78/78 RTH cycles ok (100%)")
    assert "CLEAN day" in doc["summary_line"]


def test_two_consecutive_missed_rth_cycles_is_p2_and_stale_only_in_rth():
    recs = full_day(until=(14, 0))                       # last ok slot 13:55; 14:00 and 14:05 missing
    doc = scm.evaluate(recs, at(14, 11), day=DAY, session_fn=regular)
    assert doc["missed_tail"] == 2
    items = {i["item"]: i["severity"] for i in doc["incidents"]}
    assert items == {"trade-ai-scalp-live:MISSED_CYCLES": "P2"}
    assert doc["stale"] is True                          # last ok 13:57:25 → 13.6 min > 2x cadence
    late = scm.evaluate(recs, at(17, 0), day=DAY, session_fn=regular)
    assert late["incidents"] == [] and late["stale"] is False   # after the close: quiet
    assert late["clean_day"] is False


def test_one_missed_cycle_is_not_an_incident():
    doc = scm.evaluate(full_day(until=(14, 10), skip=((14, 0),)), at(14, 11), day=DAY, session_fn=regular)
    assert doc["missed_tail"] == 0 and doc["incidents"] == [] and doc["stale"] is False


def test_thirty_minutes_without_an_ok_cycle_is_p1():
    recs = full_day(until=(13, 0))
    doc = scm.evaluate(recs, at(13, 33), day=DAY, session_fn=regular)
    sev = {i["item"].split(":")[-1]: i["severity"] for i in doc["incidents"]}
    assert sev == {"MISSED_CYCLES": "P2", "NO_CYCLES_30M": "P1"}


def test_killed_lost_and_late_cycles_count_as_missed():
    recs = full_day(until=(10, 0)) + [
        ok_rec(10, 0, status="killed", seconds=295),
        scr.build("started", day=DAY, slot="10:05", started_at=at(10, 5, 5)),
        ok_rec(10, 10, seconds=400),
    ]
    doc = scm.evaluate(recs, at(10, 19), day=DAY, session_fn=regular)
    assert doc["slot_states"] == {"ok": 6, "killed": 1, "lost": 1, "late": 1}
    assert doc["missed_tail"] == 3 and any(i["severity"] == "P2" for i in doc["incidents"])


def test_first_cycle_grace_no_alarm_at_the_open():
    doc = scm.evaluate([], at(9, 36), day=DAY, session_fn=regular)
    assert doc["incidents"] == [] and doc["stale"] is False and doc["slots_due"] == 1   # one miss: no page
    doc = scm.evaluate([], at(10, 0, 30), day=DAY, session_fn=regular)
    assert {i["severity"] for i in doc["incidents"]} == {"P1", "P2"}


def test_holiday_and_early_close():
    doc = scm.evaluate([], at(12, 0), day=DAY, session_fn=holiday)
    assert doc["slots_total"] == 0 and doc["incidents"] == [] and "market closed" in doc["summary_line"]
    half = scm.evaluate(full_day(until=(13, 0)), at(14, 0), day=DAY, session_fn=early_close)
    assert half["slots_total"] == 42 and half["clean_day"] is True and half["incidents"] == []


def test_clean_day_threshold_allows_a_few_isolated_misses():
    skips = ((10, 0), (12, 0), (14, 0))                   # 75/78 = 96.2 %, no consecutive misses
    assert scm.evaluate(full_day(skip=skips), at(16, 30), day=DAY, session_fn=regular)["clean_day"] is True
    skips = ((10, 0), (10, 5), (12, 0), (12, 5))          # two P2 episodes
    assert scm.evaluate(full_day(skip=skips), at(16, 30), day=DAY, session_fn=regular)["clean_day"] is False


def test_summary_counts_signals_and_alerts():
    recs = [ok_rec(9, 30, signals=1, triggers=1, alerts_sent=1, alerts_deduped=0),
            ok_rec(9, 35, signals=1, triggers=0, alerts_sent=0, alerts_deduped=1)]
    doc = scm.evaluate(recs, at(9, 41), day=DAY, session_fn=regular)
    assert doc["signals"] == 2 and doc["alerts_sent"] == 1 and doc["alerts_deduped"] == 1
    assert "alerts 1 sent/1 deduped" in doc["summary_line"]


def test_cli_reads_the_ledger_and_exit_codes(tmp_path, monkeypatch, capsys):
    import check_scalp_cycles as cli

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(scm, "_default_session_fn", regular)
    for r in full_day(until=(13, 0)):
        scr.append(r, tmp_path)
    assert cli.main(["--date", DAY, "--now", at(13, 33).isoformat(), "--exit-code", "--write"]) == 2
    assert capsys.readouterr().out.startswith("Scalp lane 2026-10-09: 42/")
    doc = json.loads((tmp_path / cli.MONITOR_REL).read_text())
    assert doc["schema"] == "ScalpCycleMonitor@v1"
    assert cli.main(["--date", DAY, "--now", at(17, 0).isoformat(), "--exit-code"]) == 0


# ── fan-in source 3h ────────────────────────────────────────────────────────────────────────────────────────


def test_fanin_source_is_silent_without_a_ledger_and_pages_with_one(tmp_path, monkeypatch):
    from scripts import n8n_incident_fanin as F

    monkeypatch.setattr(scm, "_default_session_fn", regular)
    now = at(13, 33).astimezone(timezone.utc)
    got = F._scalp_cycle_findings(tmp_path, now)                       # no ledger in RTH = no cycles: P1 only
    assert [(g["item"], g["severity"]) for g in got] == [("trade-ai-scalp-live:NO_CYCLES_30M", "P1")]
    assert F.NOTES["scalp_cycle_source"] == "no_ledger"
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / F.SCALP_RECEIPT_REL).write_text(json.dumps(
        {"status": "ok", "last_ok_at": (now - timedelta(minutes=4)).isoformat()}))
    assert F._scalp_cycle_findings(tmp_path, now) == []                # promote day: legacy ok is recent
    assert F._scalp_cycle_findings(tmp_path, at(17, 0).astimezone(timezone.utc)) == []
    for r in full_day(until=(13, 0)):
        scr.append(r, tmp_path)
    got = F._scalp_cycle_findings(tmp_path, now)
    assert {(g["item"], g["severity"]) for g in got} == {("trade-ai-scalp-live:MISSED_CYCLES", "P2"),
                                                         ("trade-ai-scalp-live:NO_CYCLES_30M", "P1")}
    assert all(g["detected_at"] == "2026-10-09T00:00:00+00:00" for g in got)      # one event per day
    assert F._scalp_cycle_findings(tmp_path, at(17, 0).astimezone(timezone.utc)) == []


# ── runner: started + final receipt, error, SIGTERM ─────────────────────────────────────────────────────────


def test_runner_writes_started_and_ok_with_dedupe(tmp_path, monkeypatch):
    import continuous_runner as cr
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    st = cr.CycleState()
    st.prev_go = {"WFF"}
    r.save_state(datetime.now(ET).date().isoformat(), st)

    def fake(root, label, day, state, t, **k):
        k["cycle_stats"].update(phase="done", symbols_scanned=68, signals=2, triggers=1, alert_sent=True)
        state.prev_go = {"WFF", "VIVK"}
        return [{"symbol": "WFF", "decision": "GO"}, {"symbol": "VIVK", "decision": "GO"}]

    monkeypatch.setattr(cr, "run_live_cycle", fake)
    assert r.main(["--force"]) == 0
    recs = scr.read_day(datetime.now(ET).date().isoformat(), tmp_path)
    assert [x["status"] for x in recs] == ["started", "ok"]
    ok = recs[-1]
    assert ok["symbols_scanned"] == 68 and ok["signals"] == 2 and ok["alerts_sent"] == 1
    assert ok["alerts_deduped"] == 1                     # WFF was already GO-alerted today
    assert ok["budget"]["deadline_s"] == 295.0 and ok["budget"]["enrich_budget_s"] == 150.0
    assert getattr(signal.getsignal(signal.SIGTERM), "__name__", "") != "_on_term"   # handler restored


def test_runner_records_an_ingestion_failure_as_error(tmp_path, monkeypatch):
    import continuous_runner as cr
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    def fake(root, label, day, state, t, **k):
        k["cycle_stats"].update(phase="ingest")
        k["cycle_stats"]["errors"].append("ingestion: HTTPError: 503")

    monkeypatch.setattr(cr, "run_live_cycle", fake)
    assert r.main(["--force"]) == 1
    recs = scr.read_day(datetime.now(ET).date().isoformat(), tmp_path)
    assert recs[-1]["status"] == "error" and recs[-1]["phase"] == "ingest"
    legacy = json.loads(r.receipt_path().read_text())
    assert legacy["status"] == "cycle_failed" and legacy["last_ok_at"] is None   # #1589 vocabulary; not advanced
    assert not r.state_path().exists() and not r.projection_path().exists()   # fail closed: nothing published

    def boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(cr, "run_live_cycle", boom)
    assert r.main(["--force"]) == 1
    last = scr.read_day(datetime.now(ET).date().isoformat(), tmp_path)[-1]
    assert last["status"] == "error" and "RuntimeError: db gone" in last["errors"]


def test_live_cycle_reports_phase_and_errors_on_ingestion_failure(monkeypatch, tmp_path):
    import types

    import continuous_runner as cr

    fake = types.ModuleType("finviz_ingestion")

    def _boom(*a, **k):
        raise RuntimeError("finviz 503")

    fake.load_live_candidates = _boom
    monkeypatch.setitem(sys.modules, "finviz_ingestion", fake)
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path / "reports"))
    stats: dict = {}
    assert cr.run_live_cycle(tmp_path, "scalp", DAY, cr.CycleState(), "10:00", publish_dashboard=False,
                             cycle_stats=stats) is None
    assert stats["phase"] == "ingest" and stats["errors"] == ["ingestion: RuntimeError: finviz 503"]


def test_sigterm_writes_a_killed_receipt_and_flushes_the_log(tmp_path):
    """The 295 s timeout sends SIGTERM: the cycle must leave a `killed` receipt and its log lines."""
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import sys, time, types
        sys.path[:0] = [{str(ROOT / 'scripts')!r}, {str(ROOT / 'scripts' / 'lib')!r}]
        import run_trade_ai_scalp_live as r
        fake = types.ModuleType("continuous_runner")
        class CycleState:
            prev_go = set()
            @classmethod
            def from_dict(cls, d): return cls()
            def to_dict(self): return {{}}
        def run_live_cycle(*a, cycle_stats=None, **k):
            cycle_stats["phase"] = "catalysts"
            print("  [live] 68 tickers")
            time.sleep(60)
        fake.CycleState = CycleState
        fake.run_live_cycle = run_live_cycle
        sys.modules["continuous_runner"] = fake
        sys.exit(r.main(["--force"]))
    """), encoding="utf-8")
    log = tmp_path / "cycle.log"
    env = dict(os.environ, TRADEAI_STATE_ROOT=str(tmp_path))
    with open(log, "w", encoding="utf-8") as fh:
        p = subprocess.Popen([sys.executable, str(driver)], stdout=fh, stderr=subprocess.STDOUT, env=env)
        day = datetime.now(ET).date().isoformat()
        deadline = time.time() + 30
        while time.time() < deadline and "68 tickers" not in log.read_text(encoding="utf-8"):
            time.sleep(0.1)
        p.send_signal(signal.SIGTERM)
        rc = p.wait(timeout=30)
    assert rc == 128 + signal.SIGTERM
    recs = scr.read_day(day, tmp_path)
    assert [x["status"] for x in recs] == ["started", "killed"]
    assert recs[-1]["phase"] == "catalysts" and "signal 15" in recs[-1]["errors"]
    text = log.read_text(encoding="utf-8")
    assert "cycle start slot=" in text and "68 tickers" in text and "killed by signal 15 in phase catalysts" in text


def test_runner_passes_a_state_saver_and_skips_a_done_slot(tmp_path, monkeypatch):
    import continuous_runner as cr
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(r, "in_rth", lambda now: True)
    calls = []

    def fake(root, label, day, state, t, **k):
        state.prev_go = {"WFF"}
        k["state_saver"](state)                          # saved before the send
        calls.append(json.loads(r.state_path().read_text())["state"]["prev_go"])
        return []

    monkeypatch.setattr(cr, "run_live_cycle", fake)
    assert r.main([]) == 0 and calls == [["WFF"]]
    assert r.main([]) == 0 and len(calls) == 1            # same slot already ok: no second cycle


def test_live_cycle_saves_state_before_the_send():
    src = (ROOT / "scripts/continuous_runner.py").read_text(encoding="utf-8")
    assert src.index("state_saver(state)") < src.index("send_telegram(msg)")


def test_in_rth_follows_the_market_calendar(monkeypatch):
    import market_session
    import run_trade_ai_scalp_live as r

    monkeypatch.setattr(market_session, "current_market_session", lambda now=None: "closed")
    assert r.in_rth(datetime(2026, 11, 27, 14, 0, tzinfo=ET)) is False    # e.g. a 13:00 early close
    monkeypatch.setattr(market_session, "current_market_session", lambda now=None: 1 / 0)
    assert r.in_rth(datetime(2026, 10, 9, 10, 0, tzinfo=ET)) is True       # calendar broken: fixed window


def test_runner_passes_a_wall_clock_deadline(tmp_path, monkeypatch):
    import continuous_runner as cr
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    seen = {}
    monkeypatch.setattr(cr, "run_live_cycle", lambda *a, **k: seen.update(k) or [])
    assert r.main(["--force"]) == 0
    assert seen["deadline_monotonic"] == r.PROCESS_T0 + 295.0          # from process start, not from enrichment
    assert r.PROCESS_T0 <= time.monotonic()
    assert seen["post_enrich_reserve_s"] == 100.0


def test_live_cycle_defers_lookups_past_the_deadline(monkeypatch, tmp_path):
    """Past deadline - reserve: no per-ticker lookup, no bulk call; names score on the stale cache."""
    import types

    import continuous_runner as cr

    calls = []
    fi = types.ModuleType("finviz_ingestion")

    class _DF:
        def to_dict(self, orient):
            return [{"symbol": "AAA"}, {"symbol": "BBB"}]

    fi.load_live_candidates = lambda *a, **k: {"dataframe": _DF()}
    cc = types.ModuleType("catalyst_cache")
    cc.get_bulk = lambda syms, root, day, ttl: ({}, list(syms)) if ttl == 20 else ({}, [])
    cc.set_bulk = lambda *a, **k: calls.append("set")
    ce = types.ModuleType("catalyst_enrichment")
    ce.enrich_ticker = lambda *a, **k: calls.append("lookup")
    sc = types.ModuleType("scoring")
    sc.filter_candidates = lambda t, root, n: ([x["symbol"] for x in t], t)

    def _stop(*a, **k):
        raise RuntimeError("stop after catalysts")

    sc.score_all = _stop
    si = types.ModuleType("short_interest")
    si.enrich_short_interest = _stop                      # first call of the scoring phase: stop there
    si.apply_squeeze_bonus_to_scores = lambda s: s
    bulk = types.ModuleType("scalp_catalyst_bulk")
    bulk.enrich_bulk = lambda *a, **k: calls.append("bulk")
    db = types.ModuleType("db_adapter")                   # social inject: no database
    db._execute = lambda *a, **k: []
    mc = types.ModuleType("market_context")               # market snapshot: no network
    mc.get_market_snapshot = lambda: {}
    uc = types.ModuleType("universe_coverage")
    uc.inject_prime_setup_universe = lambda *a, **k: 0
    rc = types.ModuleType("ross_catalog_universe")
    rc.inject_ross_catalog_universe = lambda *a, **k: 0
    for name, mod in (("finviz_ingestion", fi), ("catalyst_cache", cc), ("catalyst_enrichment", ce),
                      ("scoring", sc), ("short_interest", si), ("scalp_catalyst_bulk", bulk), ("db_adapter", db),
                      ("market_context", mc), ("universe_coverage", uc), ("ross_catalog_universe", rc)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path / "reports"))
    stats: dict = {}
    cr.run_live_cycle(tmp_path, "scalp", DAY, cr.CycleState(), "10:00", publish_dashboard=False,
                      cycle_stats=stats, bulk_catalysts={"bulk_enabled": True}, enrich_budget_s=150,
                      deadline_monotonic=time.monotonic() + 50, post_enrich_reserve_s=100)
    assert "lookup" not in calls and "bulk" not in calls and stats["symbols_scanned"] == 2
    assert stats["phase"] == "score" and any(e.startswith("scoring: RuntimeError") for e in stats["errors"])


def test_retention_prunes_old_daily_files_only(tmp_path):
    d = tmp_path / scr.LEDGER_REL
    d.mkdir(parents=True)
    for name in ("2026-08-01.jsonl", "2026-09-09.jsonl", "2026-09-10.jsonl", "notes.jsonl"):
        (d / name).write_text("")
    scr.append(ok_rec(10, 0), tmp_path)                                # first record of 2026-10-09 prunes
    assert sorted(f.name for f in d.iterdir()) == ["2026-09-09.jsonl", "2026-09-10.jsonl", "2026-10-09.jsonl",
                                                    "notes.jsonl"]


def test_schemas_are_registered_and_match_the_writers():
    sdir = ROOT / "docs/implementation/n8n-maturity/schemas"
    rs = json.loads((sdir / "scalp-cycle-receipt.schema.json").read_text())
    ms = json.loads((sdir / "scalp-cycle-monitor.schema.json").read_text())
    rec = ok_rec(10, 0, phase_s={"ingest": 61.2}, budget_skips=["market"])
    assert rs["properties"]["schema"]["const"] == rec["schema"] == scr.SCHEMA
    assert set(rs["required"]) <= set(rec) and set(rs["properties"]["status"]["enum"]) == set(scr.STATUSES)
    assert rs["x-legacy-status-map"] == scr.LEGACY_STATUS and rs["x-retention-days"] == scr.RETENTION_DAYS
    assert set(rec) <= set(rs["properties"]) and rec["budget"]["phase_s"] == {"ingest": 61.2}
    doc = scm.evaluate(full_day(), at(16, 30), day=DAY, session_fn=regular)
    assert ms["properties"]["schema"]["const"] == doc["schema"] and set(ms["required"]) <= set(doc)
    assert set(doc) <= set(ms["properties"])


def test_ledger_uses_the_shared_state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert scr.state_root() == tmp_path
    assert scr.ledger_path(DAY) == tmp_path / "data/runtime/scalp_cycle_receipts/2026-10-09.jsonl"
