"""Alpha Vantage fundamentals: paced calls, one retry on the per-second notice, no funds; and the
comms editor no longer links "ET"/"API" chrome as tickers (2026-10-04 data-source alert).

Stubs only: no network, no database writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import external_market_data_ingest as m  # noqa: E402
from scripts.lib import comms_editor as ce  # noqa: E402

BURST = {"Information": "Thank you for using Alpha Vantage! Please consider spreading out your free API "
                        "requests more sparingly (1 request per second)."}
DAILY = {"Information": "Our standard API rate limit is 25 requests per day."}


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.c = _Cur()

    def cursor(self):
        return self.c

    def commit(self):
        pass

    def close(self):
        pass


def _run(monkeypatch, responses):
    sleeps, calls = [], []
    seq = list(responses)
    monkeypatch.setattr(m, "_env", lambda k: "key")
    monkeypatch.setattr(m, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(m.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(m, "_av_overview", lambda sym, key: calls.append(sym) or seq.pop(0))
    res = m.ingest_alpha_vantage(symbols=["AAA", "BBB", "CCC"], limit=3)
    return res, sleeps, calls


def _ok(sym):
    return {"Symbol": sym, "PERatio": "10"}


def test_calls_are_paced(monkeypatch):
    res, sleeps, calls = _run(monkeypatch, [_ok("AAA"), _ok("BBB"), _ok("CCC")])
    assert calls == ["AAA", "BBB", "CCC"] and res["fetched"] == 3
    assert sleeps == [m.AV_MIN_INTERVAL_S, m.AV_MIN_INTERVAL_S] and m.AV_MIN_INTERVAL_S >= 1.0


def test_burst_notice_backs_off_and_retries_once(monkeypatch):
    res, sleeps, calls = _run(monkeypatch, [_ok("AAA"), BURST, _ok("BBB"), _ok("CCC")])
    assert calls == ["AAA", "BBB", "BBB", "CCC"] and res["fetched"] == 3
    assert m.AV_BURST_BACKOFF_S in sleeps


def test_daily_quota_is_not_retried(monkeypatch):
    res, sleeps, calls = _run(monkeypatch, [_ok("AAA"), DAILY, DAILY])
    assert calls == ["AAA", "BBB", "CCC"] and res["fetched"] == 1
    assert m.AV_BURST_BACKOFF_S not in sleeps


def test_selection_excludes_funds(monkeypatch):
    monkeypatch.setattr(m, "_get_symbols", lambda: [])   # empty stub result → fallback universe
    cur = _Cur()
    m._alpha_vantage_symbols(cur, 5)
    sql = " ".join(cur.sql)
    assert "symbol_profiles" in sql and "'etf'" in sql and "'ETF'" in sql


def test_chrome_et_and_api_are_not_tickers():
    subs = [{"symbol": "ET", "guid": "g1"}, {"symbol": "API", "guid": "g2"}]
    text = "Next run: tomorrow 08:00 ET. Please consider spreading out your free API requests."
    assert ce.unambiguous_subjects(text, subs) == []
    assert ce.unambiguous_subjects("Watching $ET into earnings", [{"symbol": "ET", "guid": "g1"}]) != []


def test_weekday_is_not_a_company():
    from scripts.lib.operator_subject_resolver import resolve_subjects
    syms = {r.get("symbol") for r in resolve_subjects("delivery check before Monday. NOT A SIGNAL", book=[])}
    assert "MNDY" not in syms
    assert "MNDY" in {r.get("symbol") for r in resolve_subjects("MNDY up 5%", book=[])}


def test_alert_message_never_glues_units_to_missing_values():
    from active_trader import momentum_alerts as ma
    c = ma.Candidate(symbol="ABCD", lane="BELOW", ign=0)
    t, b = ma.build_message(c, ma.TRIGGERED, {"source": "moomoo", "levels": 0}, {"source": "moomoo"}, {})
    text = f"{t}\n{b}"
    for bad in ("n/aM", "n/ax", "n/as", "n/a bps"):
        assert bad not in text, bad
    c2 = ma.Candidate(symbol="ABCD", lane="BELOW", ign=0, float_mm=6.2, rvol=9.0)
    _, b2 = ma.build_message(c2, ma.ARMED, {"source": "moomoo", "levels": 10, "depth_ratio": 1.4, "spread_bps": 20,
                                            "age_s": 1}, {}, {"quote_age_s": 2})
    assert "float 6.2M" in b2 and "RVOL 9.0x" in b2 and "spread 20 bps" in b2 and "quote 2s" in b2
