#!/usr/bin/env python3
"""analyst_coverage.py — Analyst rating + price-target gate for proposals and symbol cards.

Ensures equities have Yahoo consensus (rating + target_mean) before proposal promotion.
ETFs/funds in etf_classification_overrides.json are exempt. On-demand fetch via yfinance
when DB is missing or stale.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("analyst_coverage")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ETF_OVERRIDES_PATH = PROJECT_ROOT / "config" / "etf_classification_overrides.json"
MAX_ANALYST_AGE_DAYS = 45
_FIDELITY_PFX = ("FID-", "SS-", "TRP-", "JPM-", "VANG-", "WM-", "AB-", "SP500-", "CASH", "FCNTX")


def _load_etf_overrides() -> dict:
    if not ETF_OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(ETF_OVERRIDES_PATH.read_text())
        symbols = data.get("symbols", {}) if isinstance(data, dict) else {}
        return {str(k).upper(): v for k, v in symbols.items() if isinstance(v, dict)}
    except Exception:
        return {}


def is_analyst_exempt(symbol: str, conn=None, instrument_type: str | None = None) -> bool:
    """True when sell-side analyst consensus does not apply (ETF/fund/bond baskets)."""
    sym = (symbol or "").upper()
    if not sym or sym.startswith(_FIDELITY_PFX):
        return True
    ov = _load_etf_overrides().get(sym)
    if ov and ov.get("analyst_required") is False:
        return True
    if instrument_type in ("etf", "fund", "inverse_etf", "bond_etf", "sector_etf", "broad_index_etf"):
        return True
    if conn is not None:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT instrument_type, analyst_look_through_pct FROM symbol_profiles WHERE upper(symbol)=%s",
                (sym,),
            )
            row = cur.fetchone()
            if row:
                itype, look_through = row[0], row[1]
                if itype in ("etf", "fund", "inverse_etf"):
                    return True
                if look_through is not None:
                    return False  # ETF with look-through still needs analyst block on card
        except Exception:
            pass
    return False


def get_analyst_snapshot(conn, symbol: str) -> Optional[dict]:
    """Latest Yahoo analyst row for symbol, or None."""
    sym = (symbol or "").upper()
    if not sym:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT symbol, recommendation_key, recommendation_mean, number_of_analyst_opinions,
                   target_mean_price, target_high_price, target_low_price, current_price, created_at
            FROM yahoo_analyst_targets_history
            WHERE upper(symbol) = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (sym,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        snap = dict(zip(cols, row))
        snap["symbol"] = sym
        return snap
    except Exception as exc:
        log.debug("%s: analyst snapshot read failed — %s", sym, exc)
        return None


def _snapshot_has_coverage(snap: dict | None) -> bool:
    if not snap:
        return False
    rating = snap.get("recommendation_key")
    target = snap.get("target_mean_price")
    if rating in (None, "", "none") and snap.get("recommendation_mean") is None:
        return False
    if target is None or float(target or 0) <= 0:
        return False
    return True


def _snapshot_age_days(snap: dict | None) -> float | None:
    if not snap:
        return None
    created = snap.get("created_at")
    if not created:
        return None
    try:
        if hasattr(created, "timestamp"):
            dt = created if getattr(created, "tzinfo", None) else created.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return None


def analyst_card_block(snap: dict) -> dict:
    """Format analyst snapshot for symbol-cards / proposal context."""
    tm = snap.get("target_mean_price")
    cp = snap.get("current_price")
    upside = None
    if tm and cp and float(cp) > 0:
        upside = round((float(tm) - float(cp)) / float(cp) * 100, 1)
    return {
        "rating": snap.get("recommendation_key"),
        "mean": snap.get("recommendation_mean"),
        "opinions": snap.get("number_of_analyst_opinions"),
        "target": tm,
        "target_high": snap.get("target_high_price"),
        "target_low": snap.get("target_low_price"),
        "upside_pct": upside,
        "sources": ["yahoo"],
        "updated_at": snap.get("created_at"),
    }


def fetch_analyst_yahoo(symbol: str) -> Optional[dict]:
    """Fetch single-symbol Yahoo analyst consensus. Returns payload dict or None."""
    sym = (symbol or "").upper()
    if not sym or is_analyst_exempt(sym):
        return None
    try:
        import yfinance as yf
        info = yf.Ticker(sym).info
        tm = info.get("targetMeanPrice")
        nop = info.get("numberOfAnalystOpinions")
        rk = info.get("recommendationKey")
        if tm is None and not nop and not rk:
            return None
        return {
            "symbol": sym,
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "target_mean_price": tm,
            "target_high_price": info.get("targetHighPrice"),
            "target_low_price": info.get("targetLowPrice"),
            "target_median_price": info.get("targetMedianPrice"),
            "recommendation_mean": info.get("recommendationMean"),
            "recommendation_key": rk,
            "number_of_analyst_opinions": nop,
        }
    except Exception as exc:
        log.warning("%s: Yahoo analyst fetch failed — %s", sym, exc)
        return None


def persist_analyst_payload(payload: dict) -> bool:
    if not payload:
        return False
    try:
        from db_adapter import save_yahoo_analyst_targets_history
        date_str = datetime.now().strftime("%Y-%m-%d")
        save_yahoo_analyst_targets_history(date_str, [payload])
        return True
    except Exception as exc:
        log.warning("%s: analyst persist failed — %s", payload.get("symbol"), exc)
        return False


def ensure_analyst_for_symbol(
    conn,
    symbol: str,
    *,
    fetch_if_missing: bool = True,
    max_age_days: float = MAX_ANALYST_AGE_DAYS,
) -> Tuple[bool, Optional[dict], str]:
    """Ensure analyst rating + target exist. Returns (ok, snapshot, reason)."""
    sym = (symbol or "").upper()
    if is_analyst_exempt(sym, conn=conn):
        return True, None, "analyst_exempt"

    snap = get_analyst_snapshot(conn, sym)
    age = _snapshot_age_days(snap)
    needs_fetch = not _snapshot_has_coverage(snap) or (age is not None and age > max_age_days)

    if needs_fetch and fetch_if_missing:
        payload = fetch_analyst_yahoo(sym)
        if payload and persist_analyst_payload(payload):
            snap = get_analyst_snapshot(conn, sym)

    if not _snapshot_has_coverage(snap):
        return False, snap, "missing_analyst_rating_or_target"

    return True, snap, "ok"


def check_analyst_gate(conn, symbol: str, *, fetch_if_missing: bool = True) -> Tuple[bool, str, Optional[dict]]:
    """Proposal gate: require rating + target_mean for equities."""
    ok, snap, reason = ensure_analyst_for_symbol(conn, symbol, fetch_if_missing=fetch_if_missing)
    if ok:
        return True, reason, snap
    return False, reason, snap


def ensure_analyst_batch(conn, symbols: list[str], *, limit: int = 25) -> dict:
    """On-demand enrich a batch of symbols (symbol-cards hook)."""
    enriched = skipped = failed = 0
    details = []
    for sym in symbols[:limit]:
        sym = (sym or "").upper()
        if not sym:
            continue
        if is_analyst_exempt(sym, conn=conn):
            skipped += 1
            continue
        ok, snap, reason = ensure_analyst_for_symbol(conn, sym, fetch_if_missing=True)
        if ok and snap:
            enriched += 1
            details.append({"symbol": sym, "status": "enriched", "rating": snap.get("recommendation_key")})
        elif ok:
            skipped += 1
        else:
            failed += 1
            details.append({"symbol": sym, "status": "failed", "reason": reason})
    return {"enriched": enriched, "skipped": skipped, "failed": failed, "details": details}


# Junk listicle catalyst patterns — not valid trade catalysts
_JUNK_CATALYST_RE = re.compile(
    r"(?i)(?:"
    r"top\s+\d+\s+stocks|best\s+stocks?\s+to\s+buy|stocks?\s+to\s+watch|"
    r"these\s+\d+\s+stocks|hottest\s+stocks|stocks?\s+under\s+\$\d+|"
    r"penny\s+stocks?\s+to|must[- ]buy\s+stocks|stocks?\s+set\s+to\s+soar|"
    r"wall\s+street\s+analysts?\s+love|analysts?\s+recommend\s+these|"
    r"why\s+you\s+should\s+buy|stocks?\s+that\s+could\s+double"
    r")",
)


def is_junk_catalyst(catalyst: str | None) -> bool:
    if not catalyst:
        return False
    return bool(_JUNK_CATALYST_RE.search(str(catalyst)))


if __name__ == "__main__":
    import argparse
    import os
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Analyst coverage gate / fetch")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()

    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD"),
    )
    ok, snap, reason = ensure_analyst_for_symbol(conn, args.symbol, fetch_if_missing=args.fetch)
    print(json.dumps({
        "symbol": args.symbol.upper(),
        "ok": ok,
        "reason": reason,
        "snapshot": {k: str(v) if hasattr(v, "isoformat") else v for k, v in (snap or {}).items()},
        "card": analyst_card_block(snap) if snap else None,
    }, indent=2, default=str))
    conn.close()