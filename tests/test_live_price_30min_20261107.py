"""The operator live-price rule (2026-11-07): a current price is at most 30 minutes old.

Operator, verbatim: "a live price comes from Finviz (finviz_quote_cache.json, fresh = last_fetched <= 30 min);
if Finviz is down or stale, a fresh Schwab / Alpaca / moomoo quote; never yfinance, never a stored DB price
older than 30 min."

LQ-20261107-13 named two consumers that published a days-old mark as the current price:
  * `scripts/lib/cio_ask_research.py::_src_price` asked for `max_age_hours=96, skip_live=True`, so a
    four-day-old `market_quotes` row became "SYM last price …" in the research prose.
  * `scripts/recovery_watch_daily.py` priced every stop-out and every re-entry review from the holdings.json
    `price` copy (or a `technical_snapshot` price), with no age at all.

Both now go through the shared helper (`lib.portfolio_positions.resolve_mark` /
`get_price_batch`), and both say "unknown" rather than a stale number. Synthetic symbols and prices only:
the repository is public.

ANCHOR: LIVE_PRICE_30MIN_20261107
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from lib import portfolio_positions as pp  # noqa: E402
import lib.data_broker.market_quote as mq  # noqa: E402
import recovery_watch_daily as rwd  # noqa: E402
from scripts.lib import cio_ask_research as car  # noqa: E402

ET = ZoneInfo("America/New_York")
ENT = car.Entity(label="NVDA", kind="listed", symbol="NVDA", security_guid="sec-nvda-0001")


def _et(when: datetime) -> str:
    """The Finviz cache's own timestamp spelling ("2026-11-07 01:15:01 ET")."""
    return when.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S ET")


def _seed(tmp_path: Path, monkeypatch, *, holdings: list[dict], cache: dict) -> Path:
    """A throw-away position store + Finviz cache, both where the helpers look for them."""
    from lib import persistent_overlay

    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    (tmp_path / "PERSISTENT_STATE_ROOT.json").write_text("{}", encoding="utf-8")
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True, exist_ok=True)
    if holdings is not None:
        (state / "holdings.json").write_text(
            json.dumps({"generated_at": _et(datetime.now(timezone.utc)), "holdings": holdings}), encoding="utf-8")
    if cache is not None:
        (state / "finviz_quote_cache.json").write_text(json.dumps(cache), encoding="utf-8")
    assert pp.store_path() == state / "holdings.json", (pp.store_path(), persistent_overlay.overlay_data_source())
    pp._FV_MEMO.clear()
    return state


# ── recovery_watch_daily: the price map every stop-out decision reads ──────────────────────────────────


def test_recovery_watch_prices_from_a_fresh_finviz_fetch(tmp_path, monkeypatch):
    """A 5-minute-old Finviz row wins over the holdings.json `price` copy and the stored canonical mark."""
    now = datetime.now(timezone.utc)
    _seed(tmp_path, monkeypatch,
          holdings=[{"symbol": "NVDA", "shares": 10.0, "account": "schwab_taxable", "price": 100.0,
                     "canonical_mark": 100.0, "canonical_mark_ingested_at": "2026-01-02T00:00:00+00:00"}],
          cache={"NVDA": {"price": 182.5, "last_fetched": _et(now - timedelta(minutes=5)),
                          "last_updated": _et(now - timedelta(minutes=5))}})

    prices, status = rwd._live_prices(["NVDA"])

    assert status == "ok"
    row = prices["NVDA"]
    assert row["price"] == pytest.approx(182.5)
    assert row["price_source"] == "finviz"
    assert row["price_stale"] is False
    assert row["shares"] == 10.0


def test_recovery_watch_refuses_a_four_day_old_mark(tmp_path, monkeypatch):
    """THE defect: a 4-day-old stored canonical mark used to be reported as the current price.

    Both the Finviz row and the stored mark are old, so the honest answer is "unknown" (price None), never
    the stored 100.00 — and the caller's own `current_price > 0` guards then leave the event for review.
    """
    now = datetime.now(timezone.utc)
    _seed(tmp_path, monkeypatch,
          holdings=[{"symbol": "NVDA", "shares": 10.0, "account": "schwab_taxable", "price": 100.0,
                     "canonical_mark": 100.0, "canonical_mark_ingested_at": "2026-01-02T00:00:00+00:00"}],
          cache={"NVDA": {"price": 182.5, "last_fetched": _et(now - timedelta(days=4)),
                          "last_updated": _et(now - timedelta(days=4))}})

    prices, status = rwd._live_prices(["NVDA"])

    assert status == "ok"
    assert prices["NVDA"]["price"] is None
    assert prices["NVDA"]["price_stale"] is True
    assert prices["NVDA"]["price_as_of"] is not None          # the age is reported, not hidden


