"""SINCE_CLOSE_NEW_PRINT_REBUILD_LQ1304_20261109 — a print that lands after the last build rebuilds the card.

LQ-20261107-1304 (operator 2026-11-08 19:44 ET: "no print since Friday is an error"). The operator's question is
"what printed since the close", and ``--if-changed`` must answer it with the newest print, not with whatever the
previous build happened to see. ``change_state()`` already carries the newest print per HELD name, so a held-name
print moves the signature; a WATCHLIST name's print does not, and neither does a held print whose rounded
percentage repeats. The rule added here is narrower and stronger: if the store has a print on a held/watch name
whose ``bar_end`` is newer than the snapshot's ``generated_at``, the card is out of date and is rebuilt.

The rebuild is non-material by construction (the numbers already changed; the summary is carried, no model call),
so the check lane can afford it every 15 minutes.

Hermetic: synthetic tickers and rows, no database, no network, no production state.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import since_close_card as c  # noqa: E402

ET = ZoneInfo("America/New_York")
CLOSE_DATE = "2026-11-06"  # Friday
SUNDAY = datetime(2026, 11, 8, 20, 15, tzinfo=ET)  # the Sunday overnight open, after the Friday close


def _tickers(*, held=("AAA",), watch=("WWW",)) -> dict:
    out = {"tickers": {}, "_meta": {"generated_at": "2026-11-08T20:00:00Z"}}
    for sym in held:
        out["tickers"][sym] = {
            "quote": {"price": 100.0, "change_pct": -1.0},
            "holdings_context": {"shares_total": 10, "market_value_total": 1000.0},
            "performance": {"perf_week": 0.5},
        }
    for sym in watch:
        out["tickers"][sym] = {
            "quote": {"price": 50.0, "change_pct": 0.4},
            "performance": {"perf_week": 0.1},
        }
    return out


def _row(sym: str, at: datetime, *, price: float = 100.0, pct: float | None = 1.0, session: str = "overnight") -> dict:
    return {
        "symbol": sym,
        "session": session,
        "session_date": CLOSE_DATE,
        "bar_start": at - timedelta(minutes=5),
        "bar_end": at,
        "price": price,
        "reference_close": 100.0,
        "reference_date": CLOSE_DATE,
        "reference_basis": "alpaca_sip_daily_bar_close",
        "change_pct": pct,
        "feed": "sip",
    }


def _build(now, *, prior=None, rows=(), tickers=None, llm=None):
    return c.build_snapshot(
        now=now,
        ticker_snapshot=tickers or _tickers(),
        articles=[],
        futures=None,
        llm=llm,
        prior=prior,
        if_changed=True,
        extended_rows=list(rows),
    )


# ── the helper ────────────────────────────────────────────────────────────────────────────────────────────────


def test_newest_print_since_reads_only_the_wanted_symbols_and_only_after_the_clock():
    rows = [
        _row("AAA", datetime(2026, 11, 8, 20, 0, tzinfo=ET)),
        _row("WWW", datetime(2026, 11, 8, 20, 20, tzinfo=ET)),
        _row("/ES", datetime(2026, 11, 8, 20, 25, tzinfo=ET)),  # a futures root is not a held/watch name
        _row("ZZZ", datetime(2026, 11, 8, 20, 30, tzinfo=ET)),  # not on the card at all
    ]
    hit = c.newest_print_since(rows, ["AAA", "WWW"], after=datetime(2026, 11, 8, 20, 10, tzinfo=ET))
    assert hit is not None and hit["symbol"] == "WWW"
    assert hit["bar_end"] == "2026-11-09T01:20:00Z"  # 20:20 ET Sunday
    assert hit["printed_text"] == "Sun 8:20 PM ET"
    assert hit["session_label"] == "overnight"
    # every row is at or before the clock: nothing counts as a new print
    assert c.newest_print_since(rows, ["AAA", "WWW"], after=datetime(2026, 11, 8, 20, 30, tzinfo=ET)) is None
    assert c.newest_print_since(rows, [], after=datetime(2026, 11, 8, 19, 0, tzinfo=ET)) is None


def test_newest_print_since_prefers_the_newest_bar_end_not_the_last_row():
    older = _row("AAA", datetime(2026, 11, 8, 20, 5, tzinfo=ET))
    newer = _row("AAA", datetime(2026, 11, 8, 20, 10, tzinfo=ET))
    hit = c.newest_print_since([newer, older], ["AAA"], after=datetime(2026, 11, 8, 20, 0, tzinfo=ET))
    assert hit["bar_end"] == "2026-11-09T01:10:00Z"


# ── --if-changed: the card rebuilds on a print it has not shown ──────────────────────────────────────────────


def test_a_new_print_on_a_watchlist_name_rebuilds_the_card_without_spending_a_call():
    """The gap the signature leaves: change_state() tracks held prints, not a watchlist name's."""
    first = _build(SUNDAY, rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4)],
                   llm=lambda p: "words")
    assert first is not None and first["generated_at"] == "2026-11-09T01:15:00Z"
    assert first["summary"]["text"] == "words"

    later = SUNDAY + timedelta(minutes=15)
    calls: list[str] = []
    again = _build(
        later,
        prior=first,
        rows=[
            _row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4),
            _row("WWW", datetime(2026, 11, 8, 20, 20, tzinfo=ET), price=50.6, pct=0.6),
        ],
        llm=lambda p: calls.append(p) or "words",
    )
    assert again is not None, "a print after generated_at must rebuild"
    assert again["updated"]["kind"] == "print"
    assert again["updated"]["reason"] == "new WWW print Sun 8:20 PM ET overnight"
    assert again["summary"]["source"] == "carried" and not calls, "a print changes numbers, never the words"
    watch = next(m for m in again["moves"] if m["symbol"] == "WWW")
    assert watch["extended"]["printed_at"] == "2026-11-09T01:20:00Z"


