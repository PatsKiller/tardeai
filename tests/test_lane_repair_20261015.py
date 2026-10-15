"""Lane repair 2026-10-15: build-symbol-profiles, watchlist entry planner, indicator-engine ("turn on", then n8n shadow).

Pinned root causes (evidence: logs/symbol_profiles*.log, logs/entry_planner.log, logs/indicator_engine.log):

* build-symbol-profiles: the SELECT transaction stayed open through the Finviz batch and per-symbol yfinance calls;
  db_adapter's idle_in_transaction_session_timeout (120 s) killed the session ("SSL connection has been closed
  unexpectedly" on the first upsert), and the one long write transaction tripped lock_timeout (LockNotAvailable).
  Now: the read ends before any provider call; one short transaction per symbol; reconnect / lock retry, then a typed
  skip.
* watchlist_entry_planner: lib/comms/delivery.py closed db_adapter's THREAD-LOCAL connection after every send, so the
  planner's alerted_at UPDATE raised "InterfaceError: cursor already closed" after the first alert. Now: no close at
  the source; the planner re-checks its connection after the send; the n8n entry plans only (no sender in reach).
* indicator-engine: the cron line ran the module's AMD CLI test mode. Now: ``--universe`` gap-fills
  indicator_confluence_cache over the indicator_cache_refresh universe, bounded and idempotent.

Plus the n8n shadow wiring (registry / allowlist / REVIEWED contract with N8nExpectedOutput@v1 / effect key) and the
LaneOutput@v1 counts. Hermetic: fake DB modules via sys.modules, no network, TRADEAI_STATE_ROOT = tmp, repo config
read only.
"""
from __future__ import annotations

import json
import re
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_symbol_profiles as bsp  # noqa: E402
import watchlist_entry_planner as wep  # noqa: E402
import watchlist_entry_planner_lane as wepl  # noqa: E402
from lib import indicator_universe_lane as iul  # noqa: E402
from lib import lane_output as lo  # noqa: E402
from scripts.lib import advisory_lane_guard as G  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW_DOC = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
ALLOW = {e["lane_id"]: e for e in ALLOW_DOC["lanes"]}
# Train 2026-10-15 d: the four lanes' n8n wiring is DEFERRED (not the repair): their import closure reaches
# broker_module / order_placement through db_adapter -> holdings_guard -> schwab_position_sync, which the SHRINK-ONLY
# capability baseline (tests/test_lane_transitive_capabilities_20261015.py) refuses without operator review. The
# allowlist entry moved into blocked_reasons[lane] ("Deferred entry: {...}") and the registry dispatch is off.
DEFERRED_MARK = "Deferred entry: "


def _deferred_entry(lane: str) -> dict:
    reason = ALLOW_DOC["blocked_reasons"][lane]
    assert "DD01 capability audit" in reason and "holdings_guard" in reason, reason
    return json.loads(reason.split(DEFERRED_MARK, 1)[1])
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}
EFFECTS = json.loads((ROOT / "config" / "n8n_effect_keys.json").read_text())["lanes"]

SHADOW = {  # lane -> (class, live cron schedule, argv after $PY, receipt stem, scheduler.wave)
    "build-symbol-profiles-at-0-19": ("ingest", "0 19 * * 0", ["scripts/build_symbol_profiles.py"],
                                      "build-symbol-profiles-at-0-19", "R2-05"),
    "indicator-engine": ("ingest", "0 8 * * 1-5", ["scripts/indicator_engine.py", "--universe"], "indicator-engine",
                         "LR-W1"),
}
STAGED = {  # lane -> (live cron schedule, argv after $PY, receipt stem, cron flock lock)
    "watchlist-entry-planner-limit": ("35 17 * * 1-5",
                                      ["scripts/watchlist_entry_planner_lane.py", "--limit", "60", "--buy-rated-cap",
                                       "400"], "watchlist_entry_planner", "/tmp/entry_planner.lock"),
    "watchlist-entry-planner-scope": ("45 17 * * 1-5",
                                      ["scripts/watchlist_entry_planner_lane.py", "--scope", "proposals"],
                                      "watchlist_entry_planner_proposals", "/tmp/entry_planner_prop.lock"),
}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


