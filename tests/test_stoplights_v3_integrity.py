"""Stoplights v3 integrity patch — timing model, position cycles, config
authority, holdings→card end-to-end. Pure + real PostgreSQL."""
import json
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import defense_inverse_stoplights as sl
from research.inverse_hedge_backtest import overlay_metrics  # noqa: E402  (scripts/research)

psycopg2 = pytest.importorskip("psycopg2")


# ── P0-1: overlay timing model (pure) ────────────────────────────────────────

def _bars_seq(closes, start="2026-03-02"):
    d = date.fromisoformat(start)
    out = []
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"d": str(d), "o": c, "h": c, "l": c, "c": c})
        d += timedelta(days=1)
    return out


def test_signal_session_inverse_return_excluded():
    """Extreme inverse move ON the signal/entry session must NOT be credited."""
    bench = _bars_seq([100, 100, 100, 100])
    inv = _bars_seq([10, 20, 20, 20])           # +100% happens ON the entry day (idx1)
    trades = [{"entry": bench[1]["d"], "exit": bench[3]["d"]}]
    m = overlay_metrics(bench, inv, trades)
    # benchmark flat; hedge attribution starts idx2 (inv 20→20 = 0) → hedged == base
    assert m["mdd_hedged_pct"] == m["mdd_base_pct"]
    assert m["hedged_session_count"] == 2       # t+1 and u, not the entry day


def test_first_attributed_return_is_next_session_and_exit_included():
    bench = _bars_seq([100, 100, 100, 100, 100])
    inv = _bars_seq([10, 10, 11, 12.1, 99])     # +10% at t+1, +10% at u, +huge AFTER exit
    trades = [{"entry": bench[1]["d"], "exit": bench[3]["d"]}]
    m = overlay_metrics(bench, inv, trades)
    # hedged: gains at t+1 and u only; the post-exit +huge inverse day contributes NOTHING
    assert m["hedged_session_count"] == 2
    assert m["missing_inverse_observations"]["count"] == 0
    # session after exit unhedged: rerun with the huge day inside the window to contrast
    trades2 = [{"entry": bench[1]["d"], "exit": bench[4]["d"]}]
    m2 = overlay_metrics(bench, inv, trades2)
    assert m2["hedged_session_count"] == 3


def test_missing_inverse_observation_never_fabricated():
    bench = _bars_seq([100, 100, 90, 100])      # −10% benchmark crash on idx2
    inv = [b for b in _bars_seq([10, 10, 10, 10])]
    del inv[2]                                   # inverse observation MISSING on crash day
    trades = [{"entry": bench[0]["d"], "exit": bench[3]["d"]}]
    m = overlay_metrics(bench, inv, trades)
    # old code would credit +10% synthetic inverse; now: excluded + counted
    assert m["missing_inverse_observations"]["count"] == 1
    assert m["missing_inverse_observations"]["dates"] == [bench[2]["d"]]
    assert m["mdd_hedged_pct"] == m["mdd_base_pct"]   # crash day got NO hedge credit


def test_weekend_gap_does_not_alter_session_timing():
    bench = _bars_seq([100, 100, 100], start="2026-03-06")   # Fri, Mon, Tue
    inv = _bars_seq([10, 11, 12], start="2026-03-06")
    trades = [{"entry": bench[0]["d"], "exit": bench[2]["d"]}]
    m = overlay_metrics(bench, inv, trades)
    assert m["hedged_session_count"] == 2        # Mon + Tue; weekend irrelevant


# ── P1-1: config authority (pure) ────────────────────────────────────────────

VALID = {"bounce_day_pct": 0.75, "materiality_exposure_pct": 8.0, "band_pct": [2.0, 5.0],
         "max_hold_sessions": 20, "anti_chase_atr": 1.5, "tp1_inverse_pct": 8,
         "tp2_inverse_pct": 15, "hedge_ratio_tolerance_pct": 25, "staging": [25, 25, 50],
         "stale_calendar_days": 4, "beta_book_source": "ASSUMED_1.0",
         "shadow_twoday": {"min_daily_pct": 0.0, "min_cum_pct": 0.75}}