def test_a_new_print_on_a_held_name_rebuilds():
    """A held print already moves change_state()'s signature (kind 'minor'); the print rule is the fallback for the
    names the signature does not carry, and neither path spends a model call."""
    first = _build(SUNDAY, rows=[_row("AAA", datetime(2026, 11, 8, 20, 0, tzinfo=ET))], llm=lambda p: "words")
    assert first is not None and first["summary"]["text"] == "words"
    calls: list[str] = []
    again = _build(
        SUNDAY + timedelta(minutes=15),
        prior=first,
        rows=[_row("AAA", datetime(2026, 11, 8, 20, 0, tzinfo=ET)),
              _row("AAA", datetime(2026, 11, 8, 20, 20, tzinfo=ET))],
        llm=lambda p: calls.append(p) or "other words",
    )
    assert again is not None
    assert next(m for m in again["moves"] if m["symbol"] == "AAA")["extended"]["printed_at"] == "2026-11-09T01:20:00Z"
    assert again["summary"]["source"] == "carried" and again["summary"]["text"] == "words" and not calls


def test_the_same_print_is_not_a_change():
    rows = [_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4)]
    first = _build(SUNDAY, rows=rows)
    assert _build(SUNDAY + timedelta(minutes=15), prior=first, rows=rows) is None


def test_the_boundary_is_the_snapshots_own_clock_not_the_newest_print_it_saw():
    """A row that predates generated_at but was not in the prior build (ingest lag) is not a rebuild trigger here:
    the rule is 'printed after the snapshot was built', and the 2-hourly forced rebuild covers the lag. Stated so
    a later widening has to change this test on purpose."""
    first = _build(SUNDAY, rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4)])
    late_but_older = _row("WWW", datetime(2026, 11, 8, 20, 10, tzinfo=ET), price=50.4, pct=0.5)
    assert _build(
        SUNDAY + timedelta(minutes=15),
        prior=first,
        rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4), late_but_older],
    ) is None