# ── LaneOutput@v1 ───────────────────────────────────────────────────────────────────────────────────────────────
def test_lane_output_block_and_line_round_trip(capsys):
    block = lo.output_block(unit="rows", produced=0, attempted=3, skipped={"no_bars": 2, "x": 0, "y": 1},
                            empty_reason="all_skipped")
    assert block == {"schema": "LaneOutput@v1", "unit": "rows", "produced_count": 0, "attempted_count": 3,
                     "skipped_reasons": {"no_bars": 2, "y": 1}, "empty_reason": "all_skipped"}
    lo.emit("lane-x", "dry_run", block, started_at="t0")
    err = capsys.readouterr().err
    parsed = lo.parse(err)
    assert parsed["lane_id"] == "lane-x" and parsed["mode"] == "dry_run" and parsed["attempted_count"] == 3
    assert lo.output_block(unit="u", produced=2, attempted=2, empty_reason="ignored")["empty_reason"] is None


@pytest.mark.parametrize("bad", [True, -1, 1.5, "3"])
def test_lane_output_counts_are_integers(bad):
    with pytest.raises(ValueError):
        lo.output_block(unit="u", produced=bad, attempted=0)


# ── 1. build-symbol-profiles ────────────────────────────────────────────────────────────────────────────────────
class FakeConn:
    def __init__(self, answers):
        self.answers = answers
        self.log: list = []

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                conn.log.append(("execute", " ".join(sql.split())))
                self._rows = next((rows for sub, rows in conn.answers if sub in sql), [])

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))


@pytest.fixture
def bsp_env(monkeypatch, state):
    conn = FakeConn([("updated_at > now() - interval '30 days'", [("AAA",)]),
                     ("COALESCE(source, '') = 'finviz'", [])])
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn,
                                                                         close_thread_conn=lambda: None))
    monkeypatch.setitem(sys.modules, "watch_universe", types.SimpleNamespace(symbols=lambda cur: {"AAA", "BBB", "CCC",
                                                                                                  "DDD"}))
    monkeypatch.setitem(sys.modules, "holding_proxies", types.SimpleNamespace(HOLDING_PROXY_MAP={}))
    monkeypatch.setattr(bsp, "_profile_lane", lambda: {"db_lock_retry_sleep_s": 0})
    monkeypatch.setattr(bsp, "_cio_ranked", lambda n: [])

    class T:
        def __init__(self, s):
            self.info = {"longBusinessSummary": f"{s} makes things.", "sector": "Tech"}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    return conn


class OpErr(Exception):
    pass


class LockErr(OpErr):
    pass


def test_bsp_read_transaction_ends_before_any_provider_call(bsp_env, monkeypatch):
    def finviz(uni):
        bsp_env.log.append(("finviz",))
        return {}

    monkeypatch.setattr(bsp, "_finviz_map", finviz)
    monkeypatch.setattr(bsp, "upsert_profile", lambda cur, sym, f, source: types.SimpleNamespace(rows_written=1,
                                                                                                  rows_rejected=0))
    out = bsp.run()
    log = bsp_env.log
    at = log.index(("finviz",))
    assert log[at - 1] == ("rollback",), log  # the SELECT transaction ended before Finviz
    assert sum(1 for e in log[at:] if e == ("commit",)) == 3  # one short transaction per written symbol
    assert out["updated"] == 3 and out["output"]["produced_count"] == 3 and out["output"]["attempted_count"] == 3


def test_bsp_lock_timeout_retries_once_then_skips_and_the_drain_continues(bsp_env, monkeypatch, state):
    monkeypatch.setattr(bsp, "_finviz_map", lambda uni: {})
    monkeypatch.setattr(bsp, "_db_errors", lambda: ((OpErr,), LockErr))
    tries = {"BBB": 0, "CCC": 0}

    def upsert(cur, sym, f, source):
        if sym == "BBB":
            tries["BBB"] += 1
            raise LockErr("canceling statement due to lock timeout")
        if sym == "CCC" and tries["CCC"] == 0:
            tries["CCC"] += 1
            raise OpErr("SSL connection has been closed unexpectedly")
        return types.SimpleNamespace(rows_written=1, rows_rejected=0)

    monkeypatch.setattr(bsp, "upsert_profile", upsert)
    assert bsp.main([]) == 1  # a lost write is an honest non-zero exit
    assert tries == {"BBB": 2, "CCC": 1}
    own = json.loads((state / "data/runtime/build-symbol-profiles-at-0-19_last.json").read_text())
    out = own["summary"]["output"]
    assert own["status"] == "failed" and own["exit"] == 1
    assert out["produced_count"] == 2 and out["attempted_count"] == 3
    assert out["skipped_reasons"] == {"db_lock_timeout": 1}


