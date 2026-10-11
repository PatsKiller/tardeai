#!/usr/bin/env python3
"""Supplemental valuation feed for Watch symbols Finviz never enriched.

The Watch queue reads valuation off the Finviz strip map, which is built only from the
symbols that appear in the Finviz screeners the system runs. Legitimate stocks that are
watchlist favorites but sit in no screener — CARR, LII, LI, TLRY and hundreds more —
therefore have no P/E and render "valuation unavailable".

This backfills those names from yfinance (already a project dependency) into a supplement
cache that _finviz_strip_map_compute merges as a per-field fallback, exactly like the
existing yfinance-NAV fallback for mutual funds. The Finviz row still wins wherever it has
data; the supplement only fills the gaps.

Design constraints that matter:
  * Read-only against the DB. Writes one runtime-state JSON, nothing else.
  * Non-equities (ETFs, funds) are negative-cached with quote_type but no valuation, so a
    single yfinance call classifies them once and they are never refetched. asset_type in
    the DB is almost always null, so quote_type from the feed is the reliable ETF filter.
  * Resumable and capped. yfinance is slow and rate-limited, so a run processes at most
    --limit fresh symbols and a daily cron chips away at the tail. Symbols fetched within
    the freshness window are skipped.
  * Missing stays missing. A name with no trailing earnings keeps pe=None (the UI shows
    that honestly); nothing is fabricated.

Usage:
    python scripts/watch_valuation_backfill.py [--limit N] [--max-age-days D] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db_adapter import _execute as ex  # noqa: E402

STATE = ROOT / "data" / "state"
FINVIZ_CACHE = STATE / "ticker_enrichment_cache.json"
SUPPLEMENT = STATE / "valuation_supplement_cache.json"
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")
FRESH_DEFAULT_DAYS = 7
# yfinance occasionally returns absurd ratios; anything past these is treated as no data
# rather than published. Kept generous so a real high-multiple name (CECO at 213) survives.
SANE_MAX = 100_000.0


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or abs(f) > SANE_MAX:  # NaN or absurd
        return None
    return f


def watch_universe() -> list[str]:
    """Same union the strip map serves: watchlist + open proposals + held positions."""
    syms: set[str] = set()
    syms |= {r["symbol"] for r in (ex(
        "SELECT DISTINCT symbol FROM watchlist_items "
        "WHERE status<>'removed' AND symbol ~ '^[A-Z]{1,5}$'", fetch="all") or [])}
    syms |= {r["symbol"] for r in (ex(
        "SELECT DISTINCT symbol FROM paper_trade_proposals "
        "WHERE status IN ('PENDING','APPROVED') AND symbol ~ '^[A-Z]{1,5}$'", fetch="all") or [])}
    try:
        holdings = _load(ROOT / "data" / "portfolios" / "state" / "holdings.json")
        for h in holdings.get("holdings", []):
            s = str(h.get("symbol", "")).upper()
            if s and not h.get("is_cash") and SYMBOL_RE.match(s):
                syms.add(s)
    except Exception:
        pass
    return sorted(syms)


def priority_order(syms: list[str]) -> list[str]:
    """Active, recently-seen watchlist names first — that is the operator surface."""
    rank: dict[str, int] = {}
    rows = ex("""SELECT upper(symbol) s, status, last_seen_at
                 FROM watchlist_items WHERE upper(symbol) = ANY(%s)""", (syms,), fetch="all") or []
    for r in rows:
        active = 0 if r.get("status") == "active" else 1
        seen = r.get("last_seen_at")
        # newer last_seen sorts first within the active tier
        key = (active, -(seen.timestamp() if hasattr(seen, "timestamp") else 0))
        prev = rank.get(r["s"])
        if prev is None or key < prev:
            rank[r["s"]] = key
    return sorted(syms, key=lambda s: rank.get(s, (2, 0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=250,
                    help="max fresh yfinance fetches this run (resumable across runs)")
    ap.add_argument("--max-age-days", type=int, default=FRESH_DEFAULT_DAYS)
    ap.add_argument("--sleep", type=float, default=0.7, help="seconds between yfinance calls")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    finviz = _load(FINVIZ_CACHE)
    supplement = _load(SUPPLEMENT)
    now = dt.datetime.now(dt.timezone.utc)

    def is_fresh(sym: str) -> bool:
        row = supplement.get(sym)
        if not row or not row.get("cached_at"):
            return False
        try:
            age = (now - dt.datetime.fromisoformat(row["cached_at"])).days
        except Exception:
            return False
        return age <= args.max_age_days

    universe = watch_universe()
    # Uncovered = Finviz strip has no trailing and no forward P/E for the name.
    uncovered = [s for s in universe
                 if (finviz.get(s) or {}).get("pe") is None
                 and (finviz.get(s) or {}).get("forward_pe") is None]
    todo = [s for s in priority_order(uncovered) if not is_fresh(s)]

    print(f"universe={len(universe)} uncovered={len(uncovered)} "
          f"already_fresh={len(uncovered) - len(todo)} to_fetch={min(len(todo), args.limit)}")
    if args.dry_run:
        print("sample to_fetch:", todo[:20])
        return 0

    try:
        import yfinance as yf
    except Exception as error:
        print(f"yfinance unavailable: {error}", file=sys.stderr)
        return 1

    fetched = equities = non_equity = errors = 0
    for sym in todo[:args.limit]:
        try:
            info = yf.Ticker(sym).get_info() or {}
        except Exception as error:
            errors += 1
            print(f"  {sym}: ERROR {str(error)[:80]}", file=sys.stderr)
            time.sleep(args.sleep)
            continue
        fetched += 1
        quote_type = str(info.get("quoteType") or "").upper()
        stamp = now.isoformat()
        if quote_type and quote_type != "EQUITY":
            # Negative-cache: classified once, never refetched, and the strip map still
            # marks it N/A rather than missing.
            supplement[sym] = {"quote_type": quote_type, "no_valuation": True, "cached_at": stamp,
                               "source": "yfinance"}
            non_equity += 1
        else:
            mc = _num(info.get("marketCap"))
            supplement[sym] = {
                "pe": _num(info.get("trailingPE")),
                "forward_pe": _num(info.get("forwardPE")),
                "peg": _num(info.get("trailingPegRatio")) or _num(info.get("pegRatio")),
                "pb": _num(info.get("priceToBook")),
                "ps": _num(info.get("priceToSalesTrailing12Months")),
                "market_cap_b": round(mc / 1e9, 4) if mc is not None else None,
                "quote_type": quote_type or "EQUITY",
                "cached_at": stamp,
                "source": "yfinance",
            }
            equities += 1
        time.sleep(args.sleep)

    SUPPLEMENT.parent.mkdir(parents=True, exist_ok=True)
    tmp = SUPPLEMENT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(supplement, default=str))
    tmp.replace(SUPPLEMENT)

    with_val = sum(1 for r in supplement.values()
                   if not r.get("no_valuation") and r.get("pe") is not None)
    print(f"fetched={fetched} equities={equities} non_equity={non_equity} errors={errors}")
    print(f"supplement now holds {len(supplement)} symbols; {with_val} with a trailing P/E")
    print(f"remaining uncovered to backfill on later runs: {max(0, len(todo) - args.limit)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
