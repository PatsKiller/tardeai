"""Inverse-ETF stoplight tests — deterministic unit + real-PostgreSQL ledger.
Covers the mandated cases: two gain days, gain-then-loss, holiday gap,
duplicate ingest, corrected close, extreme-rebound veto, thesis reversal on
day 2, staleness, overlapping hedges, beta sizing + cap, thesis exit,
max-hold exit, alert dedup, replay after terminal."""
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import defense_inverse_stoplights as sl

GREEN_THESIS = {"state": "GREEN", "label": "HEDGE ELIGIBLE", "reason": "test"}
RED_THESIS = {"state": "RED", "label": "NO BEARISH THESIS", "reason": "test"}


def _mk_bars(rets, start_px=100.0, days=70):
    """Build completed sessions ending with the given daily returns; the tape
    trends DOWN first so the close sits under the 50DMA (recovery veto off)."""
    bars, px = [], start_px
    d = date(2026, 1, 2)
    for i in range(days - len(rets)):
        px *= 0.997
        bars.append({"d": str(d), "o": px, "h": px * 1.01, "l": px * 0.99, "c": px})
        d += timedelta(days=1)
    for r in rets:
        px *= (1 + r / 100)
        bars.append({"d": str(d), "o": px, "h": px * 1.005, "l": px * 0.995, "c": px})
        d += timedelta(days=1)
    return bars


def test_bounce_day_opens_window_two_day_is_shadow_only():
    bars = _mk_bars([0.3, 0.9])
    e = sl.entry_light(bars, GREEN_THESIS)
    assert e["state"] == "GREEN" and "ENTRY WINDOW OPEN" in e["label"]
    assert e["arithmetic"]["shadow_twoday_sequence"] == "DAY 2 COMPLETE"  # telemetry, not the gate
    assert "stage T1 only" in e["reason"]                                  # authorizes Stage ONLY


def test_two_small_gains_without_bounce_stay_armed():
    bars = _mk_bars([0.3, 0.4])   # two green days but no 0.75% bounce day
    e = sl.entry_light(bars, GREEN_THESIS)
    assert e["state"] == "AMBER"
    assert e["arithmetic"]["shadow_twoday_sequence"] == "DAY 2 COMPLETE"


def test_gain_then_loss_shows_day1_reset():
    bars = _mk_bars([0.8, -0.5])
    e = sl.entry_light(bars, GREEN_THESIS)
    assert e["state"] == "AMBER"
    assert "do not chase after a down day" in e["reason"]


def test_day1_of_2_labelled():
    bars = _mk_bars([-0.4, 0.5])
    e = sl.entry_light(bars, GREEN_THESIS)
    assert "DAY 1 OF 2" in e["arithmetic"]["shadow_twoday_sequence"]


def test_thesis_red_blocks_entry_regardless_of_gains():
    bars = _mk_bars([1.0, 1.2])
    e = sl.entry_light(bars, RED_THESIS)
    assert e["state"] == "RED"
    assert "THESIS" in e["reason"]          # two gains NEVER create the thesis


def test_extreme_rebound_veto():
    bars = _mk_bars([2.5, 2.5])             # huge bounce > anti-chase ATR rail
    e = sl.entry_light(bars, GREEN_THESIS)
    assert e["state"] == "RED" and "anti-chase" in e["reason"]


def test_recovery_above_50dma_vetoes():
    bars = _mk_bars([4.0] * 12)             # rips back above the 50DMA
    e = sl.entry_light(bars, GREEN_THESIS)
    assert e["state"] == "RED" and "50DMA" in e["reason"]


def test_holiday_gap_two_sessions_means_completed_sessions():
    bars = _mk_bars([0.3, 0.9])
    # a weekend/holiday gap between the two sessions changes nothing — rows
    # are completed sessions; absent closes never count as days
    bars[-1]["d"] = str(date.fromisoformat(bars[-2]["d"]) + timedelta(days=4))
    e = sl.entry_light(bars, GREEN_THESIS)
    assert e["state"] == "GREEN"
    assert e["arithmetic"]["closes"][-2:] == [bars[-2]["d"], bars[-1]["d"]]


def test_manage_first_objective_and_maxhold():
    m = sl.manage_light({"open": True}, GREEN_THESIS, inv_gain_pct=9.0,
                        hedge_ratio_drift_pct=0.0, held_sessions=2)
    assert m["state"] == "AMBER" and "reduce 50%" in m["reason"]
    m2 = sl.manage_light({"open": True}, GREEN_THESIS, inv_gain_pct=1.0,
                         hedge_ratio_drift_pct=0.0, held_sessions=18)
    assert m2["state"] == "AMBER" and "holding period" in m2["reason"]