def test_bsp_provider_misses_are_typed_skips_not_failures(bsp_env, monkeypatch, state):
    class T:
        def __init__(self, s):
            self.info = {} if s == "BBB" else {"longBusinessSummary": "x.", "sector": "Tech"}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    monkeypatch.setattr(bsp, "_finviz_map", lambda uni: {})
    monkeypatch.setattr(bsp, "upsert_profile", lambda cur, sym, f, source: types.SimpleNamespace(rows_written=1,
                                                                                                  rows_rejected=0))
    assert bsp.main([]) == 0
    own = json.loads((state / "data/runtime/build-symbol-profiles-at-0-19_last.json").read_text())
    assert own["status"] == "ok" and own["summary"]["output"]["skipped_reasons"] == {"provider_no_profile": 1}


def test_bsp_offline_dry_run_emits_lane_output_and_writes_nothing(state, capsys, monkeypatch):
    monkeypatch.setattr(bsp, "run", lambda **kw: pytest.fail("offline preview reached run"))
    assert bsp.main(["--dry-run"]) == 0
    cap = capsys.readouterr()
    assert "DRY-RUN build-symbol-profiles-at-0-19: would" in cap.out
    assert lo.parse(cap.err)["empty_reason"] == "dry_run_offline" and not state.exists()


# ── 2. watchlist entry planner ──────────────────────────────────────────────────────────────────────────────────
class ConnClosed(Exception):
    pass


class PConn:
    """A psycopg2-like connection whose cursors fail once the connection is closed."""

    ids = iter(range(100, 1000))

    def __init__(self, log):
        self.closed = False
        self.log = log

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                if conn.closed:
                    raise ConnClosed("cursor already closed")
                conn.log.append((id(conn), " ".join(sql.split())[:60], params))
                self._one = (next(PConn.ids),) if "RETURNING id" in sql else ((1,) if sql.strip() == "SELECT 1"
                                                                                  else None)

            def fetchone(self):
                return self._one

        return C()

    def commit(self):
        if self.closed:
            raise ConnClosed("connection already closed")

    def rollback(self):
        pass


@pytest.fixture
def planner_env(monkeypatch):
    log: list = []
    holder = {"conn": PConn(log)}

    def get_conn():
        if holder["conn"].closed:
            holder["conn"] = PConn(log)
        return holder["conn"]

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=get_conn,
                                                                         close_thread_conn=lambda: None))
    plan = {"entry_thesis": "pullback into support", "setup_type": "pullback", "entry_zone_low": 9.5,
            "entry_zone_high": 10.5, "limit_price": 10.0, "stop_price": 9.0, "target_price": 13.0,
            "risk_reward": 3.0, "urgency": "ready", "confidence": 0.8, "invalidation": "close < 9",
            "proposal": {"tag": "READY", "suggested_entry": 10.0, "sizing_rationale": "small"}}
    llm_calls = []
    monkeypatch.setitem(sys.modules, "llm_lane", types.SimpleNamespace(
        available=lambda name: True,
        generate=lambda prompt, **kw: llm_calls.append(kw) or json.dumps(plan)))
    monkeypatch.setattr(wep, "_candidates", lambda cur, limit, symbols, scope, cap: [
        {"symbol": "AAA", "hermes_composite_score": 1, "hermes_rank": 1, "trend": "up"},
        {"symbol": "BBB", "hermes_composite_score": 1, "hermes_rank": 2, "trend": "up"}])
    monkeypatch.setattr(wep, "_bars", lambda sym: [{"close": 10.0}])
    monkeypatch.setattr(wep, "_tech", lambda bars: {"price": 10.0, "rsi": 50, "atr": 0.5, "swing_high": 11.0,
                                                    "swing_low": 9.0, "sma50": 10.0})
    monkeypatch.setattr(wep, "_analyst", lambda cur, sym: {"tgt_mean": "n/a", "tgt_low": "n/a", "tgt_high": "n/a",
                                                           "rec_key": "n/a", "n_analysts": 0, "tgt_mean_num": None})
    return holder, log, llm_calls


