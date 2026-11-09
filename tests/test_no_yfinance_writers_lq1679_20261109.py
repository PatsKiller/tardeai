"""LQ-20261107-1679 — yfinance is never a price source, and a new import cannot slip back in.

ANCHOR: NO_YFINANCE_PRICE_WRITERS_LQ1679_20261109

The operator price rule (2026-11-07, WORKERS.md "N8N ONBOARDING + PRICE WORK"): "Finviz cache first
(30 min), a fresh Schwab/Alpaca/moomoo quote second, the stored mark only flagged stale. Never
yfinance." Measured on the live line 2026-11-09 before this change, read-only:

* ``market_quotes``: 870 rows ``source='yfinance'`` in 3 days, newest 15:56 ET, written by the third
  tier of ``external_market_data_ingest.ingest_quotes`` (~290 rows/day) — the tier is gone.
* ``ticker_prices``: 881 rows ``source='yfinance'`` in 7 days, newest 2026-11-08 20:39 ET, written by
  ``price_db_sync.backfill_yfinance_history`` — now ``backfill_price_history`` over Alpaca daily bars.
* ``data/portfolios/state/price_cache.json``: rebuilt from yfinance every Sunday by
  ``portfolio_price_cache`` — now from Alpaca daily bars, live fallback included.

Three kinds of test here:
  A. the three writers are free of yfinance (AST, so a commented mention does not count either way);
  B. behaviour: a symbol both providers cannot price is REPORTED unpriced with its cause, never
     re-attributed, and the retired ``--quotes-yf`` CLI fails loudly instead of writing;
  C. a repo-wide ratchet over ``config/yfinance_import_baseline.json``. Any module that imports
     yfinance must be listed with its kind; a NEW importer fails; a module listed as a price reader
     fails if it is not in the frozen set; and an entry that no longer imports yfinance must be
     removed (the baseline may only shrink). Fixing a module means editing this file — that is the
     design: the guard cannot silently grow.

No database, no network, no provider call: connections, cursors and fetchers are fakes.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

BASELINE = ROOT / "config" / "yfinance_import_baseline.json"

PRICE_WRITERS = [
    "scripts/external_market_data_ingest.py",
    "scripts/price_db_sync.py",
    "scripts/portfolio_price_cache.py",
]


def _yfinance_imports(path: Path) -> list[str]:
    """Every ``import yfinance`` / ``from yfinance ...`` in a file, as a readable list."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "yfinance"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "yfinance":
                found.append(f"from {node.module}")
    return found


def _scanned_modules() -> list[Path]:
    return sorted(p for p in (ROOT / "scripts").rglob("*.py") if "archive" not in p.parts)


# ── A. the three price writers are free of yfinance ──────────────────────────

def test_the_quote_ingest_module_never_imports_yfinance():
    assert _yfinance_imports(ROOT / PRICE_WRITERS[0]) == [], (
        "external_market_data_ingest writes market_quotes; a yfinance import there is a live banned "
        "price writer (LQ-20261107-1679 removed the last one, the third tier)"
    )


def test_price_db_sync_never_imports_yfinance():
    assert _yfinance_imports(ROOT / PRICE_WRITERS[1]) == [], (
        "price_db_sync writes ticker_prices; its gap-fill must stay on Alpaca daily bars"
    )


def test_portfolio_price_cache_never_imports_yfinance():
    assert _yfinance_imports(ROOT / PRICE_WRITERS[2]) == [], (
        "portfolio_price_cache rebuilds price_cache.json; both its bulk fetch and its live fallback "
        "are price reads"
    )


# ── B. behaviour ─────────────────────────────────────────────────────────────