def test_a_symbol_the_card_does_not_show_never_triggers_a_rebuild():
    first = _build(SUNDAY, rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4)])
    assert _build(
        SUNDAY + timedelta(minutes=15),
        prior=first,
        rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4),
              _row("ZZZ", datetime(2026, 11, 8, 20, 20, tzinfo=ET))],
    ) is None


def test_a_forced_rebuild_still_ignores_the_print_rule():
    """--apply without --if-changed rebuilds regardless (the sibling lane); the rule only narrows the conditional."""
    snap = c.build_snapshot(
        now=SUNDAY, ticker_snapshot=_tickers(), articles=[], futures=None, llm=None, if_changed=False,
        extended_rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4)],
    )
    assert snap is not None


def test_an_unpriced_print_is_a_print_but_never_reads_as_zero_moved():
    """The trigger is the row clock, not a value: a level-only print (its ``reference_date`` is not this card's
    close, so it has no percentage of its own) still makes the card stale, and the chip keeps Friday's matched
    pair -- an unpriced name must not read as 0% (cc-deepseek-8's caution on LQ-1282's unknown-value rule)."""
    first = _build(SUNDAY, rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4)])
    assert first is not None
    level = _row("WWW", datetime(2026, 11, 8, 20, 20, tzinfo=ET), price=51.0, pct=None, session="afterhours")
    level["reference_date"] = "2026-11-05"  # Thursday's close: a LEVEL, not a move vs Friday
    again = _build(SUNDAY + timedelta(minutes=15), prior=first,
                   rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4), level])
    assert again is not None and again["updated"]["kind"] == "print"
    watch = next(m for m in again["moves"] if m["symbol"] == "WWW")
    assert watch["extended"]["state"] == "level_only" and watch["extended"]["change_pct"] is None
    assert watch["move_now_pct"] == watch["change_pct"] == 0.4, "the two chip numbers stay a matched pair"


def test_a_prior_clock_that_cannot_be_read_rebuilds_rather_than_vouching_for_quiet():
    """No prior ``generated_at`` means the rule cannot prove no print landed since: the safe direction is a cheap
    non-material rebuild, never silence. Every snapshot this module writes carries the clock, so this is the
    legacy/hand-made case and it heals itself on the write."""
    first = _build(SUNDAY, rows=[_row("WWW", datetime(2026, 11, 8, 20, 0, tzinfo=ET), price=50.2, pct=0.4)])
    blind = {k: v for k, v in first.items() if k != "generated_at"}
    again = _build(SUNDAY + timedelta(minutes=15), prior=blind, rows=[])
    assert again is not None
    assert again["updated"]["kind"] == "print" and again["updated"]["reason"] == "rebuilt to establish the prior clock"
    assert again["generated_at"] == "2026-11-09T01:30:00Z"


# ── end to end: the real script, a temp state root, the two instants the operator named ──────────────────────


class _Cur:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.description = []

    def fetchall(self):
        return []


class _Conn:
    """Every query answers no rows; the extended store is supplied by fetch_extended, patched per test."""

    def __init__(self):
        self.closed = False

    def cursor(self):
        return _Cur()

    def close(self):
        self.closed = True


def _state_root(tmp_path: Path, *, held=("AAA",), watch=("WWW",)) -> Path:
    st = tmp_path / "state"
    state_dir = st / "data/portfolios/state"
    state_dir.mkdir(parents=True, exist_ok=True)
    snap = _tickers(held=held, watch=watch)
    (state_dir / "ticker_snapshot_latest.json").write_text(  # nosemgrep: tq-py-nonatomic-store-write -- tmp fixture
        __import__("json").dumps(snap)
    )
    return st