def test_planner_survives_a_send_path_that_closes_the_thread_connection(planner_env):
    holder, log, _ = planner_env
    sent = []

    def alerter(sym, p, urg, price):
        sent.append(sym)
        holder["conn"].closed = True  # what lib/comms/delivery.py did before 2026-10-15
        return True

    res = wep.plan_run(limit=5, alerter=alerter)
    updates = [e for e in log if e[1].startswith("UPDATE watchlist_entry_plans SET alerted_at")]
    assert sent == ["AAA", "BBB"] and res["planned"] == 2 and res["alerts"] == 2
    assert len(updates) == 2  # alerted_at stamped for both (it never was: the 20 h dedup could re-alert)
    assert res["output"]["produced_count"] == 2 and res["output"]["attempted_count"] == 2


def test_planner_plan_only_counts_alerts_not_sent(planner_env):
    _, log, _ = planner_env
    res = wep.plan_run(limit=5, alerter=None)
    assert res["planned"] == 2 and res["alerts"] == 0 and res["alerts_not_sent"] == 2
    assert not [e for e in log if e[1].startswith("UPDATE")]


def test_planner_lane_entry_has_no_sender_in_reach():
    src = (ROOT / "scripts" / "watchlist_entry_planner_lane.py").read_text()
    assert "_alert" not in re.sub(r'""".*?"""', "", src, flags=re.S)
    rep = G.scan_entry("scripts/watchlist_entry_planner_lane.py")
    assert not rep.is_sender and not rep.broker_modules and not rep.problems()
    assert G.scan_entry("scripts/watchlist_entry_planner.py").is_sender  # why the n8n entry is separate


def test_planner_lane_dry_run_is_the_preview_only(monkeypatch, capsys, state):
    monkeypatch.setattr(wepl, "plan_run", lambda **kw: pytest.fail("dry run reached plan_run"))
    seen = {}
    monkeypatch.setattr(wepl, "preview", lambda **kw: seen.update(kw) or {"candidates": 7})
    assert wepl.main(["--limit", "60", "--buy-rated-cap", "400", "--dry-run"]) == 0
    assert seen["alert"] is False and seen["limit"] == 60 and seen["buy_rated_cap"] == 400
    line = lo.parse(capsys.readouterr().err)
    assert line["lane_id"] == "watchlist_entry_planner" and line["attempted_count"] == 7 and not state.exists()


def test_planner_lane_live_writes_receipt_and_never_sends(monkeypatch, state):
    monkeypatch.setattr(wepl, "plan_run", lambda **kw: {"candidates": 2, "planned": 2, "failed": 0, "alerts": 0,
                                                        "alerts_not_sent": 1, "lane": "grok",
                                                        "output": lo.output_block(unit="u", produced=2, attempted=2)}
                        if kw["alerter"] is None else pytest.fail("alerter passed"))
    assert wepl.main(["--scope", "proposals"]) == 0
    doc = json.loads((state / "data/runtime/watchlist_entry_planner_proposals_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"]["alerts_not_sent"] == 1


def test_comms_settlement_leaves_the_thread_local_connection_open(monkeypatch):
    from scripts.lib.comms.delivery import _persist_event_settlement_pg

    class Conn:
        closed = False

        def cursor(self):
            return types.SimpleNamespace(execute=lambda *a, **k: None, rowcount=1)

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            Conn.closed = True

    conn = Conn()
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    _persist_event_settlement_pg("evt-1", status="SENT", provider_message_id="m1", settled_at=None)
    assert Conn.closed is False


# ── 3. indicator-engine universe lane ───────────────────────────────────────────────────────────────────────────
def _norm(s):
    return " ".join(s.split())


def test_universe_is_the_indicator_cache_refresh_selection_verbatim():
    raw = (ROOT / "scripts" / "indicator_cache_refresh.py").read_text()
    src = _norm(re.sub(r'"\s+"', "", raw))  # join adjacent string literals ("... master " "WHERE ...")
    assert _norm(iul.UNIVERSE_BASE_SQL) in src and _norm(iul.UNIVERSE_SCREENER_SQL) in src


class IConn:
    def __init__(self, universe, screener, fresh):
        self.universe, self.screener, self.fresh = universe, screener, fresh
        self.log: list = []

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                conn.log.append(("execute", _norm(sql)[:40], params))
                if "watchlist_symbol_master" in sql:
                    self._rows = [(s,) for s in conn.universe]
                elif "trade_ai_scans" in sql:
                    self._rows = [(s,) for s in conn.screener]
                elif "FROM indicator_confluence_cache" in sql:
                    self._rows = [(s, t) for s, t in conn.fresh.items() if s in params[1]]
                elif sql.startswith("INSERT INTO indicator_confluence_cache"):
                    conn.fresh[params[0]] = datetime.now(timezone.utc)
                    self._rows = []

            def fetchall(self):
                return list(self._rows)

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))


NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
CFG = {"profile": "swing", "stale_after_hours": 6, "max_symbols": 10, "cache_ttl_minutes": 60}


def _ok(sym, profile):
    return {"ok": True, "symbol": sym, "confluence_score": 5, "confluence_tier": "MODERATE", "key_levels": {}}


def test_stale_selection_missing_first_then_oldest_and_proxy_codes_excluded():
    conn = IConn(["OLD", "NEW", "MISS", "FID-X"], ["SCR"],
                 {"OLD": NOW - timedelta(hours=30), "NEW": NOW - timedelta(hours=1), "SCR": NOW - timedelta(hours=7)})
    out = iul.run(dry_run=True, get_conn=lambda: conn, config=CFG, now=NOW, exclude=["FID-X"],
                  analyze=lambda *a: pytest.fail("dry run analyzed"))
    assert out["sample"] == ["MISS", "OLD", "SCR"] and out["proxy_codes_excluded"] == 1 and out["universe"] == 5
    assert ("set_session", {"readonly": True}) in conn.log and ("commit",) not in conn.log
    assert out["output"]["attempted_count"] == 3 and out["output"]["produced_count"] == 0


def test_universe_run_upserts_stale_rows_and_a_second_run_is_a_no_op():
    conn = IConn(["AAA", "BBB", "CCC"], [], {"CCC": NOW - timedelta(hours=1)})

    def analyze(sym, profile):
        return _ok(sym, profile) if sym == "AAA" else {"ok": False, "error": f"No OHLCV data for {sym}"}

    first = iul.run(get_conn=lambda: conn, analyze=analyze, rate_limited=lambda: False, config=CFG, now=NOW,
                    exclude=[])
    assert first["output"]["produced_count"] == 1 and first["output"]["attempted_count"] == 2
    assert first["output"]["skipped_reasons"] == {"no_ohlcv": 1} and iul.work_ok(first)
    inserts = [e for e in conn.log if e[0] == "execute" and e[1].startswith("INSERT INTO indicator_confl")]
    assert len(inserts) == 1 and inserts[0][2][0] == "AAA" and inserts[0][2][1] == "swing"
    assert inserts[0][2][-1] == 60  # ttl from config, not a literal
    conn.fresh["BBB"] = NOW  # BBB got data from the 05:45 run meanwhile
    second = iul.run(get_conn=lambda: conn, analyze=lambda *a: pytest.fail("fresh rows recomputed"),
                     rate_limited=lambda: False, config=CFG, now=NOW + timedelta(minutes=5), exclude=[])
    assert second["output"]["produced_count"] == 0 and second["output"]["empty_reason"] == "no_stale_symbols"
    assert iul.work_ok(second)


def test_universe_run_with_work_but_nothing_landed_fails_with_a_typed_reason():
    conn = IConn(["AAA", "BBB"], [], {})
    out = iul.run(get_conn=lambda: conn, analyze=lambda s, p: {"ok": False, "error": "No OHLCV data"},
                  rate_limited=lambda: True, config=CFG, now=NOW, exclude=[])
    assert out["output"]["skipped_reasons"] == {"provider_rate_limited": 2} and not iul.work_ok(out)


