"""Authoritative holdings slices. One module every consumer calls.

READ_ONLY_ADVISORY. No new store — reads holdings.json.

Denominator for thesis coverage is held_equity_tickers() (unique tickers,
CASH and CUSIPs excluded). Scheduler T0-HOLD must match that set.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HoldingsUniverse@v1"

CASH_SYMBOLS = frozenset({"CASH", "USD", "SPAXX", "VMFXX", "FDRXX", "TEST"})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def holdings_path(*, root: Path | None = None) -> Path:
    root = root or _project_root()
    return root / "data" / "portfolios" / "state" / "holdings.json"


def load_holdings_doc(*, root: Path | None = None) -> dict[str, Any]:
    path = holdings_path(root=root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def held_position_rows(*, root: Path | None = None) -> list[dict[str, Any]]:
    data = load_holdings_doc(root=root)
    rows = data.get("holdings") or data.get("positions") or []
    return [r for r in rows if isinstance(r, dict)]


def is_cash_row(row: dict[str, Any]) -> bool:
    if row.get("is_cash") is True:
        return True
    if str(row.get("asset_type") or "").strip().lower() == "cash":
        return True
    return str(row.get("symbol") or "").strip().upper() in CASH_SYMBOLS


def is_held_equity_ticker(symbol: str) -> bool:
    """True for coverage/T0-HOLD tickers. CASH and CUSIP-like ids are out."""
    t = str(symbol or "").strip().upper()
    if not t or t in CASH_SYMBOLS:
        return False
    if len(t) > 5 or not t[0].isalpha():
        return False
    return all(c.isalnum() or c in ".-" for c in t)


def held_cash_rows(*, root: Path | None = None) -> list[dict[str, Any]]:
    return [r for r in held_position_rows(root=root) if is_cash_row(r)]


def held_unresolved_cusips(*, root: Path | None = None) -> list[str]:
    out: list[str] = []
    for r in held_position_rows(root=root):
        if is_cash_row(r):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        if sym and not is_held_equity_ticker(sym):
            out.append(sym)
    return sorted(set(out))


def held_equity_tickers(*, root: Path | None = None) -> list[str]:
    """Authoritative coverage denominator: unique non-cash equity tickers."""
    out: list[str] = []
    for r in held_position_rows(root=root):
        if is_cash_row(r):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        if is_held_equity_ticker(sym):
            out.append(sym)
    return sorted(set(out))


def snapshot(*, root: Path | None = None) -> dict[str, Any]:
    rows = held_position_rows(root=root)
    tickers = held_equity_tickers(root=root)
    cash = held_cash_rows(root=root)
    cusips = held_unresolved_cusips(root=root)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": _now(),
        "source": str(holdings_path(root=root)),
        "position_rows": len(rows),
        "unique_symbols": len({str(r.get("symbol") or "").upper() for r in rows if r.get("symbol")}),
        "cash_rows": len(cash),
        "unresolved_cusips": cusips,
        "unresolved_cusip_n": len(cusips),
        "held_equity_tickers": tickers,
        "held_equity_ticker_n": len(tickers),
        "financial_action": False,
    }


def write_snapshot(*, root: Path | None = None) -> Path:
    root = root or _project_root()
    path = root / "data" / "cio" / "holdings_universe_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(root=root), indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    import sys

    snap = snapshot()
    sys.stdout.write(json.dumps(snap, indent=2) + "\n")
    if "--write" in sys.argv:
        path = write_snapshot()
        sys.stderr.write(f"wrote {path}\n")
