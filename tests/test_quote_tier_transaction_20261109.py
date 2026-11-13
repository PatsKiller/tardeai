"""LQ-20261107-1609 — the quote tiers must not hold a transaction across a provider call.

ANCHOR: QUOTE_TIER_TRANSACTION_20261109

Measured on the live line 2026-11-09 (base fd844f3d4), read-only:

* ``market_quotes`` took 45 yfinance rows per ``--quotes`` run that failed its Finviz tier and 28 when
  the tier committed — the same 45 symbols are 28 mutual-fund/OTC names finviz cannot price plus 17 it
  can (AAAD…ZCBG). So the yfinance volume was a *symptom*: the middle tier was dying and its symbols
  were re-attributed to the next provider.
* ``logs/market_data.log``: 620 × ``[fallback] finviz failed (non-fatal): connection already closed``.
* ``pg_roles``: role ``trade_ai`` carries ``idle_in_transaction_session_timeout=120s`` and, today,
  postgres logged 28 ``terminating connection due to idle-in-transaction timeout`` FATALs.

``ingest_finviz_quotes`` wrote every symbol into ONE transaction that stayed open across the whole
loop — up to ~156 per-symbol HTTP requests, each of which may wait minutes on the global Finviz
throttle — so the server killed the session and the tier's commit raised. ``ingest_quotes`` then
swallowed the error and handed the tier's entire miss list to yfinance: work Finviz was never asked
to do, on a source the outlook method bans.

These tests pin both halves:
  A. no provider call is ever made while a transaction is open, and a killed connection is repaired
     (bounded, via lib.pg_reconnect) instead of losing the run;
  B. a symbol the tier could not attempt is ``unwritten``, never ``missing``, so it is not routed to
     the next provider; and a genuine "finviz has no quote" is reported unpriced — since
     LQ-20261107-1679 there is no yfinance tier to reach at all.

No database, no network, no provider call: the connection and the writer are fakes.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as ingest  # noqa: E402


class FakeLost(Exception):
    """Stands in for psycopg2.InterfaceError('connection already closed')."""


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn
        self.rowcount = 1

    def execute(self, sql, params=None):  # noqa: ARG002 — the fake models the transaction, not SQL
        if self.conn.closed:
            raise FakeLost("connection already closed")
        self.conn.in_tx = True

    def close(self) -> None:
        pass


class FakeConn:
    """A connection whose server kills it when a provider call starts mid-transaction.

    That is the live failure, abstracted: the role's idle_in_transaction_session_timeout fires when
    the transaction has no statement for 120 s, and the tier's provider calls are exactly that gap.
    """

    def __init__(self, *, kill_on_provider_call: bool = True) -> None:
        self.closed = False
        self.in_tx = False
        self.kill_on_provider_call = kill_on_provider_call
        self.provider_calls = 0
        self.provider_calls_in_tx = 0

    def cursor(self):
        if self.closed:
            raise FakeLost("connection already closed")
        return FakeCursor(self)

    def commit(self) -> None:
        if self.closed:
            raise FakeLost("connection already closed")
        self.in_tx = False

    def rollback(self) -> None:
        self.in_tx = False

    def close(self) -> None:
        self.closed = True


class Harness:
    """Three symbols, a fake provider, a fake writer and a fake connection factory."""

    def __init__(self, monkeypatch, *, defeat: bool = True, kill_at_call: int | None = None) -> None:
        self.conns: list[FakeConn] = []
        self.defeat = defeat
        self.kill_at_call = kill_at_call
        self.prices = {"AAA": "10.5", "BBB": "20.25", "CCC": None}  # CCC: finviz has no quote
        self.rows: list[str] = []
        self.commit_fail_for: set[str] = set()

        monkeypatch.setattr(ingest, "CONNECTION_LOST_ERRORS", (FakeLost,))
        monkeypatch.setattr(ingest, "FINVIZ_MAX_RECONNECTS", 3)
        monkeypatch.setattr(ingest.time, "sleep", lambda _s: None)
        monkeypatch.setattr(ingest, "_get_conn", self._connect)
        monkeypatch.setattr(ingest, "_finviz_quote", self._quote)
        monkeypatch.setattr(ingest, "write_market_quotes", self._write)

    # connection factory
    def _connect(self, role: str = "generic"):
        assert role == "finviz", f"the Finviz tier must name its role, got {role!r}"
        conn = FakeConn(kill_on_provider_call=self.defeat)
        self.conns.append(conn)
        return conn

    @property
    def current(self) -> FakeConn:
        return self.conns[-1]

    # provider
    def _quote(self, sym: str, deadline=None) -> dict:
        conn = self.current
        conn.provider_calls += 1
        if conn.in_tx:
            conn.provider_calls_in_tx += 1
            if self.defeat:
                conn.closed = True  # the server killed an idle-in-transaction session
        if self.kill_at_call is not None and conn.provider_calls == self.kill_at_call:
            conn.closed = True  # a kill unrelated to this tier's transaction discipline
        price = self.prices.get(sym)
        return {"price": price, "prev": price, "rvol": None, "volume": None} if price else {}

    # writer
    def _write(self, cur, rows, *, source, **_kw):
        for row in rows:
            cur.execute("INSERT", (row,))
            if row["symbol"] in self.commit_fail_for:
                # the commit of THIS row is the statement the server refuses
                cur.conn.closed = True
            else:
                self.rows.append(row["symbol"])
        return SimpleNamespace(rows_accepted=len(rows), rows_written=len(rows))


def test_no_provider_call_is_made_while_a_transaction_is_open(monkeypatch):
    """Fail-before: one commit after the loop → calls 2..N start inside the open transaction."""
    h = Harness(monkeypatch, defeat=False)
    out = ingest.ingest_finviz_quotes(["AAA", "BBB", "CCC"])

    assert h.current.provider_calls == 3
    assert h.current.provider_calls_in_tx == 0, (
        "a provider call was made with a transaction open — the role's "
        "idle_in_transaction_session_timeout is measuring exactly that window"
    )
    assert out["fetched"] == 2 and out["missing"] == ["CCC"]
    assert out["unwritten"] == []
    assert h.rows == ["AAA", "BBB"]


def test_a_killed_connection_is_repaired_and_the_run_continues(monkeypatch):
    """A server-side kill mid-loop: the tier must repair the connection, not lose the run."""
    h = Harness(monkeypatch, defeat=False, kill_at_call=2)
    out = ingest.ingest_finviz_quotes(["AAA", "BBB", "CCC"])

    assert len(h.conns) >= 2, "a killed connection was not replaced"
    assert out["fetched"] == 2
    assert out["missing"] == ["CCC"], "a symbol the tier priced must not be reported missing"
    assert out["unwritten"] == [], "the tier could attempt every symbol; nothing may be 'unwritten'"
    assert out["reconnects"] >= 1
    assert sorted(set(h.rows)) == ["AAA", "BBB"]


def test_an_unattemptable_symbol_is_unwritten_not_missing(monkeypatch):
    """A write the connection cannot complete is 'we could not tell', never 'finviz has no quote'."""
    h = Harness(monkeypatch, defeat=False)
    h.commit_fail_for = {"BBB"}
    out = ingest.ingest_finviz_quotes(["AAA", "BBB", "CCC"])

    assert out["unwritten"] == ["BBB"]
    assert out["missing"] == ["CCC"], "BBB was never answered by finviz as 'no quote'"
    assert "BBB" not in out["missing"]


def test_a_dead_tier_routes_nothing_to_the_next_provider(monkeypatch):
    """ingest_quotes: a tier failure must not hand its miss list to anything else.

    LQ-20261107-1679 removed the yfinance tier outright, so the property is now absolute: there is
    no next provider to route to, and the module no longer carries the writer at all.
    """
    monkeypatch.setattr(ingest, "_get_symbols", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(ingest, "ingest_alpaca_quotes",
                        lambda symbols=None: {"source": "alpaca", "fetched": 0, "total": 2,
                                              "missing": ["AAA", "BBB"]})

    def dead_tier(symbols=None):
        raise RuntimeError("connection already closed")

    monkeypatch.setattr(ingest, "ingest_finviz_quotes", dead_tier)
    out = ingest.ingest_quotes(["AAA", "BBB"])

    assert not hasattr(ingest, "ingest_yfinance_quotes"), "the banned writer is back"
    assert "yfinance" not in out
    assert out["unpriced"]["tier_unavailable"] == ["AAA", "BBB"]
    assert "connection already closed" in (out["finviz_error"] or "")


def test_a_genuine_finviz_miss_is_reported_unpriced_never_routed(monkeypatch):
    """A real "finviz has no quote" used to reach yfinance and be WRITTEN as a price.

    LQ-20261107-1679: it is now reported as unpriced and nothing is written — a missing price the
    caller can show, not a price from a banned source.
    """
    monkeypatch.setattr(ingest, "ingest_alpaca_quotes",
                        lambda symbols=None: {"source": "alpaca", "fetched": 0, "total": 3,
                                              "missing": ["AAA", "BBB", "CCC"]})
    monkeypatch.setattr(ingest, "ingest_finviz_quotes",
                        lambda symbols=None: {"source": "finviz", "fetched": 1, "total": 3,
                                              "missing": ["BBB"], "unwritten": ["AAA"],
                                              "reconnects": 1, "rows_dropped": 1})

    out = ingest.ingest_quotes(["AAA", "BBB", "CCC"])

    assert out["unpriced"]["no_quote"] == ["BBB"], "a finviz miss must be reported, not routed"
    assert out["unpriced"]["tier_unavailable"] == ["AAA"], "unwritten (the tier could not tell) is not a miss"
    assert "yfinance" not in out


def test_the_news_gap_path_writes_no_quote():
    """The second live yfinance writer: a NEWS gap used to write a yfinance quote for the symbol."""
    src = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "ingest_yfinance_quotes"
    ]
    assert hits == [], (
        "process_watchlist_agent_jobs must not import or call ingest_yfinance_quotes: a news gap is "
        "not a price gap, and the call wrote live yfinance rows for TGE at 10:46/10:47 ET 2026-11-09"
    )


def test_a_news_only_gap_reports_no_enrichment(monkeypatch):
    """Behavioural half: no price/technical gap, no quote written, and not a false 'enriched'."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import process_watchlist_agent_jobs as pwaj  # noqa: PLC0415 — heavy module, imported on demand

    assert pwaj._attempt_symbol_enrichment("ZZTEST", ["news_articles"]) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