def test_recovery_watch_resolves_a_symbol_it_no_longer_holds(tmp_path, monkeypatch):
    """A stopped-out name under review is not in the position store; it still gets the 30-minute rule."""
    now = datetime.now(timezone.utc)
    _seed(tmp_path, monkeypatch, holdings=[],
          cache={"PFE": {"price": 29.39, "last_fetched": _et(now - timedelta(minutes=12))}})

    prices, _ = rwd._live_prices(["PFE"])

    assert prices["PFE"]["price"] == pytest.approx(29.39)
    assert prices["PFE"]["shares"] == 0
    assert prices["PFE"]["price_stale"] is False


def test_recovery_watch_fails_closed_without_a_store(tmp_path, monkeypatch):
    """No store is "absent", not "no positions": every price is unknown, none is invented."""
    _seed(tmp_path, monkeypatch, holdings=None, cache=None)

    prices, status = rwd._live_prices(["NVDA"])

    assert status == "absent"
    assert prices == {}


def test_recovery_watch_prices_a_position_only_the_database_knows(tmp_path, monkeypatch):
    """Holdings are DB-first (`lib.holdings_document.load_document`): a position added since the last
    holdings.json export must be priced, not silently skipped because the file is behind."""
    now = datetime.now(timezone.utc)
    _seed(tmp_path, monkeypatch, holdings=[],          # the export has not caught up
          cache={"PFE": {"price": 29.39, "last_fetched": _et(now - timedelta(minutes=3))}})
    from lib import holdings_document

    monkeypatch.setattr(holdings_document, "load_document", lambda *a, **k: {
        "holdings": [{"symbol": "PFE", "shares": 25.0, "account": "schwab_ira"}],
        "document_source": "database", "document_fallback_reason": None})

    prices, status = rwd._live_prices(["PFE"])

    assert status == "ok"
    assert prices["PFE"]["price"] == pytest.approx(29.39)
    assert prices["PFE"]["shares"] == 25.0
    assert prices["PFE"]["account"] == "schwab_ira"


def test_recovery_watch_says_why_the_document_fell_back_to_the_file(tmp_path, monkeypatch):
    """A database-failure fallback is reported as such, and the file's own read state still decides
    whether the book is missing, empty or unreadable."""
    _seed(tmp_path, monkeypatch, holdings=None, cache=None)
    from lib import holdings_document

    monkeypatch.setattr(holdings_document, "load_document", lambda *a, **k: {
        "holdings": [], "document_source": "file",
        "document_fallback_reason": "database unreachable: connection refused",
        "document_store_state": "absent"})

    prices, status = rwd._live_prices(["NVDA"])

    assert status == "absent"
    assert prices == {}


def test_recovery_watch_exit_price_falls_back_to_the_trigger_capture_only():
    """The stop-out writer labels where its exit price came from (live mark, trigger capture, or nothing).

    The record keeps the trigger-time price for `exit_price` (historical by definition) while `current_price`
    stays 0 so the classifier cannot call a days-old number a breach.
    """
    src = (ROOT / "scripts" / "recovery_watch_daily.py").read_text(encoding="utf-8")
    assert '"exit_price_source": "live_mark" if fresh_price' in src
    assert 'fresh_price = live.get("price") or 0' in src
    assert 'pos.get("price", 0)' not in src.split("def _live_prices")[1].split("def detect_new_stopouts")[0]


# ── the shared helper's own contract: Finviz overlay, ISO as_of, 30-minute window ─────────────────────


