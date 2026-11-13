"""LQ-20261107-1679 — no yfinance quote writer is left in external_market_data_ingest.

Measured read-only by cc-opus-1, 2026-11-09: ``market_quotes`` took 583 yfinance rows in two days,
newest 14:24 ET. The operator's price rule bans the source: a live price comes from Finviz (fresh
<= 30 min), else a fresh Schwab/Alpaca/moomoo quote; never yfinance, never a stored DB price older
than 30 minutes.

These tests pin the removal, not a feature flag:
  A. the module no longer DEFINES ``ingest_yfinance_quotes``, no longer imports yfinance, and no
     call in it passes ``source="yfinance"`` (the AST check catches a copy pasted back under a new
     name as long as it imports the library or labels the rows);
  B. ``ingest_quotes`` writes nothing for a symbol Finviz cannot price — it reports it under
     ``unpriced.no_quote``; a tier that could not attempt a symbol stays ``unpriced.tier_unavailable``;
  C. the retired ``--quotes-yf`` CLI path REFUSES (exit 2) instead of exiting 0 as a silent no-op.

No database, no network: provider calls are monkeypatched fakes and the CLI case exits before any
I/O. Fixtures are synthetic symbols.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as ingest  # noqa: E402

SCRIPT = ROOT / "scripts" / "external_market_data_ingest.py"


def _tree() -> ast.Module:
    return ast.parse(SCRIPT.read_text(encoding="utf-8"))


def test_the_module_defines_no_yfinance_quote_writer():
    tree = _tree()
    defs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert "ingest_yfinance_quotes" not in defs
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "yfinance", "the banned provider is imported again"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") != "yfinance"
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg != "source":
                    continue
                value = kw.value
                name = getattr(value, "value", getattr(value, "id", None))
                assert name != "yfinance", "a call still labels its rows source='yfinance'"


def test_ingest_quotes_reports_a_finviz_miss_and_writes_nothing_for_it(monkeypatch):
    monkeypatch.setattr(ingest, "ingest_alpaca_quotes",
                        lambda symbols=None: {"source": "alpaca", "fetched": 1, "total": 3,
                                              "missing": ["ZQA", "ZQB", "ZQC"]})
    monkeypatch.setattr(ingest, "ingest_finviz_quotes",
                        lambda symbols=None: {"source": "finviz", "fetched": 1, "total": 3,
                                              "missing": ["ZQB"], "unwritten": ["ZQA"],
                                              "reconnects": 0, "rows_dropped": 0})

    out = ingest.ingest_quotes(["ZQA", "ZQB", "ZQC"])

    assert out["unpriced"]["no_quote"] == ["ZQB"]
    assert out["unpriced"]["tier_unavailable"] == ["ZQA"]
    assert "yfinance" not in out
    assert out["alpaca"] == 1 and out["finviz"] == 1


def test_a_dead_finviz_tier_routes_nothing_and_reports_unpriced(monkeypatch):
    monkeypatch.setattr(ingest, "ingest_alpaca_quotes",
                        lambda symbols=None: {"source": "alpaca", "fetched": 0, "total": 2,
                                              "missing": ["ZQA", "ZQB"]})

    def dead(symbols=None):
        raise RuntimeError("connection already closed")

    monkeypatch.setattr(ingest, "ingest_finviz_quotes", dead)
    out = ingest.ingest_quotes(["ZQA", "ZQB"])

    assert out["unpriced"]["tier_unavailable"] == ["ZQA", "ZQB"]
    assert out["unpriced"]["no_quote"] == []
    assert "connection already closed" in (out["finviz_error"] or "")


class _CycleCursor:
    """Records every statement the real writer issues; the sink is the observation point."""

    def __init__(self, sink):
        self.sink = sink
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.sink.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class _CycleConn:
    def __init__(self, sink):
        self.sink = sink
        self.closed = False
        self.commits = 0

    def cursor(self):
        return _CycleCursor(self.sink)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def test_one_emulated_cycle_writes_only_alpaca_and_finviz_rows(monkeypatch):
    """One full ``ingest_quotes`` pass, real tiers and the real writer, fake I/O only.

    This is the emulated cycle the ticket asks for: ZQA is priced by Alpaca, ZQB is
    missed by Alpaca and priced by Finviz, ZQC is priced by neither. Every statement
    the writer issues is recorded, so the set of sources that reached the ledger is
    measured, not asserted from the source text: exactly ``alpaca`` and ``finviz``,
    never ``yfinance``, and the unpriced symbol writes nothing at all.
    """
    sink: list[tuple[str, object]] = []
    monkeypatch.setattr(ingest, "_get_conn", lambda role="generic": _CycleConn(sink))
    monkeypatch.setattr(ingest, "CONNECTION_LOST_ERRORS", ())  # isolated run: no loss to repair
    monkeypatch.setattr(ingest, "_alpaca_creds", lambda: ("ZQKEY", "ZQSECRET"))
    monkeypatch.setattr(ingest.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ingest, "_finviz_quote",
                        lambda sym, *a, **k: ({"price": "20.5", "prev": "20.0", "rvol": None, "volume": "300"}
                                     if sym == "ZQB" else {}))

    import requests

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ZQA": {"latestTrade": {"p": 10.5},
                            "dailyBar": {"c": 10.4, "v": 1000, "t": "2026-11-09T20:00:00Z"},
                            "prevDailyBar": {"c": 10.0}}}

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())

    out = ingest.ingest_quotes(["ZQA", "ZQB", "ZQC"])

    inserts = [(sql, params) for sql, params in sink if "INSERT INTO market_quotes" in str(sql)]
    sources = [params[1] for _sql, params in inserts]
    assert sources == ["alpaca", "finviz"], sources
    assert "yfinance" not in sources
    assert out["alpaca"] == 1 and out["finviz"] == 1 and out["fetched"] == 2
    assert out["unpriced"] == {"tier_unavailable": [], "no_quote": ["ZQC"]}
    assert all("ZQC" not in str(params) for _sql, params in inserts), "the unpriced symbol was written"


def test_the_quotes_yf_cli_path_refuses_instead_of_running():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--quotes-yf"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "retired" in proc.stderr and "--quotes" in proc.stderr
