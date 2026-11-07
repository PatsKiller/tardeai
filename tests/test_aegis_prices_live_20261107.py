"""ANCHOR: AEGIS_PRICES_LIVE_20261107 — Aegis prices are live marks, and say where they came from.

LQ-20261107-05 [P0]. Two Aegis surfaces priced a holding from a STORED value and presented it as the current
price:

* ``scripts/aegis_synthesis.py::_resolve_price`` rung 1 was the holdings row's ``price`` — a copy the holdings
  build derives from the morning positions run, which lags the repricer all day (data-truth audit 2026-11-07:
  24 of 30 holdings shown at a stale price);
* ``scripts/aegis_evening_packet.py::_holdings_protection`` read ``holdings.json`` directly and used
  ``h["price"]`` or ``h["current_price"]`` for the near-stop distances.

The operator price rule (2026-11-07): a live price comes from Finviz (cache entry at most 30 minutes old); if
Finviz is down or stale, a FRESH Schwab/Alpaca/moomoo quote from the data broker; never yfinance, never a
stored DB price older than 30 minutes. A stored mark is a last resort and must be labelled STALE.

Pinned here:

  1. a fresh Finviz entry beats a stored holdings price — the old order returned the stored one;
  2. a stale Finviz entry drops to a fresh broker quote, and both the source and the as-of travel with the price;
  3. with neither fresh, the stored mark is returned flagged ``stale`` (never presented as live);
  4. the evening packet reads its document DB-first and its near-stop rows carry source, as-of and the stale flag.

Hermetic: synthetic symbols, prices and cache rows under ``tmp_path``; no DB, no network, no real ticker.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import aegis_evening_packet as pkt  # noqa: E402
import aegis_synthesis as synth  # noqa: E402

NOW = datetime.now(timezone.utc)
SYM = "TESTX"
STALE_WINDOW_S = 30 * 60


def _iso(delta_s: int) -> str:
    return (NOW + timedelta(seconds=delta_s)).isoformat()


# ── aegis_synthesis._resolve_price ──────────────────────────────────────────────────────────────────

def test_a_fresh_finviz_mark_beats_the_stored_holdings_price():
    """The old ladder returned the holdings row's `price` first, whatever Finviz said."""
    holdings = {SYM: [{"symbol": SYM, "price": 50.00, "price_as_of": _iso(-6 * 3600)}]}
    price, source, valid, as_of, stale = synth._resolve_price(
        SYM, holdings, {SYM: {"price": 55.00, "as_of": _iso(-60), "source": "finviz"}}, 0)
    assert (price, source, valid) == (55.00, "finviz", True)
    assert as_of == _iso(-60) and stale is False


def test_a_stale_finviz_row_drops_to_a_fresh_broker_quote_with_its_source_and_as_of():
    price, source, valid, as_of, stale = synth._resolve_price(
        SYM, {}, {SYM: {"price": 55.00, "as_of": _iso(-2 * 3600), "source": "finviz"}},
        0, {"price": 56.25, "as_of": _iso(-120), "source": "schwab"})
    assert (price, source, valid) == (56.25, "data_broker:schwab", True)
    assert as_of == _iso(-120) and stale is False


def test_with_nothing_fresh_the_stored_mark_is_flagged_stale():
    """A stored price may still be shown — but never as a live one."""
    price, source, valid, as_of, stale = synth._resolve_price(
        SYM, {SYM: [{"symbol": SYM, "price": 50.00, "price_as_of": _iso(-8 * 3600)}]}, {}, 0)
    assert (price, source, valid, stale) == (50.00, "stored_mark", True, True)
    assert as_of == _iso(-8 * 3600)          # the row's own quote time, carried out


def test_an_undated_stored_mark_is_stale_too():
    price, source, valid, as_of, stale = synth._resolve_price(SYM, {SYM: [{"symbol": SYM, "price": 50.0}]}, {}, 0)
    assert (price, source, valid, as_of, stale) == (50.0, "stored_mark", True, None, True)