def test_get_price_batch_overlay_serves_a_fresh_finviz_row(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _seed(tmp_path, monkeypatch, holdings=[],
          cache={"NVDA": {"price": 182.5, "last_fetched": _et(now - timedelta(minutes=5))}})

    out = mq.get_price_batch(lambda *a, **k: [], ["NVDA"], max_age_hours=0.5, skip_live=True)

    assert out["NVDA"]["price"] == pytest.approx(182.5)
    assert out["NVDA"]["source"] == "finviz_quote_cache"


def test_get_price_batch_overlay_as_of_is_iso_not_the_caches_et_spelling(tmp_path, monkeypatch):
    """The cache says "2026-11-07 01:30:01 ET". Handing that straight to a consumer loses the fact:
    CIO ask research's make_fact raised "fact without as_of" on the first live run (2026-11-07)."""
    now = datetime.now(timezone.utc)
    _seed(tmp_path, monkeypatch, holdings=[],
          cache={"NVDA": {"price": 182.5, "last_fetched": _et(now - timedelta(minutes=5))}})

    out = mq.get_price_batch(lambda *a, **k: [], ["NVDA"], max_age_hours=0.5, skip_live=True)

    assert " ET" not in out["NVDA"]["as_of"]
    parsed = datetime.fromisoformat(out["NVDA"]["as_of"])
    assert abs((now - parsed).total_seconds() - 300) < 180


def test_get_price_batch_overlay_never_serves_an_old_finviz_row(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _seed(tmp_path, monkeypatch, holdings=[],
          cache={"NVDA": {"price": 182.5, "last_fetched": _et(now - timedelta(hours=8))}})

    out = mq.get_price_batch(lambda *a, **k: [], ["NVDA"], max_age_hours=0.5, skip_live=True)

    assert "NVDA" not in out


# ── CIO ask research: the price fact the research prose quotes ─────────────────────────────────────────


def _fake_batch(monkeypatch, payload: dict, calls: dict):
    def fake(db_query, symbols, max_age_hours=12, *, skip_live=False, **kw):
        calls.update(symbols=list(symbols), max_age_hours=max_age_hours, skip_live=skip_live)
        return payload

    monkeypatch.setattr(mq, "get_price_batch", fake)


def test_cio_ask_price_is_asked_for_a_thirty_minute_window(monkeypatch):
    """The whole defect in one assertion: 96 h -> 0.5 h, and the broker backup is no longer skipped."""
    calls: dict = {}
    _fake_batch(monkeypatch, {"NVDA": {"price": 182.5, "as_of": "2026-11-07T06:20:00+00:00",
                                       "source": "finviz_quote_cache"}}, calls)

    facts = car._src_price(ENT, car.ResearchContext(question="q"))

    assert calls["max_age_hours"] == 0.5
    assert calls["skip_live"] is False
    assert calls["symbols"] == ["NVDA"]
    assert len(facts) == 1
    assert facts[0].value == pytest.approx(182.5)
    assert facts[0].field == "last_price"
    assert facts[0].citation["source"] == "finviz_quote_cache"
    assert facts[0].citation["freshness_rule"] == "live_price_le_30min"
    assert facts[0].as_of.startswith("2026-11-07T06:20:00")   # make_fact normalizes the offset spelling


def test_cio_ask_price_without_a_fresh_quote_publishes_no_fact(monkeypatch):
    """No fresh price -> no fact. The prose then says nothing, instead of quoting a four-day-old row."""
    calls: dict = {}
    _fake_batch(monkeypatch, {}, calls)

    assert car._src_price(ENT, car.ResearchContext(question="q")) == []


def test_cio_ask_price_refuses_a_yfinance_answer(monkeypatch):
    """The waterfall's yfinance arm is not an operator-named provider, so its answer is not a price."""
    calls: dict = {}
    _fake_batch(monkeypatch, {"NVDA": {"price": 182.5, "as_of": "2026-11-07T06:20:00+00:00",
                                       "source": "data_broker.market_quote:get_best_quote:yfinance"}}, calls)

    assert car._src_price(ENT, car.ResearchContext(question="q")) == []


def test_cio_ask_price_refuses_a_blank_price(monkeypatch):
    calls: dict = {}
    _fake_batch(monkeypatch, {"NVDA": {"price": None, "as_of": "2026-11-07T06:20:00+00:00",
                                       "source": "market_quotes"}}, calls)

    assert car._src_price(ENT, car.ResearchContext(question="q")) == []