def test_valid_config_passes_and_is_deterministic():
    assert sl.validate_stoplight_config(dict(VALID)) == VALID


@pytest.mark.parametrize("mutate,frag", [
    (lambda c: c.pop("bounce_day_pct"), "missing required field"),
    (lambda c: c.update(bounce_day_pct="0.75"), "must be numeric"),
    (lambda c: c.update(max_hold_sessions=-5), "below sensible floor"),
    (lambda c: c.update(staging=[50, 50, 50]), "must total 100"),
    (lambda c: c.update(tp1_inverse_pct=20, tp2_inverse_pct=8), "must exceed"),
    (lambda c: c.update(band_pct=[5.0, 2.0]), "ordered"),
    (lambda c: c.update(zzz_typo=1), "unknown config keys"),
])
def test_invalid_config_fails_closed(mutate, frag):
    c = json.loads(json.dumps(VALID))
    mutate(c)
    with pytest.raises(sl.StoplightConfigError, match=frag.replace("(", "\\(")):
        sl.validate_stoplight_config(c)


def test_configured_staleness_controls_behavior():
    bars = [{"d": str(date.today() - timedelta(days=6)), "o": 1, "h": 1, "l": 1, "c": 1}]
    assert sl._bars_fresh(bars, stale_days=10) is True
    assert sl._bars_fresh(bars, stale_days=4) is False       # config value decides


# ── P0-2 + P1-2: cycles + holdings→card end-to-end (real PG) ─────────────────

@pytest.fixture()
def pg_env(tmp_path, monkeypatch):
    try:
        conn = psycopg2.connect(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
                                user=os.environ.get("DB_USER", "postgres"),
                                password=os.environ.get("DB_PASSWORD", ""),
                                host=os.environ.get("DB_HOST", "localhost"),
                                port=os.environ.get("DB_PORT", "5432"))
    except Exception as e:
        pytest.skip(f"no postgres: {e}")
    schema = f"cyc_{uuid.uuid4().hex[:8]}"
    cur = conn.cursor()
    cur.execute(f'CREATE SCHEMA "{schema}"')
    cur.execute(f'SET search_path TO "{schema}"')
    conn.commit()
    hpath = tmp_path / "holdings.json"
    monkeypatch.setattr(sl, "HOLDINGS_PATH", hpath)
    yield conn, cur, hpath
    conn.rollback()
    conn.cursor().execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def _write_holdings(hpath, rows, as_of=None):
    hpath.write_text(json.dumps({"as_of": as_of or str(date.today()),
                                 "holdings": rows}))


def _fresh_bench(n=70, rets=None):
    bars, px = [], 100.0
    d = date.today() - timedelta(days=140)
    seq = ([-0.3] * (n - len(rets or [])) + (rets or []))
    for r in seq:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        px *= (1 + r / 100)
        bars.append({"d": str(d), "o": px, "h": px * 1.005, "l": px * 0.995, "c": px})
        d += timedelta(days=1)
    # re-date the tail so the last close is today-ish (fresh)
    shift = (date.today() - date.fromisoformat(bars[-1]["d"])).days
    for b in bars:
        nd = date.fromisoformat(b["d"]) + timedelta(days=shift)
        b["d"] = str(nd)
    return bars


SH_ROW = {"symbol": "SH", "account": "schwab_taxable", "shares": 300,
          "cost_basis": 9000.0, "price": 33.0}


