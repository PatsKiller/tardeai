"""Stop alerts carry their mark's price, source and as_of — and never show a stale price as live.

Operator price rule (2026-11-07): a live price comes from the Finviz cache (fresh = last_fetched <= 30 min);
if Finviz is down or stale, a fresh Schwab / Alpaca / moomoo quote; never yfinance, never a stored DB price
older than 30 min. LQ-20261107-03: `stop_lifecycle_monitor` built proximity/lifecycle off the store's
`current_price` and `stop_drift_alert` off `portfolio_holdings()`'s `current_price` — both shown as live with
no provenance. These tests use synthetic tickers only; the Finviz cache and the data broker are injected.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "scripts"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import stop_drift_alert as sda  # noqa: E402
import stop_health_check as shc  # noqa: E402
import stop_lifecycle_monitor as slm  # noqa: E402
from lib import stop_alert_price as sap  # noqa: E402

NOW = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)


def _iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


DOC = {"holdings": [
    # the store says 41.00 (a 3h-old canonical mark); Finviz has a live 42.50
    {"symbol": "ZQALP", "account": "schwab_fixture", "shares": 100, "broker_actual_shares": 100,
     "price": 41.00, "canonical_mark": 41.00, "canonical_mark_ingested_at": _iso(180)},
    # Finviz is stale for this one; a fresh broker quote is the backup
    {"symbol": "ZQBET", "account": "schwab_fixture", "shares": 10, "broker_actual_shares": 10,
     "price": 88.00, "canonical_mark": 88.00, "canonical_mark_ingested_at": _iso(180)},
    # nothing fresh anywhere: the stored mark serves, flagged stale
    {"symbol": "ZQCAP", "account": "schwab_fixture", "shares": 5, "canonical_mark": 12.0,
     "canonical_mark_ingested_at": _iso(300), "cost_basis": 500.0},
    # cash is never a stop's collateral
    {"symbol": "ZQCASH", "account": "schwab_fixture", "is_cash": True, "shares": 500},
    # no price of any kind: dropped, never marked 0
    {"symbol": "ZQNONE", "account": "schwab_fixture", "shares": 1},
]}

FINVIZ = {"ZQALP": {"price": 42.50, "as_of": _iso(2)},     # fresh
          "ZQBET": {"price": 86.00, "as_of": _iso(180)}}    # stale (3h)
QUOTES = {"ZQBET": {"price": 87.40, "as_of": _iso(1), "source": "schwab"}}


# ── the rendering rule ─────────────────────────────────────────────────────

def test_a_fresh_mark_is_shown_with_its_source_and_as_of():
    line = sap.price_line(42.5, "finviz", "2026-11-07T14:58:00Z", 120, False)
    assert line == "mark $42.50 (finviz, as of 2026-11-07T14:58:00Z)"


def test_a_stale_mark_is_labelled_stale_and_never_reads_as_live():
    line = sap.price_line(42.5, "stored_mark", "2026-11-07T12:00:00Z", 10800, True)
    assert "STALE" in line and "not live" in line and "3.0h old" in line
    assert "$42.50" in line and "stored_mark" in line


def test_an_undated_mark_is_stale_not_live():
    for stale, age, as_of in ((None, None, None), (None, 600, None), (True, None, None)):
        line = sap.price_line(9.0, "stored_mark", as_of, age, stale)
        assert "STALE" in line and "not live" in line, (stale, age, as_of)


def test_no_price_says_unknown_and_invents_nothing():
    for price in (None, 0, ""):
        assert sap.price_line(price, "none", None, None, True).startswith("mark UNKNOWN")
    assert sap.price_line(None, None, None, None, None) == sap.price_line(None, None, None, None, None)


def test_a_sub_dollar_mark_is_never_rounded_to_zero():
    """SRNE is $0.0003: "$0.00" would show an invented zero as the live mark."""
    line = sap.price_line(0.0003, "finviz", "2026-11-07T14:58:00Z", 60, False)
    assert "$0.0003" in line and "$0.00 " not in line


def test_age_text_is_human_and_refuses_nonsense():
    assert sap.age_text(45) == "45s" and sap.age_text(720) == "12m" and sap.age_text(10800) == "3.0h"
    assert sap.age_text(None) is None and sap.age_text("bad") is None and sap.age_text(-5) is None


# ── the mark ladder (Finviz -> fresh backup -> stored, labelled) ───────────

def test_finviz_beats_the_stored_price():
    rows = {r["symbol"]: r for r in sap.holdings_marks(DOC, finviz=FINVIZ, quotes=QUOTES, now=NOW)}
    alp = rows["ZQALP"]
    assert alp["price"] == 42.50 and alp["price_source"] == "finviz"
    assert alp["price_stale"] is False and alp["price_as_of"] == _iso(2)


def test_a_fresh_backup_quote_serves_when_finviz_is_stale():
    rows = {r["symbol"]: r for r in sap.holdings_marks(DOC, finviz=FINVIZ, quotes=QUOTES, now=NOW)}
    bet = rows["ZQBET"]
    assert bet["price"] == 87.40 and bet["price_source"] == "data_broker:schwab"
    assert bet["price_stale"] is False


def test_with_nothing_fresh_the_stored_mark_is_served_and_flagged_stale():
    rows = {r["symbol"]: r for r in sap.holdings_marks(DOC, finviz=FINVIZ, quotes=QUOTES, now=NOW)}
    cap = rows["ZQCAP"]
    assert cap["price"] == 12.0 and cap["price_source"] == "stored_mark"
    assert cap["price_stale"] is True and cap["price_age_s"] == 18000


def test_cash_and_price_less_rows_are_never_marked():
    rows = {r["symbol"]: r for r in sap.holdings_marks(DOC, finviz=FINVIZ, quotes=QUOTES, now=NOW)}
    assert "ZQCASH" not in rows and "ZQNONE" not in rows


def test_the_backup_reader_is_stated_and_empty_without_a_database(monkeypatch):
    """No DB means no backup: the caller labels the stored mark stale, it never fabricates a quote."""
    import lib.holdings_document as hd

    monkeypatch.setattr(hd, "default_db_query", lambda: None)
    assert sap._backup_quotes({"ZQALP": {"price": 1.0, "as_of": _iso(180)}}, DOC["holdings"], NOW) == {}


def test_a_yfinance_row_in_the_finviz_cache_is_never_served_as_a_finviz_mark(tmp_path):
    """The live cache carried two non-Finviz rows (SRNE, AMANX: buy-from-yfinance). 'Never yfinance' means a
    caller falls through to its next rung, so a stored mark shows flagged stale and never as a live Finviz one."""
    import json

    from lib import portfolio_positions as pp

    cache = tmp_path / "finviz_quote_cache.json"
    cache.write_text(json.dumps({
        "ZQALP": {"price": 10.0, "last_fetched": "2026-11-07 14:58:00 ET", "source": "finviz_elite"},
        "ZQBET": {"price": 0.0003, "last_fetched": "2026-11-07 14:58:00 ET",
                  "source": "data_broker.market_quote:get_best_quote:yfinance"},
        "ZQCAP": {"price": 20.0, "last_fetched": "2026-11-07 14:58:00 ET"},   # pre-stamp row, kept
    }))
    got = pp.finviz_cache(cache)
    assert set(got) == {"ZQALP", "ZQCAP"}
    assert got["ZQALP"]["source"] == "finviz_elite" and got["ZQCAP"]["source"] is None


def test_a_row_the_cache_labelled_itself_is_not_evidence_of_a_finviz_mark(tmp_path):
    """Observed live 2026-11-07: SRNE held 0.0003 labelled `…get_best_quote:yfinance` at 00:15 ET and
    `finviz_quote_cache` at 00:45 ET. get_price_batch overlays the cache row and the repricer writes that label
    back, so the provider is gone. Matching "finviz" in the name would resurrect exactly the value the rule bars."""
    import json

    from lib import portfolio_positions as pp

    cache = tmp_path / "finviz_quote_cache.json"
    cache.write_text(json.dumps({
        "ZQSRNE": {"price": 0.0003, "last_fetched": "2026-11-07 00:45:02 ET", "source": "finviz_quote_cache"},
        "ZQAMX": {"price": 79.07, "last_fetched": "2026-11-07 00:45:02 ET", "source": "finviz_quote_cache"},
        "ZQALP": {"price": 10.0, "last_fetched": "2026-11-07 00:45:02 ET", "source": "finviz_elite"},
    }))
    got = pp.finviz_cache(cache)
    assert set(got) == {"ZQALP"}
    # and the dropped row does not come back through resolve_mark: the stored mark serves, labelled stale
    mark = pp.resolve_mark({"symbol": "ZQSRNE", "canonical_mark": 0.2954,
                            "canonical_mark_ingested_at": _iso(300)},
                           finviz=got.get("ZQSRNE"), now=NOW)
    assert mark["price"] == 0.2954 and mark["source"] == "stored_mark" and mark["stale"] is True


# ── stop_lifecycle_monitor: the map, the record, the persisted evidence ────

def test_the_holdings_map_keys_by_account_and_symbol_with_evidence():
    hmap = slm._holdings_map(document=DOC, finviz=FINVIZ, quotes=QUOTES, now=NOW)
    alp = hmap[("schwab_fixture", "ZQALP")]
    assert alp["price"] == 42.50 and alp["price_source"] == "finviz"
    assert set(sap.MARK_FIELDS) <= set(alp)
    assert alp["broker_shares"] == 100


def test_a_stop_record_carries_the_mark_evidence_it_was_classified_with():
    held = {"shares": 100.0, "broker_shares": 100.0, "price": 42.50, "price_source": "finviz",
            "price_as_of": _iso(2), "price_age_s": 120, "price_stale": False}
    stop = {"symbol": "ZQALP", "account": "schwab_fixture", "broker": "schwab", "order_id": "synthetic-1",
            "order_type": "STOP", "status": "working", "stop_price": 42.4, "qty": 100.0}
    rec = slm._classify(stop, held)
    assert rec["current_price"] == 42.50 and rec["price_source"] == "finviz"
    assert rec["price_as_of"] == _iso(2) and rec["price_stale"] is False
    assert rec["proximity_pct"] == round((42.5 - 42.4) / 42.5 * 100, 2)


def test_the_alpaca_paper_mark_is_labelled_as_a_live_broker_read(monkeypatch):
    import types

    fake = types.ModuleType("alpaca_paper_reconciler")
    fake.get_env = lambda: {}
    fake.get_alpaca_positions = lambda env: [{"symbol": "ZQALP", "qty": "3", "current_price": "42.5"}]
    monkeypatch.setitem(sys.modules, "alpaca_paper_reconciler", fake)
    got = slm._alpaca_positions_map()[("tradeai_automated", "ZQALP")]
    assert got["price"] == 42.5 and got["price_source"] == "alpaca_paper_position"
    assert got["price_stale"] is False and got["price_as_of"]


# ── stop_drift_alert: the map, the evidence, the messages ─────────────────

def test_the_drift_map_keeps_basis_and_carries_evidence():
    doc = {"holdings": [{"symbol": "ZQCAP", "account": "schwab_fixture", "shares": 10, "cost_basis": 400.0,
                         "canonical_mark": 50.0, "canonical_mark_ingested_at": _iso(300)}]}
    m = sda._live_holdings_map(document=doc, finviz={}, quotes={}, now=NOW)
    cap = m["ZQCAP"]
    assert cap["price"] == 50.0 and cap["basis_ps"] == 40.0
    assert cap["price_source"] == "stored_mark" and cap["price_stale"] is True


def test_an_alert_with_no_live_mark_falls_back_to_a_labelled_advisory_price():
    fresh = sda._hold_evidence({}, 40.0, _iso(10))
    assert fresh["price_source"] == "advisory_snapshot" and fresh["price_stale"] is False
    old = sda._hold_evidence({}, 40.0, _iso(60 * 24 * 3))
    assert old["price_source"] == "advisory_snapshot" and old["price_stale"] is True
    undated = sda._hold_evidence({}, 40.0, None)
    assert undated["price_stale"] is True and undated["price_as_of"] is None


def _lockin(**kw):
    d = {"symbol": "ZQALP", "price": 42.5, "price_source": "finviz", "price_as_of": _iso(2),
         "price_age_s": 120, "price_stale": False, "live_fixed_stop": 40.0, "trail_pct": 5.0,
         "trailing_floor": 40.38, "gain_above_fixed_pct": 0.9, "account": "schwab_fixture"}
    d.update(kw)
    return d


def test_every_drift_message_names_the_price_source_and_as_of():
    for msg in (sda._lockin_message(_lockin(), "Schwab API · 2FA"),
                sda._drift_message({"symbol": "ZQALP", "advised_stop": 41.0, "raise_by": 1.0, "live_stop": 40.0,
                                    "raise_pct": 2.4, "price": 42.5, "price_source": "finviz",
                                    "price_as_of": _iso(2), "price_age_s": 120, "price_stale": False}),
                sda._trail_message({"symbol": "ZQALP", "pnl_pct": 9.5, "threshold_pct": 9.0, "live_fixed_stop": 40.0,
                                    "trail_pct": 6.0, "price": 42.5, "price_source": "finviz",
                                    "price_as_of": _iso(2), "price_age_s": 120, "price_stale": False},
                                   "Schwab API · 2FA")):
        assert "mark $42.50 (finviz, as of " in msg, msg


def test_a_stale_mark_in_a_message_is_labelled_stale():
    msg = sda._lockin_message(_lockin(price_stale=True, price_source="stored_mark",
                                      price_age_s=10800, price_as_of=_iso(180)), "Schwab API · 2FA")
    assert "STALE" in msg and "not live" in msg and "stored_mark" in msg


# ── stop_health_check: the alert line and the SIEM payload ────────────────

def _run_health(monkeypatch, alerts):
    payloads, sent = [], []

    class _SLM:
        @staticmethod
        def scan(persist=True):
            return {"summary": {"total": len(alerts), "by_health": "alert"}, "alerts": alerts}

    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor", _SLM)
    monkeypatch.setattr(shc, "_recently_alerted", lambda sym, cond, hours=2: False)
    monkeypatch.setattr(shc, "_siem", lambda sym, sev, line, payload: payloads.append((line, payload)))
    monkeypatch.setattr(shc, "_hermes_finding", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_send_telegram", lambda m, **k: sent.append(m) or True)
    monkeypatch.setattr(shc, "_portfolio_drawdown_guard", lambda: None)
    monkeypatch.setattr(shc, "_log_health_event", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_pl_if_fired", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_recover_current_scan", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(shc, "_last_known_blind_alerts", lambda *a, **k: {})
    monkeypatch.setattr(shc, "_schwab_unavailable_alert", lambda *a, **k: None)
    shc.run(quiet=True)
    return payloads, sent


def _alert(**kw):
    a = {"symbol": "ZQALP", "account": "schwab_fixture", "broker": "schwab", "order_id": "synthetic-1",
         "flags": ["near_trigger"], "qty": 100, "held_qty": 100, "stop_price": 42.4, "proximity_pct": 0.24,
         "lifecycle": "near_trigger", "health": "alert", "order_type": "STOP", "current_price": 42.5,
         "coverage": "full", "price_source": "finviz", "price_as_of": _iso(2), "price_age_s": 120,
         "price_stale": False}
    a.update(kw)
    return a


def test_the_stop_health_alert_carries_price_source_and_as_of(monkeypatch):
    payloads, sent = _run_health(monkeypatch, [_alert()])
    assert len(payloads) == 1
    line, payload = payloads[0]
    assert payload["price_source"] == "finviz" and payload["price_as_of"] == _iso(2)
    assert payload["price_stale"] is False
    assert "mark $42.50 (finviz, as of " in line and "STALE" not in line
    assert "finviz" in sent[0]


def test_a_stale_stop_health_mark_is_labelled_and_never_shown_live(monkeypatch):
    a = _alert(price_source="stored_mark", price_as_of=_iso(300), price_age_s=18000, price_stale=True)
    payloads, _ = _run_health(monkeypatch, [a])
    line, payload = payloads[0]
    assert payload["price_stale"] is True
    assert "STALE" in line and "not live" in line and "stored_mark" in line


def test_an_alert_with_no_mark_says_unknown(monkeypatch):
    a = _alert(current_price=None, price_source=None, price_as_of=None, price_age_s=None, price_stale=None)
    payloads, _ = _run_health(monkeypatch, [a])
    line, payload = payloads[0]
    assert payload["price_source"] is None and payload["price_stale"] is None
    assert "mark UNKNOWN" in line