def test_nothing_at_all_is_unavailable_not_zero_dressed_as_a_price():
    price, source, valid, as_of, stale = synth._resolve_price(SYM, {}, {}, 0)
    assert (price, source, valid) == (0, "none", False)
    assert as_of is None and stale is True


def test_the_risk_management_price_is_a_last_resort_and_is_not_live():
    _price, source, valid, _as_of, stale = synth._resolve_price(SYM, {}, {}, 42.5)
    assert source == "stored_mark" and valid is True and stale is True


# ── aegis_evening_packet._holdings_protection ──────────────────────────────────────────────────────

def _store(tmp_path, rows):
    store = tmp_path / "data" / "portfolios" / "state" / "holdings.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"as_of": "2026-11-07T12:00:00Z", "holdings": rows,
                                 "portfolio_totals": {"total_value": 1000.0}}))
    return store


def _finviz(store, entries):
    # nosemgrep: tq-py-nonatomic-store-write -- pytest tmp_path fixture, not a store
    (store.parent / "finviz_quote_cache.json").write_text(json.dumps(entries))


def test_the_packet_prices_a_near_stop_holding_from_finviz_not_the_stored_price(tmp_path, monkeypatch):
    monkeypatch.setattr(pkt, "ROOT", tmp_path)
    store = _store(tmp_path, [{"symbol": SYM, "account": "TEST-ACCOUNT", "price": 50.00, "stop": 51.00}])
    _finviz(store, {SYM: {"price": 52.00, "last_fetched": _iso(-90), "source": "finviz"}})

    hp = pkt._holdings_protection()

    assert hp["stale_prices"] == 0
    assert hp["document_source"]                       # the packet says which document it read
    [row] = hp["near_stop"]
    assert row["price"] == 52.00                      # not the stored 50.00
    assert row["price_source"] == "finviz"
    assert row["price_as_of"] == _iso(-90).replace("+00:00", "Z")   # the cache row's own fetch time, carried out
    assert row["price_stale"] is False
    assert row["account"] == "TEST-ACCOUNT"
    assert row["distance_pct"] == round(abs(52.00 - 51.00) / 52.00 * 100, 2)


def test_the_packet_labels_a_stored_price_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(pkt, "ROOT", tmp_path)
    store = _store(tmp_path, [{"symbol": SYM, "account": "TEST-ACCOUNT", "price": 50.00,
                               "price_as_of": _iso(-9 * 3600), "stop": 51.00}])

    hp = pkt._holdings_protection()

    assert hp["stale_prices"] == 1
    [row] = hp["near_stop"]
    assert row["price"] == 50.00 and row["price_source"] == "stored_mark" and row["price_stale"] is True


def test_the_packet_states_its_price_basis(tmp_path, monkeypatch):
    monkeypatch.setattr(pkt, "ROOT", tmp_path)
    _store(tmp_path, [])
    hp = pkt._holdings_protection()
    assert "Finviz" in hp["price_basis"] and "30 min" in hp["price_basis"]
    assert "STALE" in hp["price_basis"]


def test_the_packet_reads_the_document_db_first_and_reports_a_fallback(tmp_path, monkeypatch):
    """load_document is the reader; its source and fallback reason reach the packet."""
    monkeypatch.setattr(pkt, "ROOT", tmp_path)
    store = _store(tmp_path, [{"symbol": SYM, "price": 50.00, "stop": 60.00}])
    seen = {}

    def fake_load_document(path=None, **_kw):
        seen["store"] = Path(path)
        return {"holdings": json.loads(store.read_text())["holdings"], "document_source": "database",
                "document_fallback_reason": None}

    import lib.holdings_document as hd
    monkeypatch.setattr(hd, "load_document", fake_load_document)

    hp = pkt._holdings_protection()

    assert seen["store"] == store
    assert hp["document_source"] == "database" and hp["document_fallback_reason"] is None