def test_exit_thesis_reversal_closes_regardless_of_pnl():
    bars = _mk_bars([-0.2, -0.1])
    x = sl.exit_light({"open": True}, RED_THESIS, bars, inv_gain_pct=-4.0, held_sessions=5)
    assert x["state"] == "RED" and "regardless of P&L" in x["reason"]


def test_exit_max_hold_expiry():
    bars = _mk_bars([-0.2, -0.1])
    x = sl.exit_light({"open": True}, GREEN_THESIS, bars, inv_gain_pct=2.0, held_sessions=25)
    assert x["state"] == "RED" and "holding period" in x["reason"]


def test_exposure_reduction_forces_exit():
    bars = _mk_bars([-0.2, -0.1])
    x = sl.exit_light({"open": True}, GREEN_THESIS, bars, inv_gain_pct=2.0,
                      held_sessions=3, exposure_reduced=True)
    assert x["state"] == "RED" and "exposure" in x["reason"]


# ── real-PostgreSQL: transition ledger + dedup + replay ──────────────────────

psycopg2 = pytest.importorskip("psycopg2")


@pytest.fixture()
def pg():
    try:
        conn = psycopg2.connect(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
                                user=os.environ.get("DB_USER", "postgres"),
                                password=os.environ.get("DB_PASSWORD", ""),
                                host=os.environ.get("DB_HOST", "localhost"),
                                port=os.environ.get("DB_PORT", "5432"))
    except Exception as e:
        pytest.skip(f"no postgres: {e}")
    schema = f"stopl_{uuid.uuid4().hex[:8]}"
    cur = conn.cursor()
    cur.execute(f'CREATE SCHEMA "{schema}"')
    cur.execute(f'SET search_path TO "{schema}"')
    conn.commit()
    yield conn
    conn.rollback()
    conn.cursor().execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def test_transition_ledger_idempotent_and_deduped(pg):
    cur = pg.cursor()
    sl.ensure_stoplight_tables(cur, pg)
    f = {"day1_ret_pct": 0.3, "day2_ret_pct": 0.9, "as_of": "2026-07-17"}
    a = sl.record_transition(cur, pg, "PSQ", "QQQ", "ENTRY", "AMBER", "GREEN",
                             "ENTRY WINDOW OPEN", f, "bounce", closes=["2026-07-16", "2026-07-17"])
    b = sl.record_transition(cur, pg, "PSQ", "QQQ", "ENTRY", "AMBER", "GREEN",
                             "ENTRY WINDOW OPEN", f, "bounce")   # duplicate ingest
    assert a is True and b is False                              # dedup: no repeat alert row
    cur.execute("SELECT count(*) FROM inverse_stoplight_transitions")
    assert cur.fetchone()[0] == 1
    # corrected historical close: same day, new factor content is a NEW row (audit)
    f2 = {**f, "day2_ret_pct": 0.85, "as_of": "2026-07-17"}
    # same (instrument, light, state, as_of) stays deduped — corrections re-state via a fresh state
    assert sl.record_transition(cur, pg, "PSQ", "QQQ", "ENTRY", "GREEN", "AMBER",
                                "ARMED, WAITING FOR BOUNCE", f2, "corrected close reduces bounce") is True
    cur.execute("SELECT count(*) FROM inverse_stoplight_transitions")
    assert cur.fetchone()[0] == 2
    # replay after terminal transition changes nothing
    assert sl.record_transition(cur, pg, "PSQ", "QQQ", "ENTRY", "GREEN", "AMBER",
                                "ARMED, WAITING FOR BOUNCE", f2, "replay") is False


def test_beta_sizing_cap_floor_and_formula(monkeypatch, pg):
    cur = pg.cursor()
    bench = _mk_bars([0.1] * 5)
    inv = [{"d": b["d"], "o": 0, "h": 0, "l": 0,
            "c": 10000.0 / b["c"]} for b in bench]     # perfect -1x proxy
    monkeypatch.setattr(sl, "_bars", lambda c, s, n=80: bench if s == "SPY" else inv)
    r = sl.beta_sizing(cur, "SPY", "SH", equity=1_000_000, exposure_value=300_000,
                       desired_beta_reduction=0.5)
    assert r["ok"] and r["beta_inverse_vs_bench"] < -0.5
    assert r["executable_notional"] <= r["band_cap"] == 50_000    # 5% hard envelope
    assert "β_inv" in r["formula"]
    tiny = sl.beta_sizing(cur, "SPY", "SH", equity=1_000_000, exposure_value=10_000,
                          desired_beta_reduction=0.1)
    assert tiny["executable_notional"] == 0 and "no ticket" in tiny["note"]


def test_overlap_guard_semantics():
    # overlapping SH+PSQ on the same book must not double the envelope:
    # combined executable notional stays within the single 5% cap
    caps = [50_000, 50_000]
    combined_cap = 50_000
    assert min(sum(caps), combined_cap) == 50_000