def test_a_symbol_no_provider_can_price_is_reported_unpriced(monkeypatch):
    import external_market_data_ingest as ingest

    monkeypatch.setattr(ingest, "ingest_alpaca_quotes",
                        lambda symbols=None: {"source": "alpaca", "fetched": 1, "total": 3,
                                              "missing": ["FUNDX", "OTCADR", "AAA"]})
    monkeypatch.setattr(ingest, "ingest_finviz_quotes",
                        lambda symbols=None: {"source": "finviz", "fetched": 1, "total": 3,
                                              "missing": ["FUNDX", "OTCADR"], "unwritten": [],
                                              "reconnects": 0, "rows_dropped": 0})
    out = ingest.ingest_quotes(["FUNDX", "OTCADR", "AAA"])

    assert out["unpriced"]["no_quote"] == ["FUNDX", "OTCADR"]
    assert out["unpriced"]["tier_unavailable"] == []
    assert "yfinance" not in out
    assert out["fetched"] == 2  # alpaca 1 + finviz 1, and nothing invented


def test_the_retired_quotes_yf_cli_refuses_and_writes_nothing(tmp_path):
    """A stale cron line or retry_cmd that still says --quotes-yf must FAIL, not quietly no-op."""
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "scripts"),
           "TRADEAI_STATE_ROOT": str(tmp_path)}
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "external_market_data_ingest.py"),
                           "--quotes-yf"],
                          capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=120)
    assert proc.returncode == 2, f"--quotes-yf must exit 2, got {proc.returncode}: {proc.stderr[:400]}"
    assert "--quotes" in proc.stderr and "LQ-20261107-1679" in proc.stderr, (
        "the refusal must name the ticket and the replacement path, so a stale cron line is diagnosable"
    )


def test_the_backfill_writes_alpaca_never_yfinance(monkeypatch):
    import price_db_sync as prices

    written: list[dict] = []

    class Cursor:
        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    def alpaca_rows(symbol, period="1y", *, fetch=None):  # noqa: ARG001 — the real helper's shape
        if symbol == "NOPRICE":
            return []
        return [{"symbol": symbol, "price_date": __import__("datetime").date(2026, 11, 6),
                 "close_price": 10.5}]

    monkeypatch.setattr(prices, "_get_conn", lambda: Conn())
    monkeypatch.setattr("lib.redeploy_price_history._alpaca_close_rows", alpaca_rows)
    monkeypatch.setattr(prices, "write_ticker_prices",
                        lambda cur, rows, **kw: (written.append({"rows": rows, **kw}),
                                                 SimpleNamespace(rows_written=len(rows)))[1])

    out = prices.backfill_price_history(["AAA", "NOPRICE"])

    assert [w["source"] for w in written] == ["alpaca"], (
        "the gap-fill still writes a non-Alpaca source"
    )
    assert out["source"] == "alpaca"
    assert out["filled"] == 1 and out["failed"] == 1
    assert out["failed_sample"] == ["NOPRICE"], "a symbol with no bars is failed, never invented"


def test_the_legacy_backfill_name_cannot_reach_yfinance(monkeypatch):
    import price_db_sync as prices

    assert prices.backfill_yfinance_history is not None
    assert _yfinance_imports(ROOT / "scripts" / "price_db_sync.py") == []
    # The alias resolves to the Alpaca path, not to a banned write.
    calls: list[str] = []
    monkeypatch.setattr(prices, "backfill_price_history",
                        lambda symbols, **kw: (calls.append("alpaca"), {"filled": 0})[1])
    assert prices.backfill_yfinance_history(["AAA"]) == {"filled": 0}
    assert calls == ["alpaca"]


def test_the_price_cache_build_maps_dates_to_alpaca_closes(monkeypatch):
    import market_data_snapshot_loader as mdl
    import portfolio_price_cache as ppc

    def bars(symbol, days):  # noqa: ARG001 -- the fake mirrors fetch_alpaca_daily_bars(symbol, days)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        return [
            {"symbol": symbol, "close": 10.0, "bar_time": datetime(2026, 11, 5, tzinfo=et)},
            {"symbol": symbol, "close": 10.5, "bar_time": datetime(2026, 11, 6, tzinfo=et)},
            {"symbol": symbol, "close": 0, "bar_time": datetime(2026, 11, 7, tzinfo=et)},
            {"symbol": symbol, "close": None, "bar_time": datetime(2026, 11, 8, tzinfo=et)},
        ]

    monkeypatch.setattr(mdl, "fetch_alpaca_daily_bars", bars)
    out = ppc._fetch_symbols(["AAA"], "2026-11-01", "2026-11-09")

    assert out == {"AAA": {"2026-11-05": 10.0, "2026-11-06": 10.5}}, (
        "a zero close or a missing close must be skipped, not stored as 0"
    )