def test_universe_cap_bounds_the_run():
    conn = IConn([f"S{i}" for i in range(12)], [], {})
    out = iul.run(dry_run=True, get_conn=lambda: conn, config={**CFG, "max_symbols": 4}, now=NOW, exclude=[])
    assert out["would_compute"] == 4 and out["capped"] == 8


def test_universe_main_writes_receipt_and_exits_honestly(monkeypatch, state, capsys):
    conn = IConn(["AAA"], [], {})
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn,
                                                                         close_thread_conn=lambda: None))
    monkeypatch.setitem(sys.modules, "indicator_engine", types.SimpleNamespace(
        analyze_confluence=lambda s, p: {"ok": False, "error": "boom"}, _rate_limit_cooldown_active=lambda: False))
    monkeypatch.setattr(iul, "load_config", lambda path=None: dict(CFG))
    monkeypatch.setattr(iul, "proxy_codes", lambda: frozenset())
    assert iul.main(["--universe"]) == 1
    doc = json.loads((state / "data/runtime/indicator-engine_last.json").read_text())
    assert doc["status"] == "failed" and doc["summary"]["output"]["skipped_reasons"] == {"analysis_error": 1}
    monkeypatch.setitem(sys.modules, "indicator_engine", types.SimpleNamespace(
        analyze_confluence=_ok, _rate_limit_cooldown_active=lambda: False))
    conn.fresh.clear()
    assert iul.main(["--universe"]) == 0
    assert json.loads((state / "data/runtime/indicator-engine_last.json").read_text())["status"] == "ok"
    assert lo.parse(capsys.readouterr().err)["produced_count"] == 1


def test_universe_config_block_is_read_from_the_strategy_config():
    cfg = iul.load_config()
    assert set(cfg) == set(iul.DEFAULTS) and cfg["profile"] == "swing" and int(cfg["max_symbols"]) > 0


def test_indicator_engine_cli_routes_universe_and_keeps_dry_run_out_of_pipeline_telemetry():
    src = (ROOT / "scripts" / "indicator_engine.py").read_text()
    main = src[src.index("if __name__ == '__main__':"):]
    uni = main.index('"--universe" in _sys.argv[1:]')
    dry = main.index("_sys.exit(_lane.main(_sys.argv[1:]))")
    first_pipeline = main.index('with PipelineRun("indicator_engine")')
    assert uni < dry < first_pipeline  # a --dry-run exits before any PipelineRun write


# ── n8n shadow wiring ───────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lane", sorted(SHADOW))
def test_shadow_rows_are_deferred_until_the_capability_review(lane):
    klass, cron, argv, receipt, wave = SHADOW[lane]
    row = ROWS[lane]
    s = row["scheduler"]
    assert s["kind"] == "cron" and s["stage"] == "shadow" and s["wave"] == wave and s["expression"] == cron
    assert row["state"] == "ACTIVE" and "generated_by" not in row
    # dispatch OFF: no dispatch block (a shadow cron row with dispatch.mode off is refused by R1 shape admission);
    # the reviewed block is parked as deferred_dispatch, so re-enabling = rename it back + restore the allowlist entry
    assert "dispatch" not in row and LD.dispatch_mode(row) == "off" and LD.validate_dispatch_block(row) == []
    assert row["deferred_dispatch"] == {"mode": "dry_run", "cron": [cron], "tz": "America/New_York", "wave": "W4",
                                        "class": klass, "priority": 5, "retry_policy": "none"}
    assert "DD01 capability audit" in row["dispatch_blocked_reason"]
    parked = dict(row, dispatch=row["deferred_dispatch"])
    # the ONLY thing between the parked block and admission is the missing (deferred) allowlist entry
    assert [i.detail for i in LD.validate_dispatch_block(parked)] == [f"class {klass!r} (R1): not_allowlisted"]
    assert lane not in ALLOW  # the n8n run route cannot start it
    sig = f"data/runtime/{receipt}_last.json"
    assert row["output_signal"] == {"kind": "json_key", "path": sig, "key": "ok_at"}
    entry = _deferred_entry(lane)
    assert entry["command"] == ["$PY", *argv] and entry["dry_run_arg"] == ["--dry-run"]
    assert entry["output_signal"] == sig and entry["lock_kind"] == "flock"
    rep = G.scan_entry(argv[0])
    assert not rep.is_sender and not rep.broker_modules and not rep.problems()  # direct reach only (DD01 = transitive)


