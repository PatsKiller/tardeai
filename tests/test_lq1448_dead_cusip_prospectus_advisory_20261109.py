"""ANCHOR: LQ1448_DEAD_CUSIP_PROSPECTUS_ADVISORY_20261109

Dead CUSIP holdings must not appear on /api/v2/prospectus/index or
/api/v3/advisory (page walk 02:20 items 150/151). Same predicate as LQ-1417:
``security_identity.is_dead_cusip_holding``. Synthetic fixtures only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DEAD = "000000AA0"
PRICED = "000000BB1"
TICKER = "ZZZT"
NOW = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)


def _holdings_book() -> list[dict]:
    return [
        {"symbol": TICKER, "account": "acct-a", "current_price": 10.0, "market_value": 50.0, "shares": 5},
        {"symbol": DEAD, "account": "acct-a", "current_price": 0.0, "market_value": 0.0, "shares": 7},
        {"symbol": PRICED, "account": "acct-a", "current_price": 12.5, "market_value": 100.0, "shares": 8},
    ]


def test_fail_before_unfiltered_index_and_rows_still_list_the_dead_cusip():
    """Documents the defect shape: without the filter helpers, dead CUSIPs stay."""
    items = [
        {"symbol": TICKER, "status": "ready"},
        {"symbol": DEAD, "status": "ready"},
        {"symbol": PRICED, "status": "ready"},
    ]
    rows = [
        {"symbol": TICKER, "current_price": 10.0, "market_value": 50.0},
        {"symbol": DEAD, "current_price": 0.0, "market_value": 0.0},
        {"symbol": PRICED, "current_price": 12.5, "market_value": 100.0},
    ]
    assert DEAD in [i["symbol"] for i in items]
    assert DEAD in [r["symbol"] for r in rows]


def test_prospectus_index_helper_drops_only_the_unpriced_cusip():
    from scripts.lib.prospectus_api import without_dead_cusip_index_items

    items = [
        {"symbol": TICKER, "status": "ready"},
        {"symbol": DEAD, "status": "ready"},
        {"symbol": PRICED, "status": "ready"},
    ]
    out = without_dead_cusip_index_items(items, _holdings_book())
    assert [i["symbol"] for i in out] == [TICKER, PRICED]


def test_prospectus_index_keeps_symbol_when_any_account_row_is_priced():
    """LQ-1458 / REVIEW-1454: one dead zero row must not hide a priced row of the same symbol."""
    from scripts.lib.prospectus_api import dead_cusip_symbols, without_dead_cusip_index_items

    from scripts.lib.security_identity import is_dead_cusip_holding

    mixed = [
        {"symbol": PRICED, "account": "a", "current_price": 0.0, "market_value": 0.0, "shares": 1},
        {"symbol": PRICED, "account": "b", "current_price": 12.5, "market_value": 40.0, "shares": 3.2},
        {"symbol": DEAD, "account": "a", "current_price": 0.0, "market_value": 0.0, "shares": 7},
        {"symbol": TICKER, "account": "a", "current_price": 10.0, "market_value": 50.0, "shares": 5},
    ]
    # Fail-before shape of the old any-row rule: one zero row condemned the symbol.
    any_row_dead = {str(r["symbol"]).upper() for r in mixed if is_dead_cusip_holding(r)}
    assert PRICED in any_row_dead and DEAD in any_row_dead

    assert PRICED not in dead_cusip_symbols(mixed)
    assert DEAD in dead_cusip_symbols(mixed)
    items = [
        {"symbol": TICKER, "status": "ready"},
        {"symbol": DEAD, "status": "ready"},
        {"symbol": PRICED, "status": "ready"},
    ]
    out = without_dead_cusip_index_items(items, mixed)
    assert [i["symbol"] for i in out] == [TICKER, PRICED]


def test_prospectus_index_payload_hides_dead_cusip_when_holdings_present(tmp_path: Path):
    from scripts.lib import prospectus_api as api
    from scripts.lib.prospectus import load_config, store

    base = store.base_dir(tmp_path, load_config())
    store.write_universe(
        base,
        [
            {"symbol": TICKER, "scope": "holding", "premium": True},
            {"symbol": DEAD, "scope": "holding", "premium": False},
            {"symbol": PRICED, "scope": "holding", "premium": False},
        ],
    )
    for sym, name in ((TICKER, "Zeta"), (DEAD, "Dead"), (PRICED, "Priced")):
        store.update_index(
            base, sym, name=name, scope="holding", version="20261109T000000Z",
            generated_at="20261109T000000Z", model="synthetic", status="ready",
            next_due="2099-01-01T00:00:00+00:00",
        )
    hold_path = tmp_path / "data" / "portfolios" / "state" / "holdings.json"
    hold_path.parent.mkdir(parents=True, exist_ok=True)
    hold_path.write_text(  # nosemgrep: tq-py-nonatomic-store-write -- synthetic fixture under pytest tmp_path
        json.dumps({"holdings": _holdings_book()}), encoding="utf-8"
    )

    # Fail-before shape on the same fixture: raw universe still lists DEAD.
    assert DEAD in {r["symbol"] for r in store.read_universe(base)}

    out = api.index_payload(tmp_path, now=NOW)
    syms = [i["symbol"] for i in out["items"]]
    assert DEAD not in syms
    assert TICKER in syms
    assert PRICED in syms
    assert out["totals"]["ready"] == 2


def test_advisory_row_helper_drops_only_the_unpriced_cusip():
    from scripts.api_v3_advisory import without_dead_cusip_advisory_rows

    rows = [
        {"symbol": TICKER, "current_price": 10.0, "market_value": 50.0},
        {"symbol": DEAD, "current_price": 0.0, "market_value": 0.0},
        {"symbol": PRICED, "price": 12.5, "market_value": 100.0},  # price-only field
    ]
    out = without_dead_cusip_advisory_rows(rows)
    assert [r["symbol"] for r in out] == [TICKER, PRICED]


def test_advisory_desk_load_holdings_skips_dead_cusip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.lib.data_broker import advisory_desk as desk

    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(  # nosemgrep: tq-py-nonatomic-store-write -- synthetic fixture under pytest tmp_path
        json.dumps({
            "as_of": "2026-11-09T00:00:00+00:00",
            "portfolio_totals": {"total_value": 150.0, "cash_weight_pct": 0.0},
            "holdings": _holdings_book(),
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(desk, "STATE_DIR", state)
    monkeypatch.setattr(desk, "PROJECT_ROOT", tmp_path)

    loaded = desk._load_holdings()
    syms = [p["symbol"] for p in loaded["positions"]]
    assert DEAD not in syms
    assert TICKER in syms
    assert PRICED in syms


def test_house_sources_holdings_skips_dead_cusip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """prospectus-build writer: HouseSources.holdings must not plan dead CUSIPs."""
    from scripts.lib.prospectus import inputs as pin

    book = {
        "holdings": [
            {"symbol": TICKER, "shares": 5, "current_price": 10.0, "market_value": 50.0, "is_cash": False},
            {"symbol": DEAD, "shares": 7, "current_price": 0.0, "market_value": 0.0, "is_cash": False},
            {"symbol": PRICED, "shares": 8, "current_price": 12.5, "market_value": 100.0, "is_cash": False},
        ]
    }

    class _PP:
        @staticmethod
        def load_store():
            return book

        @staticmethod
        def is_cash(r):
            return bool(r.get("is_cash"))

    class _PC:
        @staticmethod
        def get_positions_context(_db, syms):
            return {s: {"market_value": 1.0} for s in syms}

    src = pin.HouseSources(tmp_path, db_query=lambda *a, **k: None, read_only=True)
    monkeypatch.setattr(
        pin, "_plib",
        lambda name: _PP if name == "portfolio_positions" else (_ for _ in ()).throw(ImportError(name)),
    )
    monkeypatch.setattr(
        src, "_lib",
        lambda name: _PC if name == "positions_context" else (_ for _ in ()).throw(ImportError(name)),
    )

    held = src.holdings()
    assert DEAD not in held
    assert TICKER in held
    assert PRICED in held
