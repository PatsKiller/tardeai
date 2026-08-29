"""Authoritative holdings slices. One module every consumer calls.

READ_ONLY_ADVISORY. No new store — reads holdings.json.

Denominator for thesis coverage is held_equity_tickers() (unique tickers,
CASH and CUSIPs excluded). Scheduler T0-HOLD must match that set.

Wave 2 slice 12 adds two truth labels on top of that set:

* **instrument_id** (12) — a non-cash row whose ``symbol`` field is not a
  ticker (``12507E201``, ``543354104``, ``628518102``) is an *instrument id*,
  not a ticker. It is reported under ``instrument_id`` with ``id_type`` so no
  surface renders a CUSIP where a ticker belongs.
* **DUST_RESIDUAL** (12a) — a ticker whose aggregate market value across
  accounts is below ``DUST_MAX_MARKET_VALUE_USD`` is a residual, not a hold.
  See ``DUST_POLICY``. Lots are never deleted; only the *label* changes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HoldingsUniverse@v1"

CASH_SYMBOLS = frozenset({"CASH", "USD", "SPAXX", "VMFXX", "FDRXX", "TEST"})

# ── Wave 2 slice 12a — documented DUST policy ────────────────────────────────
# Threshold is ABSOLUTE MARKET VALUE, not portfolio weight.
#
# Weight was rejected: at a $1.29M book, "weight < 0.5%" would label AMANX
# ($5,164 / 0.40%) and the taxable SPCX sleeve ($5,458 / 0.42%) as dust. Those
# are real positions. A flat $50 floor separates a residual share left behind
# by a sale (SCHG $8.09, SRNE $0.90) from a small but deliberate holding.
#
# Aggregated PER TICKER across accounts, so a name held small in one account
# and large in another is never called dust.
#
# Unknown/missing market value is NOT dust — a position is never dropped from
# coverage merely because its price is missing. Fail-open to HELD, honestly.
DUST_MAX_MARKET_VALUE_USD = 50.0
DUST_STATUS = "DUST_RESIDUAL"
HELD_STATUS = "HELD"

DUST_POLICY = {
    "policy_id": "dust_residual@v1",
    "rule": "aggregate market_value across accounts < $50.00 per ticker",
    "threshold_usd": DUST_MAX_MARKET_VALUE_USD,
    "basis": "market_value",
    "aggregation": "per_ticker_across_accounts",
    "rejected_alternative": "portfolio weight < 0.5% (would mislabel AMANX and SPCX)",
    "unknown_market_value": "treated as HELD, never dust",
    "effect": "excluded from held_n / thesis coverage / observational S1; label only",
    "deletes_lots": False,
    "fixture": "SCHG",
    "authority": AUTHORITY,
}


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


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Wave 2 slice 12: instrument_id, not ticker ───────────────────────────────

def classify_instrument_id(raw: str) -> str:
    """Label a non-ticker held identifier. Never returns "TICKER"."""
    t = str(raw or "").strip().upper()
    if len(t) == 9 and t[:8].isalnum() and t[8].isdigit():
        return "CUSIP"
    if len(t) == 12 and t[:2].isalpha() and t[2:].isalnum():
        return "ISIN"
    return "UNKNOWN_INSTRUMENT_ID"


def held_instrument_id_rows(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Held non-cash rows whose symbol field carries an instrument id, not a ticker.

    The holdings feed puts a CUSIP in the ``symbol`` column. Every consumer that
    reads ``symbol`` as a ticker is wrong for these rows, so they are surfaced
    under ``instrument_id`` with an explicit ``id_type`` and ``is_ticker=False``.
    """
    out: list[dict[str, Any]] = []
    for r in held_position_rows(root=root):
        if is_cash_row(r):
            continue
        raw = str(r.get("symbol") or "").strip().upper()
        if not raw or is_held_equity_ticker(raw):
            continue
        out.append({
            "instrument_id": raw,
            "id_type": classify_instrument_id(raw),
            "is_ticker": False,
            "ticker": None,
            "symbol_field_value": raw,
            "account": r.get("account") or r.get("account_id"),
            "shares": _num(r.get("shares") if r.get("shares") is not None else r.get("quantity")),
            "market_value": _num(r.get("market_value")),
            "name": r.get("name"),
            "note": "instrument_id — resolve before any surface renders this as a ticker",
        })
    out.sort(key=lambda x: (str(x["instrument_id"]), str(x.get("account") or "")))
    return out


# ── Wave 2 slice 12a: DUST_RESIDUAL ──────────────────────────────────────────

def held_market_value_by_ticker(*, root: Path | None = None) -> dict[str, Optional[float]]:
    """Aggregate market value per held equity ticker. ``None`` = value unknown.

    One leg with an unknown market value makes the whole aggregate unknown, so
    a name is never called dust on the strength of the accounts that happened
    to price.
    """
    known: dict[str, float] = {}
    unknown: set[str] = set()
    for r in held_position_rows(root=root):
        if is_cash_row(r):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        if not is_held_equity_ticker(sym):
            continue
        known.setdefault(sym, 0.0)
        mv = _num(r.get("market_value"))
        if mv is None:
            unknown.add(sym)
        else:
            known[sym] += mv
    return {sym: (None if sym in unknown else total) for sym, total in known.items()}


def is_dust_market_value(market_value: Any) -> bool:
    """True only when the value is KNOWN and below the documented floor."""
    mv = _num(market_value)
    return mv is not None and mv < DUST_MAX_MARKET_VALUE_USD


def held_dust_tickers(*, root: Path | None = None) -> list[str]:
    """Held tickers that are residual, not positions. SCHG is the fixture."""
    totals = held_market_value_by_ticker(root=root)
    return sorted(s for s, mv in totals.items() if is_dust_market_value(mv))


def held_equity_tickers_nondust(*, root: Path | None = None) -> list[str]:
    """Coverage denominator after slice 12a: held tickers minus DUST_RESIDUAL."""
    dust = set(held_dust_tickers(root=root))
    return [s for s in held_equity_tickers(root=root) if s not in dust]


def dust_status_for(symbol: str, totals: dict[str, Optional[float]]) -> str:
    return DUST_STATUS if is_dust_market_value(totals.get(str(symbol).upper())) else HELD_STATUS


def dust_table(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Per-ticker dry table: ticker, aggregate market value, HELD | DUST_RESIDUAL."""
    totals = held_market_value_by_ticker(root=root)
    return [
        {
            "symbol": sym,
            "market_value": totals.get(sym),
            "holding_status": dust_status_for(sym, totals),
            "threshold_usd": DUST_MAX_MARKET_VALUE_USD,
        }
        for sym in sorted(totals)
    ]


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
    instrument_ids = held_instrument_id_rows(root=root)
    dust = held_dust_tickers(root=root)
    nondust = [s for s in tickers if s not in set(dust)]
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
        # Wave 2 slice 12 — CUSIP-ish rows labeled instrument_id, never ticker.
        "instrument_ids": instrument_ids,
        "instrument_id_n": len(instrument_ids),
        # Wave 2 slice 12a — dust is a label, not a deletion.
        "dust_policy": DUST_POLICY,
        "dust_tickers": dust,
        "dust_n": len(dust),
        "dust_table": dust_table(root=root),
        "held_equity_tickers": tickers,
        "held_equity_ticker_n": len(tickers),
        "held_equity_tickers_nondust": nondust,
        "held_equity_ticker_nondust_n": len(nondust),
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