@pytest.mark.parametrize("lane", sorted(STAGED))
def test_planner_rows_are_staged_until_a_governed_bridge_route_exists(lane):
    cron, argv, receipt, lock = STAGED[lane]
    row, entry = ROWS[lane], _deferred_entry(lane)
    assert lane not in ALLOW and "DD01 capability audit" in row["dispatch_blocked_reason"]
    assert "dispatch" not in row and row["scheduler"].get("stage") is None and LD.dispatch_mode(row) == "off"
    pend = row["r1_pending"]
    assert pend["scheduler"]["stage"] == "shadow" and pend["dispatch"]["class"] == "llm"
    assert pend["dispatch"]["mode"] == "dry_run" and pend["dispatch"]["cron"] == [cron]
    assert pend["output_signal"]["path"] == f"data/runtime/{receipt}_last.json" == entry["output_signal"]
    assert entry["command"] == ["$PY", *argv] and entry["lock"] == lock
    entry = {**entry, "lane_id": lane, "live_arg": None, "market_gate": False}
    assert "llm_route" not in entry and not any("--lane" in t for t in entry["command"])
    activated = dict(row, scheduler={**row["scheduler"], **pend["scheduler"]}, output_signal=pend["output_signal"],
                     dispatch=pend["dispatch"])
    ok, why = LD.r1_class_admission(activated, entry)
    assert not ok and why.startswith("llm_route_not_governed_bridge"), why  # the documented blocker
    fx = EFFECTS[lane]
    assert fx["effects"] == ["append", "llm"] and fx["cron_claim"] is False and fx["n8n_claim"] is False
    assert fx["schedule"] == cron


@pytest.mark.parametrize("lane", sorted(SHADOW) + sorted(STAGED))
def test_contracts_are_reviewed_with_an_expected_output_rule(lane):
    c = CONTRACTS[lane]
    exp = c["expected_output"]
    assert c["status"] == "REVIEWED" and c["review"]["reviewed_on"] == "2026-10-15"
    assert exp["schema"] == "N8nExpectedOutput@v1" and exp["produced_field"] == "produced_count"
    assert exp["rule"] in ("min_produced", "empty_allowed") and isinstance(exp["min_produced"], int)
    assert exp["min_produced"] >= 1 and exp["fatal_skip_reasons"] and exp["empty_allowed_reasons"]
    assert exp["on_violation"]["run_state"] == "RUN_FAILED" and exp["evidence"]
    assert {"empty_output"} <= {f["check"] for f in c["failed"]}
    assert {"output_produced"} <= {h["check"] for h in c["healthy"]}
    assert not set(exp["fatal_skip_reasons"]) & set(exp["empty_allowed_reasons"])
    import check_n8n_workflow_framework as FW  # the §23.24 FW-M6 rule, on main since train 2026-10-15 b

    assert FW._check_expected_output(c)["status"] == FW.PASS


def test_packet_holds_the_exact_candidate_cron_diff_and_rollback():
    pk = ROOT / "docs" / "ops" / "packets" / "lane-repair-indicator-engine-20261015"
    diff = (pk / "crontab.diff").read_text()
    assert "-0 8 * * 1-5 cd $PROJ && $PY scripts/indicator_engine.py >> logs/indicator_engine.log 2>&1" in diff
    assert ("+0 8 * * 1-5 cd $PROJ && flock -n /tmp/indicator_engine.lock $PY scripts/indicator_engine.py --universe "
            ">> logs/indicator_engine.log 2>&1") in diff
    for name in ("dry_run.sh", "apply.sh", "rollback.sh"):
        assert (pk / name).exists(), name
    assert "crontab -" in (pk / "apply.sh").read_text()
