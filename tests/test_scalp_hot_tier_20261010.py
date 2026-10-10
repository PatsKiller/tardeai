"""Scalp hot tier (operator decision (4), 2026-10-10): owner-side code paths, knob OFF by default.

Pins:
- the knob: off unless SCALP_HOT_TIER=1, and a kill file turns it off again; market days 06:00-16:00 ET only;
- budget math against the Finviz throttle ceiling (241,920/week) and the SearXNG daily cap;
- the event trigger (decide is read-only; commit is the single writer; legacy clock when the knob is off);
- the scalp_list projection (never fetches, never writes; fresher of L1050's file and the premarket receipt);
- the enrichment owner's hot path: one custom-column export, ``hot_cached_at`` stamp, ``cached_at`` untouched,
  merge carries the newer hot fields; dry run reaches no request and no save;
- social_ingest --scalp-list, L636 --hot-list-only / proposal-stage gate, L708 routed search, L246 gate order;
- research search goes only through the routing engine (no direct SearXNG/Brave in the hot path).

Hermetic: tmp_path stores, stub engine / fetch / DB rows. No network, no DB, no live state.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import scalp_hot_tier as hot  # noqa: E402
from lib import scalp_list_trigger as trig  # noqa: E402
from lib import scalp_research_route as route  # noqa: E402
from lib.data_broker import catalog  # noqa: E402
from lib.data_broker import scalp_list as sl  # noqa: E402

ET = hot.ET
MON_0700 = datetime(2026, 10, 12, 7, 0, tzinfo=ET)  # Monday, market day
MON_0945 = datetime(2026, 10, 12, 9, 45, tzinfo=ET)
SAT_0700 = datetime(2026, 10, 10, 7, 0, tzinfo=ET)
THANKSGIVING = datetime(2026, 11, 26, 7, 0, tzinfo=ET)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv(hot.ENV_FLAG, raising=False)
    monkeypatch.delenv(sl.RECEIPT_ENV, raising=False)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def hot_on(state, monkeypatch):
    monkeypatch.setenv(hot.ENV_FLAG, "1")
    return state


# ── knob, windows ─────────────────────────────────────────────────────────────


def test_knob_default_off_env_on_kill_file_off(state):
    assert hot.enabled({}, state_root=state) is False
    assert hot.enabled({"SCALP_HOT_TIER": "0"}, state_root=state) is False
    assert hot.enabled({"SCALP_HOT_TIER": "1"}, state_root=state) is True
    hot.kill_file(state).write_text("rollback")
    assert hot.enabled({"SCALP_HOT_TIER": "1"}, state_root=state) is False
    assert hot.flag_state({"SCALP_HOT_TIER": "1"}, state_root=state)["kill_file_present"] is True


def test_windows_market_days_only():
    assert hot.in_window("list_hot", MON_0700)
    assert not hot.in_window("list_hot", MON_0945)  # L1050 owns the list from 09:30
    assert hot.in_window("enrichment", MON_0945)
    assert not hot.in_window("social", datetime(2026, 10, 12, 11, 0, tzinfo=ET))
    assert not hot.in_window("enrichment", datetime(2026, 10, 12, 16, 0, tzinfo=ET))
    assert not hot.in_window("list_hot", datetime(2026, 10, 12, 5, 58, tzinfo=ET))
    assert not hot.in_window("list_hot", SAT_0700)
    assert not hot.in_window("enrichment", THANKSGIVING)


def test_scalp_screener_ids_match_the_scalp_window():
    assert hot.scalp_screener_ids(ROOT) == list(hot.DEFAULT_SCREENER_IDS)


def test_slo_status_thresholds():
    assert hot.slo_status("scalp_list", 4.9) == "healthy"
    assert hot.slo_status("scalp_list", 6) == "late"
    assert hot.slo_status("scalp_list", 9.8) == "degraded"  # today's measured median
    assert hot.slo_status("scalp_list", 16) == "failed"
    assert hot.slo_status("scalp_social", None) == "failed"


# ── budget ────────────────────────────────────────────────────────────────────


def test_budget_against_finviz_ceiling():
    b = hot.budget_projection()
    f = b["finviz"]
    assert f["ceiling_per_week_24x7"] == 241_920
    assert f["hot_list_per_week"] == 4 * 30 * 3.5 * 5  # 2,100
    assert f["hot_enrichment_per_week"] == 4 * 12 * 10 * 5  # 2,400
    assert f["within_ceiling"] and f["after_pct_of_ceiling"] < 10
    assert f["peak_requests_per_min"] < f["throttle_requests_per_min"]
    s = b["searxng"]
    assert s["worst_case_per_day_no_cache"] == 50 * 3 * 10 and s["within_cap"]
    assert b["stocktwits"]["per_hour_in_window"] == 150


# ── trigger ───────────────────────────────────────────────────────────────────


def _env(as_of, syms=("AAA",)):
    return {"as_of": as_of.isoformat() if as_of else None, "symbols": list(syms), "list_source": "test"}


def test_trigger_legacy_clock_when_knob_off(state):
    on_slot = datetime(2026, 10, 12, 7, 0, tzinfo=ET)
    off_slot = datetime(2026, 10, 12, 7, 6, tzinfo=ET)
    d1 = trig.decide("social-scalp-scanner", _env(on_slot), now=on_slot, hot_enabled=False, state_root=state)
    d2 = trig.decide("social-scalp-scanner", _env(off_slot), now=off_slot, hot_enabled=False, state_root=state)
    assert (d1["fire"], d1["decision"]) == (True, "FIRE_LEGACY_CLOCK")
    assert (d2["fire"], d2["decision"]) == (False, "SKIP_NOT_LEGACY_SLOT")
    # L708's legacy slot is :25 — a */2 grid lands on :26
    d3 = trig.decide(
        "hermes-scalp-catalyst", None, now=datetime(2026, 10, 12, 7, 26, tzinfo=ET), hot_enabled=False, state_root=state
    )
    assert d3["fire"]


def test_trigger_advance_new_symbols_min_interval_and_stale(state):
    c = "social-scalp-scanner"
    t0 = MON_0700
    d = trig.decide(c, _env(t0 - timedelta(minutes=1)), now=t0, hot_enabled=True, state_root=state)
    assert d["decision"] == "FIRE_NEW_SYMBOLS"
    trig.commit(c, _env(t0 - timedelta(minutes=1)), decision=d["decision"], now=t0, state_root=state)
    # same as_of -> no advance
    d = trig.decide(
        c, _env(t0 - timedelta(minutes=1)), now=t0 + timedelta(minutes=2), hot_enabled=True, state_root=state
    )
    assert d["decision"] == "SKIP_NO_ADVANCE" and not d["fire"]
    # advanced, same symbols, before min interval (10 min for L246)
    d = trig.decide(
        c, _env(t0 + timedelta(minutes=1)), now=t0 + timedelta(minutes=2), hot_enabled=True, state_root=state
    )
    assert d["decision"] == "SKIP_MIN_INTERVAL"
    # advanced with a new symbol -> immediate
    d = trig.decide(
        c,
        _env(t0 + timedelta(minutes=1), ("AAA", "NEW")),
        now=t0 + timedelta(minutes=2),
        hot_enabled=True,
        state_root=state,
    )
    assert d["decision"] == "FIRE_NEW_SYMBOLS" and d["new_symbols"] == ["NEW"]
    # advanced, past min interval
    d = trig.decide(
        c, _env(t0 + timedelta(minutes=10)), now=t0 + timedelta(minutes=11), hot_enabled=True, state_root=state
    )
    assert d["decision"] == "FIRE_ADVANCE"
    # list stalled (> 15 min) and past the legacy 30 min -> fallback fire, never silence
    d = trig.decide(
        c, _env(t0 - timedelta(minutes=1)), now=t0 + timedelta(minutes=31), hot_enabled=True, state_root=state
    )
    assert d["decision"] == "FIRE_STALE_LIST"


def test_trigger_decide_is_read_only_and_commit_is_atomic(state):
    path = trig.store_path(state)
    trig.decide("l636-proposal-stage", _env(MON_0700), now=MON_0700, hot_enabled=True, state_root=state)
    assert not path.exists()
    trig.commit(
        "l636-proposal-stage", _env(MON_0700, ("X", "Y")), decision="FIRE_NEW_SYMBOLS", now=MON_0700, state_root=state
    )
    doc = json.loads(path.read_text())
    assert doc["schema"] == trig.SCHEMA
    assert doc["consumers"]["l636-proposal-stage"]["symbols_fired"] == ["X", "Y"]
    assert set(trig.first_seen_today(MON_0700, state_root=state)) == {"X", "Y"}
    assert not list(path.parent.glob("*.tmp"))
    src = ast.get_source_segment(Path(trig.__file__).read_text(), _fn(trig.__file__, "decide"))
    assert "open(" not in src and "replace(" not in src and "commit(" not in src


def _fn(path, name):
    tree = ast.parse(Path(path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


# ── scalp_list projection ─────────────────────────────────────────────────────


def _write_universe(state, as_of, syms=("VIVK", "BDAI")):
    p = state / "data" / "trade_ai" / "scalp_universe_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"schema": "TradeAIScalpUniverse@v1", "as_of": as_of.isoformat(), "rows": [{"symbol": s} for s in syms]}
        )
    )


def test_scalp_list_premarket_receipt_wins_when_fresher(state):
    _write_universe(state, MON_0700 - timedelta(hours=15))
    receipt = {
        "state": "DONE",
        "at": (MON_0700 - timedelta(minutes=1)).isoformat(),
        "screener_ids": list(hot.DEFAULT_SCREENER_IDS),
    }
    seen = {}

    def rows(ids, since):
        seen.update(ids=ids, since=since)
        return [("abc", "prime_setups", MON_0700), ("XYZ", "watchlist_setups", MON_0700)]

    env = sl.get_scalp_list(now=MON_0700, state_root=state, rows_fn=rows, receipt=receipt)
    assert env["list_source"] == "hot_tier_premarket_screeners"
    assert env["symbols"] == ["ABC", "XYZ"] and env["provider_calls"] == 0
    assert env["schema"] == "BrokerReadEnvelope@v1" and env["stale"] is False
    assert seen["ids"] == list(hot.DEFAULT_SCREENER_IDS)
    assert seen["since"] == datetime.fromisoformat(receipt["at"]).astimezone(timezone.utc) - timedelta(minutes=5)


def test_scalp_list_l1050_wins_in_rth_and_stale_flags(state):
    _write_universe(state, MON_0945 - timedelta(minutes=2))
    receipt = {"state": "DONE", "at": (MON_0945 - timedelta(minutes=20)).isoformat(), "screener_ids": ["prime_setups"]}
    env = sl.get_scalp_list(now=MON_0945, state_root=state, rows_fn=lambda i, s: [], receipt=receipt)
    assert env["list_source"] == "l1050_scalp_universe" and env["symbols"] == ["VIVK", "BDAI"]
    env = sl.get_scalp_list(
        now=MON_0945 + timedelta(minutes=10), state_root=state, rows_fn=lambda i, s: [], receipt=receipt
    )
    assert env["stale"] is True  # 12 min > 5 min SLO in window


def test_scalp_list_never_reads_db_without_a_covering_done_receipt(state):
    def boom(*a):
        raise AssertionError("DB reached")

    pre = sl.read_premarket(state_root=state, rows_fn=boom, receipt={"state": "STARTED"})
    assert pre["error"] == "no_done_receipt"
    pre = sl.read_premarket(
        state_root=state, rows_fn=boom, receipt={"state": "DONE", "at": MON_0700.isoformat(), "screener_ids": ["other"]}
    )
    assert pre["error"] == "receipt_not_covering_scalp_screeners"
    _write_universe(state, MON_0700)
    (state / "data" / "trade_ai" / "scalp_universe_latest.json").write_text('{"schema": "Other@v1"}')
    assert sl.read_universe(state)["error"] == "schema_mismatch"


def test_scalp_enrichment_reads_hot_stamp(state):
    now = MON_0700.astimezone(timezone.utc)
    local = lambda dt: dt.astimezone().replace(tzinfo=None).isoformat()  # noqa: E731
    cache = {
        "AAA": {
            "cached_at": local(now - timedelta(hours=3)),
            "hot_cached_at": local(now - timedelta(minutes=3)),
            "rvol": 7.0,
        },
        "BBB": {"cached_at": local(now - timedelta(hours=3))},
    }
    out = sl.get_scalp_enrichment(["AAA", "BBB", "CCC"], now=now, cache=cache)
    assert out["fresh"] == ["AAA"] and out["stale_or_missing"] == ["BBB", "CCC"]
    assert out["symbols"]["AAA"]["fields"]["rvol"] == 7.0 and out["missing_any"] is True
    assert out["provider_calls"] == 0


def test_freshness_report_no_slo_off_window_and_statuses_in_window(state):
    rep = sl.freshness_report(
        now=SAT_0700, state_root=state, project_root=state, list_env=_env(SAT_0700), cache={}, first_seen={}
    )
    assert rep["overall"] == "NO_SLO"
    now = MON_0700
    rep = sl.freshness_report(
        now=now,
        state_root=state,
        project_root=state,
        list_env=_env(now - timedelta(minutes=3), ()),
        cache={},
        first_seen={},
    )
    assert rep["domains"]["scalp_list"]["status"] == "healthy"
    assert rep["domains"]["scalp_social"]["status"] == "failed"  # no social hot receipt yet
    assert rep["overall"] == "failed"
    noon = datetime(2026, 10, 12, 12, 0, tzinfo=ET)
    rep = sl.freshness_report(
        now=noon,
        state_root=state,
        project_root=state,
        list_env=_env(noon - timedelta(minutes=3), ()),
        cache={},
        first_seen={},
    )
    assert rep["domains"]["scalp_social"]["status"] == "NO_SLO"  # social is polled 06:00-11:00 only
    assert rep["domains"]["scalp_list"]["status"] == "healthy"


def test_catalog_lists_the_projection():
    row = next(p for p in catalog.PROJECTIONS if p["id"] == "scalp_list")
    assert row["read_only"] and row["provider_calls"] == 0 and row["authority_domain"] is None


# ── enrichment owner hot path ─────────────────────────────────────────────────


import finviz_enrichment as fe  # noqa: E402


def test_merge_keeps_full_refresh_and_carries_newer_hot_fields():
    disk = {"AAA": {"cached_at": "2026-10-12T05:00:00", "rvol": 1.0, "sector": "Tech"}}
    mine = {
        "AAA": {
            "cached_at": "2026-10-12T04:00:00",
            "rvol": 9.0,
            "hot_price": 3.2,
            "hot_cached_at": "2026-10-12T07:00:00",
            "sector": "Old",
        }
    }
    out = fe.merge_cache_records(disk, mine)["AAA"]
    assert out["sector"] == "Tech"  # six-view record from the newer full refresh
    assert out["rvol"] == 9.0 and out["hot_price"] == 3.2 and out["hot_cached_at"] == "2026-10-12T07:00:00"
    # reversed: a full refresh newer than the hot stamp keeps its own fields
    disk2 = {"AAA": {"cached_at": "2026-10-12T08:00:00", "rvol": 2.0}}
    out2 = fe.merge_cache_records(disk2, mine)["AAA"]
    assert out2["rvol"] == 2.0 and "hot_cached_at" not in out2
    # legacy records (no hot stamp): newer cached_at wins unchanged
    a = {"X": {"cached_at": "2026-10-10T10:00:00", "rsi": 1}}
    b = {"X": {"cached_at": "2026-10-10T11:00:00", "rsi": 2}}
    assert fe.merge_cache_records(a, b)["X"]["rsi"] == 2 and fe.merge_cache_records(b, a)["X"]["rsi"] == 2


def test_enrich_scalp_hot_one_custom_export_cached_at_untouched(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(tickers, view, root, *, col_map=None, extra_query=""):
        calls.append((list(tickers), view, extra_query, col_map is fe.HOT_COLUMN_MAP))
        return {t: {"rvol": 8.0, "gap_pct": 12.0, "float_m": 5.0, "hot_price": 3.1} for t in tickers}

    monkeypatch.setattr(fe, "_fetch_view", fake_fetch)
    (tmp_path / "data" / "state").mkdir(parents=True)
    fresh_hot = datetime.now().isoformat()
    (tmp_path / fe.CACHE_FILE).write_text(
        json.dumps(
            {
                "OLD": {"cached_at": "2026-10-01T09:00:00", "sector": "Health", "rvol": 0.0},
                "FRESH": {"hot_cached_at": fresh_hot, "rvol": 5.0},
            }
        )
    )
    stats = fe.enrich_scalp_hot(["OLD", "NEW", "FRESH"], str(tmp_path))
    assert calls == [(["OLD", "NEW"], 152, f"&c={fe.HOT_COLUMNS}", True)]
    assert stats["requests"] == 1 and stats["returned"] == 2
    cache = json.loads((tmp_path / fe.CACHE_FILE).read_text())
    assert cache["OLD"]["cached_at"] == "2026-10-01T09:00:00" and cache["OLD"]["sector"] == "Health"
    assert cache["OLD"]["rvol"] == 8.0 and cache["OLD"]["hot_price"] == 3.1 and "price" not in cache["OLD"]
    assert "cached_at" not in cache["NEW"] and cache["NEW"]["hot_cached_at"]
    assert fe._is_stale(cache["NEW"])  # the six-view TTL still sees a hot-only record as stale
    assert cache["FRESH"]["hot_cached_at"] == fresh_hot


def test_hot_column_map_parses_by_name_with_aliases(monkeypatch, tmp_path):
    class R:
        status_code = 200
        ok = True
        headers = {}
        text = 'Ticker,Float,Relative Volume,Gap,Price,Change,Volume\n"AAA","4.5","9.10","12.00%","3.20","15.00%","1200000"\n'

    monkeypatch.setattr(fe, "_env", lambda k, d="": "tok" if k == "FINVIZ_API_TOKEN" else d)
    monkeypatch.setattr(fe, "_load_env", lambda root: None)
    monkeypatch.setattr(fe.requests, "get", lambda url, headers=None, timeout=None: R())
    monkeypatch.setattr(fe, "REQUEST_DELAY", 0)
    sys.modules.setdefault("finviz_throttle", type(sys)("finviz_throttle"))
    sys.modules["finviz_throttle"].acquire = lambda: None
    sys.modules["finviz_throttle"].cooldown = lambda *a: None
    got = fe._fetch_view(["AAA"], 152, tmp_path, col_map=fe.HOT_COLUMN_MAP, extra_query="&c=1")
    assert got["AAA"]["float_m"] == 4.5 and got["AAA"]["rvol"] == 9.1 and got["AAA"]["gap_pct"] == 12.0
    assert got["AAA"]["hot_price"] == 3.2 and got["AAA"]["hot_change_pct"] == 15.0


def test_enrichment_scalp_hot_main_off_and_dry_run_reach_no_request(state, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("must not fetch/save")

    monkeypatch.setattr(fe, "_fetch_view", boom)
    monkeypatch.setattr(fe, "save_cache", boom)
    assert fe.main_scalp_hot(dry_run=False, now=MON_0700) == 0
    assert "SKIPPED_FLAG_OFF" in capsys.readouterr().out
    monkeypatch.setenv(hot.ENV_FLAG, "1")
    monkeypatch.setattr(
        sl, "get_scalp_list", lambda **k: {"symbols": ["AAA", "BBB"], "list_source": "t", "as_of": "x", "stale": False}
    )
    monkeypatch.chdir(state)
    assert fe.main_scalp_hot(dry_run=True, now=MON_0700) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"finviz_export_requests": 1' in out
    assert not (state / "data" / "runtime" / f"{fe.HOT_LANE_ID}_last.json").exists()
    assert fe.main_scalp_hot(dry_run=True, now=SAT_0700) == 0
    assert "SKIPPED_OFF_WINDOW" in capsys.readouterr().out


# ── social owner hot path ─────────────────────────────────────────────────────


import social_ingest as si  # noqa: E402


def test_social_scalp_list_off_dry_and_real(state, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(si, "ingest_stocktwits", boom)
    assert si.main(["--source", "stocktwits", "--scalp-list"]) == 0
    assert "SKIPPED_FLAG_OFF" in capsys.readouterr().out
    assert si.main(["--source", "stocktwits", "--scalp-list", "--discover"]) == 2
    monkeypatch.setenv(hot.ENV_FLAG, "1")
    monkeypatch.setattr(hot, "in_window", lambda name, now=None: True)
    monkeypatch.setattr(
        sl,
        "get_scalp_list",
        lambda **k: {"symbols": [f"S{i}" for i in range(30)], "list_source": "t", "as_of": "x", "stale": False},
    )
    assert si.main(["--source", "stocktwits", "--scalp-list", "--dry-run"]) == 0
    assert '"stocktwits_symbol_requests": 25' in capsys.readouterr().out
    receipt = state / "data" / "runtime" / f"{si.SCALP_HOT_LANE_ID}_last.json"
    assert not receipt.exists()
    seen = []
    monkeypatch.setattr(
        si, "ingest_stocktwits", lambda syms: seen.append(syms) or {"inserted": 3, "skipped": 1, "errors": []}
    )
    assert si.main(["--source", "stocktwits", "--scalp-list"]) == 0
    assert len(seen[0]) == 25
    doc = json.loads(receipt.read_text())
    assert doc["ok_at"] and doc["summary"]["inserted"] == 3


# ── L636 wrapper ──────────────────────────────────────────────────────────────


import run_finviz_momentum_scalp_scan as scan  # noqa: E402


def _run_scan(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["run_finviz_momentum_scalp_scan.py", *argv])
    return scan.main()


@pytest.fixture
def lane_stubs(monkeypatch):
    calls = []
    lane = scan.lane
    monkeypatch.setattr(
        lane, "stage_finviz_scan", lambda **k: calls.append(("scan", k)) or {"stage": "finviz_scan", "ok": True}
    )
    monkeypatch.setattr(
        lane,
        "stage_signal_sync",
        lambda dry_run: calls.append(("sync", dry_run)) or {"stage": "signal_sync", "ok": True},
    )
    monkeypatch.setattr(
        lane,
        "stage_proposal_gen",
        lambda dry_run: calls.append(("gen", dry_run)) or {"stage": "proposal_gen", "ok": True},
    )
    monkeypatch.setattr(
        lane,
        "stage_validation",
        lambda submit: calls.append(("val", submit)) or {"stage": "validation_fast_path", "ok": True},
    )
    monkeypatch.setattr(lane, "scan_counts", lambda: {"ok": False})
    monkeypatch.setattr(lane, "refresh_age_min", lambda *a, **k: 5.0)
    return calls


def test_hot_list_only_off_by_default(state, lane_stubs, monkeypatch, capsys):
    assert _run_scan(monkeypatch, ["--hot-list-only", "--apply", "--now", "2026-10-12T07:00:00"]) == 0
    assert "SKIPPED_FLAG_OFF" in capsys.readouterr().out and lane_stubs == []


def test_hot_list_only_dry_run_and_apply(hot_on, lane_stubs, monkeypatch, capsys):
    assert _run_scan(monkeypatch, ["--hot-list-only", "--now", "2026-10-12T07:00:00"]) == 0
    out = capsys.readouterr().out
    assert "dry_run_no_refresh" in out and '"finviz_export_requests": 4' in out and lane_stubs == []
    assert _run_scan(monkeypatch, ["--hot-list-only", "--apply", "--now", "2026-10-12T07:00:00"]) == 0
    assert lane_stubs[0][0] == "scan" and lane_stubs[0][1]["screener_ids"] == list(hot.DEFAULT_SCREENER_IDS)
    assert [c[0] for c in lane_stubs] == ["scan"]  # no handoff stage on the hot line
    lane_stubs.clear()
    assert _run_scan(monkeypatch, ["--hot-list-only", "--apply", "--now", "2026-10-12T09:40:00"]) == 0
    assert "SKIPPED_OFF_HOT_WINDOW" in capsys.readouterr().out and lane_stubs == []


def test_lane_unchanged_when_knob_off(state, lane_stubs, monkeypatch):
    monkeypatch.setattr(scan.trig, "decide", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gated")))
    argv = [
        "--window",
        "early",
        "--apply",
        "--refresh-if-older-min",
        "15",
        "--sync-signals",
        "--generate-proposals",
        "--run-validation-fast-path",
        "--now",
        "2026-10-12T07:00:00",
    ]
    assert _run_scan(monkeypatch, argv) == 0
    assert [c[0] for c in lane_stubs] == ["sync", "gen", "val"]  # age 5 < 15: no refresh, as before


def test_lane_hot_phase_skips_own_refresh_and_gates_proposals(hot_on, lane_stubs, monkeypatch, capsys):
    monkeypatch.setattr(sl, "get_scalp_list", lambda **k: _env(MON_0700))
    commits = []
    monkeypatch.setattr(scan.trig, "commit", lambda *a, **k: commits.append(a))
    monkeypatch.setattr(scan.trig, "decide", lambda c, env, **k: {"fire": False, "decision": "SKIP_NO_ADVANCE"})
    argv = [
        "--window",
        "early",
        "--apply",
        "--refresh-if-older-min",
        "0",
        "--sync-signals",
        "--generate-proposals",
        "--run-validation-fast-path",
        "--now",
        "2026-10-12T07:00:00",
    ]
    assert _run_scan(monkeypatch, argv) == 0
    out = capsys.readouterr().out
    assert "skipped_hot_tier_owns_refresh" in out and "skipped_no_list_advance" in out
    assert [c[0] for c in lane_stubs] == ["val"] and commits == []  # validation untouched
    lane_stubs.clear()
    monkeypatch.setattr(scan.trig, "decide", lambda c, env, **k: {"fire": True, "decision": "FIRE_ADVANCE"})
    assert _run_scan(monkeypatch, argv) == 0
    assert [c[0] for c in lane_stubs] == ["sync", "gen", "val"] and len(commits) == 1


# ── research routing ──────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    calls = []

    def fake(query, **kw):
        calls.append((query, kw))
        if kw["time_range"] == "day":
            return {"ok": True, "results": [], "decision": "FREE_LANE_EMPTY"}
        return {
            "ok": True,
            "results": [{"title": "FDA nod", "url": "https://x/1", "content": "c"}],
            "provider": "searxng",
            "cache_hit": False,
            "decision": "FREE_LANE",
        }

    route.set_engine_for_tests(fake)
    yield calls
    route.set_engine_for_tests(None)


def test_route_unavailable_is_typed():
    route.set_engine_for_tests(None)
    if not route.engine_available():
        r = route.route("abc", "premarket catalyst", caller="t")
        assert r["decision"] == "ROUTING_ENGINE_UNAVAILABLE" and r["results"] == []


def test_route_priority_class_week_fallback_and_cache_ttl(engine):
    r = route.route("abc", "premarket catalyst", caller="hermes_scalp_catalyst", priority=True)
    assert r["ok"] and r["request_class"] == "scalp_priority" and len(r["results"]) == 1
    assert [c[1]["time_range"] for c in engine] == ["day", "week"]
    assert engine[0][0] == "ABC stock premarket catalyst" and engine[0][1]["cache_ttl_s"] == 1200
    assert engine[0][1]["subject"] == "ABC" and engine[0][1]["intent"] == "premarket catalyst"


def test_route_engine_error_is_typed():
    route.set_engine_for_tests(lambda q, **k: (_ for _ in ()).throw(RuntimeError("down")))
    try:
        r = route.route("abc", "x", caller="t")
    finally:
        route.set_engine_for_tests(None)
    assert r["decision"] == "ROUTING_ENGINE_ERROR" and not r["ok"]


import hermes_momentum_catalyst_researcher as hr  # noqa: E402


def test_hermes_search_goes_through_engine_when_hot(hot_on, engine, monkeypatch):
    monkeypatch.setattr(
        hr.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("direct SearXNG call in the hot path")),
    )
    out = hr.search_catalyst("abc", "premarket catalyst", caller="catalyst_momentum_engine")
    assert out[0]["title"] == "FDA nod" and out[0]["routed"]["provider"] == "searxng"
    assert engine[0][1]["dry_run"] is False and engine[0][1]["caller"] == "catalyst_momentum_engine"
    engine.clear()
    hr.search_catalyst("abc", "premarket catalyst", caller="catalyst_momentum_engine", dry_run=True)
    assert [c[1]["dry_run"] for c in engine] == [True]  # a dry run asks once and passes dry_run through


def test_hermes_legacy_path_when_knob_off(state, engine, monkeypatch):
    hit = []

    class Resp:
        def read(self):
            return b'{"results": []}'

    monkeypatch.setattr(hr.urllib.request, "urlopen", lambda *a, **k: hit.append(1) or Resp())
    assert hr.search_catalyst("abc", "latest news") == []
    assert hit == [1] and engine == []


def test_select_hot_candidates_new_or_stale_priority_first():
    now = datetime(2026, 10, 12, 8, 0)
    researched = {
        "OLD": now - timedelta(minutes=45),
        "RECENT": now - timedelta(minutes=10),
        "PRIO": now - timedelta(minutes=5),
    }
    got = hr.select_hot_candidates(["PRIO", "AWAIT"], ["CAND"], ["RECENT", "NEW", "OLD"], researched, now=now)
    assert got == ["AWAIT", "NEW", "CAND", "OLD"]  # RECENT and PRIO researched < 30 min ago
    assert len(hr.select_hot_candidates([], [], [f"S{i}" for i in range(40)], {}, now=now)) == 15


def test_researched_today_reads_latest_timestamp(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text(
        '{"symbol": "abc", "research_timestamp": "2026-10-12T07:00:00"}\n'
        '{"symbol": "ABC", "research_timestamp": "2026-10-12T07:40:00"}\nnot json\n'
    )
    assert hr.researched_today(p) == {"ABC": datetime(2026, 10, 12, 7, 40)}


def test_research_path_never_names_a_provider_directly():
    for path in (
        SCRIPTS / "lib" / "scalp_research_route.py",
        SCRIPTS / "lib" / "scalp_list_trigger.py",
        SCRIPTS / "lib" / "scalp_hot_tier.py",
        SCRIPTS / "lib" / "data_broker" / "scalp_list.py",
    ):
        tree = ast.parse(path.read_text())
        imported = (
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            | {(n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            | {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        )
        for mod in ("brave_router", "searxng_client", "urllib.request", "requests", "free_search"):
            assert not any(mod == m or m.endswith("." + mod) for m in imported), (path.name, mod)
        code = ast.unparse(
            [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        )
        for token in ("18888", "urlopen", "requests.get"):
            assert token not in code, (path.name, token)
    tree = ast.parse((SCRIPTS / "hermes_momentum_catalyst_researcher.py").read_text())
    routed = _fn(SCRIPTS / "hermes_momentum_catalyst_researcher.py", "_routed")
    assert "urlopen" not in ast.unparse(routed)
    sc = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "search_catalyst")
    first = sc.body[1] if isinstance(sc.body[0], ast.Expr) else sc.body[0]
    assert isinstance(first, ast.If) and "_hot_research_on" in ast.unparse(first.test)


# ── L246 gate order; rails ────────────────────────────────────────────────────


def test_social_scalp_scanner_gate_runs_before_scan_and_commit_after():
    fn = _fn(SCRIPTS / "social_scalp_scanner.py", "main")
    src = ast.unparse(fn)
    assert src.index("gate_main") < src.index("if not gate['decision']['fire']") < src.rindex("run_scan()")
    assert src.rindex("run_scan()") < src.index("_trig.commit")
    tail = (SCRIPTS / "social_scalp_scanner.py").read_text().rstrip().splitlines()[-2:]
    assert tail == ['if __name__ == "__main__":', "    sys.exit(main())"]


def test_hot_tier_touches_no_order_or_send_path():
    files = [
        SCRIPTS / "lib" / "scalp_hot_tier.py",
        SCRIPTS / "lib" / "scalp_list_trigger.py",
        SCRIPTS / "lib" / "scalp_research_route.py",
        SCRIPTS / "lib" / "data_broker" / "scalp_list.py",
        SCRIPTS / "scalp_hot_tier_report.py",
    ]
    for p in files:
        src = p.read_text()
        for token in (
            "place_order",
            "submit_paper",
            "send_telegram",
            "MOMENTUM_SCALP_VALIDATION_SUBMIT",
            "run_trade_ai_scalp_live import",
            "INSERT ",
            "UPDATE ",
        ):
            assert token not in src, (p.name, token)


def test_report_cli_budget_is_read_only(state, capsys):
    import scalp_hot_tier_report as rpt

    assert rpt.main(["--budget"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["budget"]["finviz"]["ceiling_per_week_24x7"] == 241_920 and doc["writes"] == "none"
    assert list((state / "data" / "runtime").iterdir()) == []


def test_catalyst_engine_passes_routing_kwargs_only_when_hot(state, monkeypatch):
    import catalyst_momentum_engine as cme

    route.set_engine_for_tests(None)
    if not route.engine_available():
        monkeypatch.setenv(hot.ENV_FLAG, "1")
        assert cme._search_kwargs(dry_run=True) == {}  # knob on but no engine: legacy two-argument call
    route.set_engine_for_tests(lambda q, **k: {"ok": True, "results": []})
    try:
        monkeypatch.setenv(hot.ENV_FLAG, "1")
        assert cme._search_kwargs(dry_run=True) == {"caller": "catalyst_momentum_engine", "dry_run": True}
        monkeypatch.delenv(hot.ENV_FLAG)
        assert cme._search_kwargs(dry_run=False) == {}
    finally:
        route.set_engine_for_tests(None)


def test_report_triggers_shadow_never_commits(state, monkeypatch, capsys):
    import scalp_hot_tier_report as rpt

    monkeypatch.setattr(sl, "get_scalp_list", lambda **k: _env(MON_0700))
    assert rpt.main(["--triggers"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc["triggers"]) == set(trig.CONSUMERS)
    assert not trig.store_path(state).exists()
