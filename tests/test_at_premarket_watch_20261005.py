"""Active Trader premarket watch (operator 2026-10-05: "why can't [it] pick up premarket").

Heads-up only (kind PREMARKET_WATCH) 07:00–09:29 ET with the levels for the open (PM high = break,
PM VWAP = stop reference). Pins: replay never sees bars after as-of; gap/volume/rotation/VWAP math;
fail-closed float; premarket spread limit; throttle 1 per symbol per 30 min; shadow journals only,
send uses momentum_alerts.telegram_send with the AT header (comms-editor exemption); no trade
context anywhere. Fakes only: no OpenD, no database, no Telegram.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import premarket_watch as pw  # noqa: E402

DAY = "2026-10-05"
ET = pw.ET
NOW = datetime(2026, 10, 5, 8, 1, 5, tzinfo=ET).timestamp()


@pytest.fixture(autouse=True)
def _journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    return tmp_path / "at"


def _bars(n=60, start=(7, 0), base=10.0, step=0.01, vol=5000, day=DAY):
    out = []
    h, m = start
    for i in range(n):
        mm = m + i
        hh, mm = h + mm // 60, mm % 60
        c = base + step * i
        out.append({"time_key": f"{day} {hh:02d}:{mm:02d}:00", "open": c, "high": c + 0.02, "low": c - 0.02,
                    "close": c, "volume": vol})
    return out


class FakeData:
    def __init__(self, bars, snap, book=None, tape=None):
        self._bars, self._snap, self._book, self._tape = bars, snap, book, tape
        self.bar_calls = []

    def snapshot(self, syms):
        return {s: self._snap.get(s, {}) for s in syms}

    def bars(self, sym):
        self.bar_calls.append(sym)
        return self._bars.get(sym, [])

    def book(self, sym, now):
        return self._book

    def tape(self, sym):
        return self._tape or []


def good_book(at=NOW, bid=10.58, ask=10.59):
    return {"bids": [(bid - i * 0.01, 8000) for i in range(10)],
            "asks": [(ask + i * 0.01, 1500) for i in range(9)] + [(10.80, 40000)], "ts_epoch": at - 2}


def test_features_never_use_bars_after_as_of_or_after_the_open():
    bars = _bars(200, start=(7, 0))                         # runs to 10:19
    f = pw.premarket_features(bars, prev_close=9.0, float_mm=5.0, day=DAY, as_of_hm="08:00", vwap_hold_bars=5)
    assert f["bars"] == 61 and f["last_bar_at"] == "08:00"
    f2 = pw.premarket_features(bars, prev_close=9.0, float_mm=5.0, day=DAY, as_of_hm="11:00", vwap_hold_bars=5)
    assert f2["last_bar_at"] == "09:29"                     # regular-hours bars are not premarket
    other_day = pw.premarket_features(_bars(5, day="2026-10-02"), prev_close=9.0, float_mm=5.0, day=DAY,
                                      as_of_hm="09:00", vwap_hold_bars=5)
    assert other_day["status"] == "NO_PREMARKET_BARS"


def test_feature_math():
    bars = _bars(61, start=(7, 0), base=10.0, step=0.01, vol=5000)
    f = pw.premarket_features(bars, prev_close=9.0, float_mm=5.0, day=DAY, as_of_hm="08:00", vwap_hold_bars=5)
    assert f["last"] == pytest.approx(10.6) and f["gap_pct"] == pytest.approx(17.78, abs=0.01)
    assert f["pm_volume"] == 61 * 5000 and f["rotation_pct"] == pytest.approx(6.1)
    assert f["pm_high"] == pytest.approx(10.62) and f["pm_high_at"] == "08:00"
    assert f["pm_vwap"] == pytest.approx(10.3, abs=1e-6) and f["above_vwap"] is True


def test_decide_reasons_and_fail_closed_float():
    cfg = pw.PremarketConfig()
    f = pw.premarket_features(_bars(61, vol=500), prev_close=10.2, float_mm=None, day=DAY, as_of_hm="08:00",
                              vwap_hold_bars=5)
    d = pw.decide(f, {}, {}, cfg=cfg, quote_age_s=10)
    assert d["verdict"] == ma.VETO
    assert {"FLOAT_UNKNOWN", "GAP_SMALL", "PM_VOLUME_THIN"} <= set(d["veto_reasons"])
    good = pw.premarket_features(_bars(61), prev_close=9.0, float_mm=5.0, day=DAY, as_of_hm="08:00", vwap_hold_bars=5)
    assert pw.decide(good, {}, {}, cfg=cfg, quote_age_s=10)["verdict"] == ma.ALERT
    big = dict(good, float_mm=80.0)
    assert "FLOAT_TOO_LARGE" in pw.decide(big, {}, {}, cfg=cfg, quote_age_s=10)["veto_reasons"]
    falling = pw.premarket_features(_bars(61, step=-0.01, base=11.0), prev_close=9.0, float_mm=5.0, day=DAY,
                                    as_of_hm="08:00", vwap_hold_bars=5)
    assert "BELOW_PM_VWAP" in pw.decide(falling, {}, {}, cfg=cfg, quote_age_s=10)["veto_reasons"]


def test_premarket_spread_limit_replaces_rth_limit():
    cfg = pw.PremarketConfig()
    good = pw.premarket_features(_bars(61), prev_close=9.0, float_mm=5.0, day=DAY, as_of_hm="08:00", vwap_hold_bars=5)
    l2 = {"ok": False, "reasons": ["SPREAD_WIDE"], "spread_bps": 120.0, "depth_ratio": 2.0, "best_ask": 10.6}
    assert pw.decide(good, l2, {}, cfg=cfg, quote_age_s=5)["verdict"] == ma.ALERT      # 120 bps ok premarket
    l2w = dict(l2, spread_bps=200.0)
    assert "SPREAD_WIDE" in pw.decide(good, l2w, {}, cfg=cfg, quote_age_s=5)["veto_reasons"]


def test_supply_near_pm_high_reports_wall():
    near = pw.supply_near_level([(10.59, 1500), (10.60, 1500), (10.65, 40000), (11.5, 99999)], 10.62, near_pct=1.0)
    assert near["ask_shares_near_level"] == 43000 and near["wall_price"] == 10.65


def test_shadow_pass_journals_with_levels_and_throttles(_journal_dir):
    data = FakeData({"SDEV": _bars(61)}, {"SDEV": {"prev_close": 9.0}}, book=good_book(),
                    tape=[{"ts_epoch": NOW - 5, "price": 10.6, "volume": 100, "direction": "BUY"}] * 20)
    cfg = pw.PremarketConfig()
    sent = []
    rows = pw.evaluate([{"symbol": "SDEV", "float_mm": 1.8}], data=data, cfg=cfg, now=NOW, day=DAY,
                       as_of_hm="08:00", live_book=True, persist=True, send_fn=lambda **k: sent.append(k) or {"sent": True})
    r = rows[0]
    assert r["verdict"] == ma.ALERT and r["kind"] == pw.PREMARKET_WATCH and r["sent"] is False and sent == []
    assert r["candidate"]["entry_ref"] == pytest.approx(10.62) and r["candidate"]["stop_ref"] == r["premarket"]["pm_vwap"]
    assert r["candidate"]["float_source"] == "scan"
    assert r["supply_near_pm_high"]["wall_price"] == 10.80 or r["supply_near_pm_high"]["ask_shares_near_level"] > 0
    lines = (_journal_dir / "momentum_alerts.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["contract"] == ma.CONTRACT
    fresh = FakeData({"SDEV": _bars(71)}, {"SDEV": {"prev_close": 9.0}}, book=good_book(at=NOW + 600, bid=10.68, ask=10.69))
    again = pw.evaluate([{"symbol": "SDEV", "float_mm": 1.8}], data=fresh, cfg=cfg, now=NOW + 600, day=DAY,
                        as_of_hm="08:10", live_book=True, persist=True)
    assert again[0]["verdict"] == ma.VETO and again[0]["veto_reasons"] == ["COOLDOWN"]


def test_send_mode_uses_the_at_alert_path_and_header():
    data = FakeData({"SDEV": _bars(61)}, {"SDEV": {"prev_close": 9.0}}, book=good_book())
    got = []
    rows = pw.evaluate([{"symbol": "SDEV", "float_mm": 1.8}], data=data, cfg=pw.PremarketConfig(mode="send"),
                       now=NOW, day=DAY, as_of_hm="08:00", live_book=True, persist=False,
                       send_fn=lambda **k: got.append(k) or {"sent": True})
    assert rows[0]["sent"] is True and got[0]["alert_type"] == "at_scalp_premarket"
    text = got[0]["title"] + "\n" + got[0]["body"]
    assert text.splitlines()[0] == ma.AT_SCALP_ALERT_HEADER and ma.NOT_AN_ORDER in text
    assert "time to buy" not in text.lower() and "PM high" in text and "PM VWAP" in text
    from lib.comms_editor import is_active_trader_scalp_alert
    assert is_active_trader_scalp_alert(text)


def test_large_float_is_skipped_before_any_subscription_and_moomoo_float_is_labelled():
    data = FakeData({"BIG": _bars(61), "NEW": _bars(61)}, {"BIG": {"prev_close": 9.0},
                                                          "NEW": {"prev_close": 9.0, "float_mm": 4.0}})
    rows = pw.evaluate([{"symbol": "BIG", "float_mm": 900.0}, {"symbol": "NEW", "float_mm": None}], data=data,
                       cfg=pw.PremarketConfig(), now=NOW, day=DAY, as_of_hm="08:00", live_book=False, persist=False)
    assert data.bar_calls == ["NEW"] and rows[0]["candidate"]["float_source"] == "moomoo_outstanding"


def test_replay_skips_book_and_tape(_journal_dir):
    class NoBook(FakeData):
        def book(self, sym, now):
            raise AssertionError("replay must not read a live book")
    data = NoBook({"SDEV": _bars(61)}, {"SDEV": {"prev_close": 9.0}})
    rows = pw.evaluate([{"symbol": "SDEV", "float_mm": 1.8}], data=data, cfg=pw.PremarketConfig(), now=NOW, day=DAY,
                       as_of_hm="08:00", live_book=False, persist=False)
    assert rows[0]["replay_as_of"] == "08:00" and rows[0]["l2"] == {}
    assert not (_journal_dir / "momentum_alerts.jsonl").exists()


def test_window_and_config():
    cfg = pw.PremarketConfig()
    assert pw.in_window(datetime(2026, 10, 5, 7, 0, tzinfo=ET), cfg)
    assert pw.in_window(datetime(2026, 10, 5, 9, 29, tzinfo=ET), cfg)
    assert not pw.in_window(datetime(2026, 10, 5, 9, 30, tzinfo=ET), cfg)
    assert not pw.in_window(datetime(2026, 10, 4, 8, 0, tzinfo=ET), cfg)     # Sunday
    assert pw.PremarketConfig.from_mapping({"mode": "send", "excluded_routes": ["reject"]}).excluded_routes == ("reject",)
    with pytest.raises(ValueError):
        pw.PremarketConfig.from_mapping({"mode": "live"})
    with pytest.raises(SystemExit):
        pw.main(["--apply", "--as-of", "08:00"])                            # a replay never journals


def test_no_trade_context_or_order_path():
    src = (ROOT / "scripts" / "active_trader" / "premarket_watch.py").read_text()
    for banned in ("OpenSecTradeContext", "unlock_trade", "place_order", "modify_order", "TrdEnv"):
        assert banned not in src
    tree = ast.parse(src)
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"place_order", "unlock_trade", "cancel_order", "request_history_kline"}  # no history quota
