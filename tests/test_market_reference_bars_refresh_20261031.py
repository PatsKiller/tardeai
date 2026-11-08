"""Daily bars for the Market Risk Engine's reference ETFs are refreshed on purpose, not as a side effect.

Before 2026-10-31 market_ohlcv_bars daily rows were written only when an on-demand technical lookup asked for a
symbol, so SPY stopped on 2026-10-09 and QQQ/SMH had none (builder H's audit, PR #2341). These tests pin the
fetch window arithmetic, that a dry run never writes, that --apply writes through the store function it is given,
and that a symbol the provider returns nothing for is named and fails the run. No network, no DB.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_reference_bars_refresh as mrb  # noqa: E402


class _Cur:
    def __init__(self, last):
        self.last = last

    def execute(self, sql, params=None):
        assert sql.lstrip().upper().startswith("SELECT")  # the lane only reads through its own cursor

    def fetchall(self):
        return list(self.last.items())


class _Conn:
    def __init__(self, last):
        self.last = last

    def cursor(self):
        return _Cur(self.last)


def _bars(sym, n):
    return [
        {"symbol": sym, "timeframe": "daily", "bar_time": datetime(2026, 10, 1 + i, tzinfo=timezone.utc)}
        for i in range(n)
    ]


def test_fetch_window():
    today = date(2026, 10, 31)
    assert mrb.fetch_days(date(2026, 10, 9), today, None) == 25  # from the last stored bar
    assert mrb.fetch_days(date(2026, 10, 30), today, None) == mrb.INCREMENTAL_MIN_DAYS
    assert mrb.fetch_days(None, today, None) == mrb.fetch_days(date(2026, 10, 30), today, 400)  # never had bars
    assert mrb.fetch_days(None, today, 400) >= 400 * 365 / 252  # enough calendar days for 400 sessions


def test_dry_run_never_stores_and_apply_does(monkeypatch):
    monkeypatch.setattr(mrb, "reference_symbols", lambda: ["SPY", "QQQ"])
    stored = []

    def store(conn, bars):
        stored.extend(bars)
        return len(bars)

    fetch = lambda s, days: _bars(s, 3)  # noqa: E731
    dry = mrb.run(
        apply=False, backfill_sessions=None, conn=_Conn({}), fetch=fetch, store=store, today=date(2026, 10, 31)
    )
    assert dry["mode"] == "dry_run" and dry["stored_bars"] == 0 and stored == []
    assert dry["fetched_bars"] == 6 and dry["empty"] == []
    assert dry["source"] == "alpaca"  # the lane names the granted `bars` supply, never yfinance

    live = mrb.run(
        apply=True, backfill_sessions=None, conn=_Conn({}), fetch=fetch, store=store, today=date(2026, 10, 31)
    )
    assert live["stored_bars"] == 6 and len(stored) == 6


def test_empty_symbol_is_named(monkeypatch):
    monkeypatch.setattr(mrb, "reference_symbols", lambda: ["SPY", "UUP"])
    out = mrb.run(
        apply=False,
        backfill_sessions=None,
        conn=_Conn({"SPY": date(2026, 10, 9)}),
        fetch=lambda s, d: [] if s == "UUP" else _bars(s, 2),
        store=lambda c, b: 0,
        today=date(2026, 10, 31),
    )
    assert out["empty"] == ["UUP"]
    spy = next(r for r in out["rows"] if r["symbol"] == "SPY")
    assert spy["last_stored"] == "2026-10-09" and spy["requested_days"] == 25


def test_symbols_come_from_the_shared_config():
    syms = mrb.reference_symbols()
    for s in ("SPY", "QQQ", "SMH", "HYG", "UUP", "VIXY"):
        assert s in syms


def _n_bars(sym, n):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"symbol": sym, "timeframe": "daily", "bar_time": start + timedelta(days=i)} for i in range(n)]


class _ApplyConn(_Conn):
    def close(self):
        pass


def test_apply_receipt_counts_bars_not_symbols_and_the_contract_grades_produced(tmp_path, monkeypatch):
    """LQ-20261107-479: a run that stores every fetched bar must grade ``produced``.

    The receipt's counted unit is a bar. ``produced_count`` is bars stored, so ``attempted_count`` has to be
    bars fetched: with the symbol count there (51) against a normal run's stored bars (357) the executor's
    n8n_output_verdict returned ``unverifiable: counts_inconsistent`` and the first live fire would have
    been RUN_FAILED ``output_unverifiable``. This drives the real ``main(["--apply"])`` through the real
    receipt writer, then grades the immutable per-attempt receipt against the lane's shipped contract.
    """
    import json
    import types

    from lib import n8n_output_verdict

    per_symbol = {"SPY": 200, "QQQ": 150}
    fake = types.ModuleType("market_data_snapshot_loader")
    fake.get_conn = lambda: _ApplyConn({})
    fake.fetch_alpaca_daily_bars = lambda sym, days: _n_bars(sym, per_symbol[sym])
    fake.store_bars = lambda conn, bars: len(bars)
    monkeypatch.setitem(sys.modules, "market_data_snapshot_loader", fake)
    monkeypatch.setattr(mrb, "reference_symbols", lambda: list(per_symbol))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_RUN_ID", "lq479-test-run")
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")

    assert mrb.main(["--apply"]) == 0

    receipt = json.loads(
        (tmp_path / "data/runtime/lane_attempts/market-reference-bars/lq479-test-run.json").read_text("utf-8")
    )
    assert receipt["schema"] == "LaneRunReceipt@v2"
    assert receipt["produced_count"] == 350
    assert receipt["attempted_count"] == 350, "the attempt unit is a bar, not a symbol"

    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))["contracts"]
    rule = next(c for c in contracts if c["id"] == "market-reference-bars")["expected_output"]
    verdict = n8n_output_verdict.evaluate(
        rule, receipt, run_id="lq479-test-run", lane_id="market-reference-bars", mode="live"
    )
    assert verdict["verdict"] == "produced", verdict