def _run(tmp_path, monkeypatch, rows, now: datetime):
    import lib.cio_market_context_state as CM
    import since_close_snapshot as SCS

    st = _state_root(tmp_path)
    conn = _Conn()
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(st))
    monkeypatch.setattr(CM, "connect_trade_ai_readonly", lambda: conn)
    monkeypatch.setattr(c, "fetch_extended", lambda conn, *, symbols, since: list(rows))
    rc = SCS.main(["--apply", "--if-changed", "--state-dir", str(st / "data/portfolios/state"),
                   "--now", now.isoformat()])
    out = st / "data/portfolios/state/since_close_latest.json"
    return rc, (out.read_text() if out.exists() else None), conn


def test_sunday_2030_et_a_new_overnight_print_reaches_the_file(tmp_path, monkeypatch, capsys):
    """The operator's instants, through the real script: Sun 20:15 writes, and at Sun 20:30 a print that landed
    after that build rebuilds the file with the new print — no model call in either fire."""
    import json as _json

    rows = [_row("WWW", datetime(2026, 11, 8, 20, 5, tzinfo=ET), price=50.2, pct=0.4)]
    rc, snap, conn = _run(tmp_path, monkeypatch, rows, datetime(2026, 11, 8, 20, 15, tzinfo=ET))
    capsys.readouterr()
    assert rc == 0 and snap and conn.closed
    first = _json.loads(snap)
    assert first["generated_at"] == "2026-11-09T01:15:00Z"

    rows2 = [*rows, _row("WWW", datetime(2026, 11, 8, 20, 25, tzinfo=ET), price=50.8, pct=0.8)]
    rc, snap2, conn = _run(tmp_path, monkeypatch, rows2, datetime(2026, 11, 8, 20, 30, tzinfo=ET))
    out, _err = capsys.readouterr()
    assert rc == 0 and conn.closed
    assert "wrote " in out and "prints_since_close=1 WWW" in out
    second = _json.loads(snap2)
    assert second["generated_at"] == "2026-11-09T01:30:00Z"
    assert second["updated"]["kind"] == "print" and second["updated"]["reason"] == "new WWW print Sun 8:25 PM ET overnight"
    assert next(m for m in second["moves"] if m["symbol"] == "WWW")["extended"]["change_pct"] == 0.8


def test_friday_1700_et_a_held_after_hours_print_reaches_the_file(tmp_path, monkeypatch, capsys):
    """The Schwab lane's missing Friday 16:00-20:00 slot, seen from the card: once the lane stores an after-hours
    print on a HELD name, a build as of Friday 17:00 attaches it to that name (the card half of LQ-1304 fix (a))."""
    import json as _json

    rows = [_row("AAA", datetime(2026, 11, 6, 16, 45, tzinfo=ET), session="afterhours", price=101.5, pct=1.5)]
    rc, snap, conn = _run(tmp_path, monkeypatch, rows, datetime(2026, 11, 6, 17, 0, tzinfo=ET))
    out, _err = capsys.readouterr()
    assert rc == 0 and conn.closed and "wrote " in out
    card = _json.loads(snap)
    assert card["window"]["session_date"] == "2026-11-06"
    ext = next(m for m in card["moves"] if m["symbol"] == "AAA")["extended"]
    assert ext["state"] == "print" and ext["session_label"] == "after-hours" and ext["change_pct"] == 1.5
    assert "prints_since_close=1 AAA" in out


def test_this_module_is_registered_in_the_ci_gate():
    gate = ROOT / "config/ci_gates/since_close_new_print_rebuild_lq1304_20261109.json"
    spec = __import__("json").loads(gate.read_text())
    assert spec["schema"] == "CiGate@v1"
    assert spec["name"] == gate.stem == "since_close_new_print_rebuild_lq1304_20261109"
    assert spec["files"] == ["tests/test_since_close_new_print_rebuild_lq1304_20261109.py"]
    assert spec["anchor"] == "SINCE_CLOSE_NEW_PRINT_REBUILD_LQ1304_20261109"