# ── C. repo-wide ratchet ─────────────────────────────────────────────────────

def test_no_module_outside_the_baseline_imports_yfinance():
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    allowed = doc["allowed"]
    new = [str(p.relative_to(ROOT)) for p in _scanned_modules()
           if _yfinance_imports(p) and str(p.relative_to(ROOT)) not in allowed]
    assert new == [], (
        "new yfinance importer(s): " + ", ".join(new) + ". yfinance is banned for prices "
        "(operator rule 2026-11-07, LQ-20261107-1679); a non-price use still needs an entry in "
        "config/yfinance_import_baseline.json with its reason"
    )


def test_every_baseline_entry_still_imports_yfinance_so_the_baseline_only_shrinks():
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    stale = [mod for mod in doc["allowed"] if not _yfinance_imports(ROOT / mod)]
    assert stale == [], (
        "baseline entries that no longer import yfinance: " + ", ".join(stale) +
        ". Delete them — a baseline that only grows hides the next regression"
    )


def test_no_baseline_entry_is_a_price_source():
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    price = sorted(m for m, meta in doc["allowed"].items() if meta.get("kind") == "price")
    assert price == [], (
        "modules still fetching a PRICE from yfinance: " + ", ".join(price) +
        ". They must be routed to Alpaca/Finviz/broker, not baselined"
    )


def test_the_price_read_follow_up_set_is_the_frozen_one():
    """Modules that still take a price from yfinance but do not write a store.

    They are not fixed by LQ-1679 (which removed the three store writers) and each needs its own
    row; this assertion freezes the set so it can only shrink and a fix must update the baseline.
    """
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    actual = set(m for m, meta in doc["allowed"].items() if meta.get("kind") == "price_read")
    actual |= set(doc.get("dynamic_allowed") or {})  # a hidden import is a price read by construction
    assert sorted(actual) == sorted(doc["price_read_follow_ups"]), (
        "the price-read follow-up set changed; update config/yfinance_import_baseline.json "
        "price_read_follow_ups and tell the lead which module was fixed"
    )


_IMPORT_IN_TEXT = __import__("re").compile(
    r"(?m)^[ \t]*(?:import[ \t]+yfinance|from[ \t]+yfinance\b)"
)


def test_no_module_hides_a_yfinance_import_in_a_source_string():
    """An import the AST cannot see: ``exec``/subprocess source text.

    ``lib/quote_validator.get_yfinance_quotes`` builds ``"import yfinance as yf, json"`` and runs it
    in a subprocess, so an AST-only guard reports it clean while it fetches a yfinance price. This
    scan is over string constants, matched at line start so ordinary prose in a docstring ("never
    yfinance") does not count.
    """
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    allowed = set(doc.get("dynamic_allowed") or {})
    hidden = []
    for path in _scanned_modules():
        rel = str(path.relative_to(ROOT))
        if rel in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and _IMPORT_IN_TEXT.search(node.value)):
                hidden.append(f"{rel}:{node.lineno}")
                break
    assert hidden == [], (
        "yfinance import hidden inside a source string (exec/subprocess): " + ", ".join(hidden) +
        ". Either route the price to Alpaca/Finviz or list the module in dynamic_allowed with its "
        "reason — the AST guard cannot see this path"
    )


def test_a_dynamic_entry_still_hides_its_import_or_it_is_removed():
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    stale = []
    for rel in doc.get("dynamic_allowed") or {}:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        if not any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and _IMPORT_IN_TEXT.search(n.value) for n in ast.walk(tree)):
            stale.append(rel)
    assert stale == [], f"dynamic_allowed entries with no hidden import any more: {stale}"