def test_cycle_lifecycle_full(pg_env):
    conn, cur, hpath = pg_env
    bars = _fresh_bench()
    # 1. first sighting → cycle A
    _write_holdings(hpath, [SH_ROW])
    p1 = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p1 and p1["qty"] == 300 and p1["inv_gain_pct"] == 10.0
    a = p1["cycle_id"]
    # 2. unchanged holdings → same cycle
    p2 = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p2["cycle_id"] == a
    cur.execute("SELECT count(*) FROM inverse_position_cycles")
    assert cur.fetchone()[0] == 1
    # 3. partial reduction stays cycle A
    _write_holdings(hpath, [{**SH_ROW, "shares": 100, "cost_basis": 3000.0}])
    p3 = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p3["cycle_id"] == a and p3["qty"] == 100
    # 6. STALE snapshot does NOT close cycle A
    _write_holdings(hpath, [], as_of=str(date.today() - timedelta(days=30)))
    p_st = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p_st and p_st.get("data_gap") and p_st["cycle_id"] == a
    cur.execute("SELECT status FROM inverse_position_cycles WHERE position_cycle_id=%s", (a,))
    assert cur.fetchone()[0] == "OPEN"
    # unreadable snapshot also never closes
    hpath.write_text("{corrupt")
    p_bad = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p_bad and p_bad.get("data_gap")
    # 4. CONFIRMED fresh absence closes cycle A
    _write_holdings(hpath, [])
    assert sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY") is None
    cur.execute("SELECT status, closed_session FROM inverse_position_cycles WHERE position_cycle_id=%s", (a,))
    st, cs = cur.fetchone()
    assert st == "CLOSED" and cs is not None
    # 5. reopen → cycle B, held sessions RESET
    _write_holdings(hpath, [SH_ROW])
    p5 = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p5["cycle_id"] != a
    assert p5["held_sessions"] == 1              # first-seen session only
    cur.execute("SELECT status FROM inverse_position_cycles WHERE position_cycle_id=%s", (a,))
    assert cur.fetchone()[0] == "CLOSED"          # prior cycle immutable


def test_held_sessions_use_market_sessions_not_weekdays(pg_env):
    conn, cur, hpath = pg_env
    bars = _fresh_bench()
    # simulate a holiday: drop the second-to-last session from the bench series
    holiday_bars = bars[:-2] + bars[-1:]
    _write_holdings(hpath, [SH_ROW])
    p = sl.resolve_position_cycle(cur, conn, "SH", holiday_bars, "SPY")
    a = p["cycle_id"]
    # backdate first_seen_session by 5 SESSIONS
    first = holiday_bars[-5]["d"]
    cur.execute("UPDATE inverse_position_cycles SET first_seen_session=%s WHERE position_cycle_id=%s",
                (first, a))
    conn.commit()
    p2 = sl.resolve_position_cycle(cur, conn, "SH", holiday_bars, "SPY")
    held, dates = sl._held_sessions(holiday_bars, first)
    assert p2["held_sessions"] == held == 5      # completed sessions in the SERIES
    assert all(d in [b["d"] for b in holiday_bars] for d in dates)  # holiday absent = uncounted


def test_multi_account_aggregation_and_missing_basis(pg_env):
    conn, cur, hpath = pg_env
    bars = _fresh_bench()
    _write_holdings(hpath, [
        {"symbol": "SH", "account": "schwab_taxable", "shares": 100, "cost_basis": 3000.0, "price": 33.0},
        {"symbol": "SH", "account": "schwab_rollover_ira", "shares": 200, "cost_basis": 6000.0, "price": 33.0},
        {"symbol": "SH", "account": "schwab_taxable", "shares": 999, "cost_basis": 1.0, "price": 33.0},  # dup acct guarded
    ])
    p = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p["qty"] == 300 and p["basis"] == 9000.0
    assert set(p["accounts"]) == {"schwab_taxable", "schwab_rollover_ira"}
    assert p["account_components"]["schwab_taxable"]["qty"] == 100   # components preserved
    # missing basis on one account → gain UNAVAILABLE, never zero
    _write_holdings(hpath, [
        {"symbol": "SH", "account": "schwab_taxable", "shares": 100, "cost_basis": None, "price": 33.0},
        {"symbol": "SH", "account": "schwab_rollover_ira", "shares": 200, "cost_basis": 6000.0, "price": 33.0}])
    p2 = sl.resolve_position_cycle(cur, conn, "SH", bars, "SPY")
    assert p2["inv_gain_pct"] is None and "UNAVAILABLE" in p2["gain_note"]


def test_concurrent_evaluators_one_open_cycle(pg_env):
    conn, cur, hpath = pg_env
    bars = _fresh_bench()
    _write_holdings(hpath, [SH_ROW])
    sl.ensure_cycle_tables(cur, conn)
    import threading
    ids, errs = [], []
    cur.execute("SELECT current_schema()")
    schema = cur.fetchone()[0]

    def worker():
        try:
            c2 = psycopg2.connect(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
                                  user=os.environ.get("DB_USER", "postgres"),
                                  password=os.environ.get("DB_PASSWORD", ""),
                                  host=os.environ.get("DB_HOST", "localhost"),
                                  port=os.environ.get("DB_PORT", "5432"))
            k = c2.cursor()
            k.execute(f'SET search_path TO "{schema}"')
            p = sl.resolve_position_cycle(k, c2, "SH", bars, "SPY")
            ids.append(p["cycle_id"])
            c2.close()
        except Exception as e:
            errs.append(str(e))

    ts = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    cur.execute("SELECT count(*) FROM inverse_position_cycles WHERE status='OPEN'")
    assert cur.fetchone()[0] == 1
    assert len(set(ids)) == 1


# ── P1-2: full evaluate_all() holdings→card→ledger (real PG) ─────────────────

@pytest.fixture()
def e2e(pg_env, tmp_path, monkeypatch):
    conn, cur, hpath = pg_env
    bars = _fresh_bench()
    monkeypatch.setitem(sl._BARS_CACHE, "SPY", bars)
    monkeypatch.setitem(sl._BARS_CACHE, "QQQ", bars)
    monkeypatch.setitem(sl._BARS_CACHE, "DIA", bars)
    monkeypatch.setitem(sl._BARS_CACHE, "IWM", bars)
    snap_dir = tmp_path / "runtime"
    snap_dir.mkdir()
    monkeypatch.setattr(sl, "SNAP", snap_dir / "stoplights.json")
    recs = tmp_path / "recs.json"
    recs.write_text(json.dumps({"groups": {"short_side": [
        {"title": "HEDGE · SH (1x inverse SPY — deterioration)"}]}}))
    real_loads = json.loads
    orig_read = Path.read_text
    def patched_read(self, *a, **k):
        if str(self).endswith("defense_recommendations_latest.json"):
            return recs.read_text()
        return orig_read(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", patched_read)
    # keep the DB helper away from prod: evaluate_all takes cur/conn directly
    yield conn, cur, hpath, bars, recs


def _run_eval(conn, cur):
    import options_lifecycle_alerts as ola
    return sl.evaluate_all(cur, conn, notify=False)


def test_e2e_scenario_a_profitable_open_hedge(e2e):
    conn, cur, hpath, bars, recs = e2e
    _write_holdings(hpath, [SH_ROW])           # +10% ≥ tp1 8%
    out = _run_eval(conn, cur)
    card = next(c for c in out["candidates"] if c["inverse"] == "SH")
    L = card["lights"]
    cur.execute("SELECT count(*) FROM inverse_position_cycles WHERE instrument='SH' AND status='OPEN'")
    assert cur.fetchone()[0] == 1
    assert L["MANAGE"]["state"] == "AMBER" and "reduce 50%" in L["MANAGE"]["reason"]
    assert L["EXIT"]["state"] != "RED"
    assert card["position"]["qty"] == 300 and card["position"]["basis"] == 9000.0
    assert card["position"]["inv_gain_pct"] == 10.0
    assert isinstance(card["position"]["held_sessions"], int)
    assert card["position"]["accounts"] == ["schwab_taxable"]
    assert "not computable" in L["MANAGE"].get("note", "")
    cur.execute("SELECT count(*) FROM inverse_stoplight_transitions WHERE instrument='SH' AND light='MANAGE'")
    n1 = cur.fetchone()[0]
    _run_eval(conn, cur)                       # replay
    cur.execute("SELECT count(*) FROM inverse_stoplight_transitions WHERE instrument='SH' AND light='MANAGE'")
    assert cur.fetchone()[0] == n1             # no duplicate transitions


def test_e2e_scenario_b_thesis_reversal(e2e):
    conn, cur, hpath, bars, recs = e2e
    _write_holdings(hpath, [SH_ROW])
    _run_eval(conn, cur)
    recs.write_text(json.dumps({"groups": {"short_side": []}}))   # thesis card GONE → RED
    out = _run_eval(conn, cur)
    L = next(c for c in out["candidates"] if c["inverse"] == "SH")["lights"]
    assert L["THESIS"]["state"] == "RED"
    assert L["EXIT"]["state"] == "RED" and "regardless of P&L" in L["EXIT"]["reason"]
    cur.execute("SELECT status FROM inverse_position_cycles WHERE instrument='SH'")
    assert cur.fetchone()[0] == "OPEN"          # no fabricated close from EXIT RED
    cur.execute("""SELECT count(*) FROM inverse_stoplight_transitions
                   WHERE instrument='SH' AND light='EXIT' AND new_state LIKE 'RED%'""")
    assert cur.fetchone()[0] == 1               # transition identity created ONCE


def test_e2e_scenario_c_stale_bars_fail_closed(e2e):
    conn, cur, hpath, bars, recs = e2e
    stale = [dict(b) for b in bars]
    shift = 30
    for b in stale:
        b["d"] = str(date.fromisoformat(b["d"]) - timedelta(days=shift))
    for sym in ("SPY", "QQQ", "DIA", "IWM"):
        sl._BARS_CACHE[sym] = stale
    _write_holdings(hpath, [SH_ROW])
    out = _run_eval(conn, cur)
    card = next(c for c in out["candidates"] if c["inverse"] == "SH")
    L = card["lights"]
    assert L["ENTRY"]["state"] == "RED" and "STALE" in L["ENTRY"]["reason"]
    assert stale[-1]["d"] in L["ENTRY"]["reason"]      # stale close date shown
    assert "stage" not in L["ENTRY"]["reason"].lower() # no Stage authorization
    assert card["position"] is not None                # existing risk still represented
    assert L["MANAGE"]["state"] in ("GREEN", "AMBER", "RED")


def test_e2e_scenario_d_close_and_reopen(e2e):
    conn, cur, hpath, bars, recs = e2e
    _write_holdings(hpath, [SH_ROW])
    _run_eval(conn, cur)
    cur.execute("SELECT position_cycle_id FROM inverse_position_cycles WHERE instrument='SH' AND status='OPEN'")
    a = cur.fetchone()[0]
    _write_holdings(hpath, [])                  # fresh, confirmed absent
    _run_eval(conn, cur)
    cur.execute("SELECT status FROM inverse_position_cycles WHERE position_cycle_id=%s", (a,))
    assert cur.fetchone()[0] == "CLOSED"
    _write_holdings(hpath, [SH_ROW])
    _run_eval(conn, cur)
    cur.execute("SELECT position_cycle_id, first_seen_session FROM inverse_position_cycles WHERE instrument='SH' AND status='OPEN'")
    b, first_b = cur.fetchone()
    assert b != a
    held, _ = sl._held_sessions(bars, first_b)
    assert held == 1                            # reset, not inherited
    cur.execute("SELECT status, first_seen_session FROM inverse_position_cycles WHERE position_cycle_id=%s", (a,))
    assert cur.fetchone()[0] == "CLOSED"        # cycle A immutable
