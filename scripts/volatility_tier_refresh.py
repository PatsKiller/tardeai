#!/usr/bin/env python3
"""volatility_tier_refresh — daily volatility-tier classification (advisory only).

Classifies every held + watch-universe symbol into low/medium/high volatility
using classify_volatility_tier (beta / real ATR% / dividend yield / sector — rules
in config/stop_policy.yaml, NO hardcoded symbols) and stores the result in:
  - data/state/volatility_tiers_latest.json  (read by holding_family.volatility_tier)
  - symbol_volatility_tiers DB table          (queryable history/provenance)

Inputs: data/state/ticker_enrichment_cache.json (finviz beta/atr$/yield/sector,
refreshed by finviz_enrichment) + live prices from market_quotes / holdings.json
so ATR$ becomes a real ATR%. Never touches orders or stops — pure classification.

Usage: .venv/bin/python scripts/volatility_tier_refresh.py [--quiet]
Cron:  daily 06:45 (after the 06:40 symbol-cards refresh, before market open).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STATE_OUT = ROOT / "data" / "state" / "volatility_tiers_latest.json"

DDL = """CREATE TABLE IF NOT EXISTS symbol_volatility_tiers (
    symbol TEXT PRIMARY KEY,
    tier TEXT NOT NULL CHECK (tier IN ('low','medium','high')),
    beta NUMERIC, atr_pct NUMERIC, div_yield_pct NUMERIC, sector TEXT,
    source TEXT, computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""


def _symbols() -> set[str]:
    """Held symbols + watch universe (both fail-soft)."""
    syms: set[str] = set()
    try:
        for h in json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json")
                            .read_text()).get("holdings", []):
            s = str(h.get("symbol") or "").upper()
            if s and s != "CASH":
                syms.add(s)
    except Exception:
        pass
    try:
        wu = json.loads((ROOT / "data" / "state" / "watch_universe.json").read_text())
        rows = wu.get("symbols") or wu.get("items") or wu
        for r in (rows if isinstance(rows, list) else []):
            s = str((r.get("symbol") if isinstance(r, dict) else r) or "").upper()
            if s:
                syms.add(s)
    except Exception:
        pass
    return syms


def _prices(syms: set[str]) -> dict[str, float]:
    """Live price per symbol: market_quotes first, holdings.json as fallback."""
    px: dict[str, float] = {}
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT ON (UPPER(symbol)) UPPER(symbol), price
                       FROM market_quotes WHERE UPPER(symbol) = ANY(%s)
                       ORDER BY UPPER(symbol), quoted_at DESC""", (list(syms),))
        for s, p in cur.fetchall():
            if p:
                px[s] = float(p)
        conn.rollback()
    except Exception:
        pass
    try:
        for h in json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json")
                            .read_text()).get("holdings", []):
            s = str(h.get("symbol") or "").upper()
            p = h.get("current_price") or h.get("price")
            if s and p and s not in px:
                px[s] = float(p)
    except Exception:
        pass
    return px


def main() -> int:
    quiet = "--quiet" in sys.argv
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
    import holding_family as hf

    cache = json.loads((ROOT / "data" / "state" / "ticker_enrichment_cache.json")
                       .read_text())
    syms = _symbols()
    px = _prices(syms)
    now = datetime.now(timezone.utc).isoformat()

    tiers: dict[str, dict] = {}
    counts = {"low": 0, "medium": 0, "high": 0, "no_data": 0}
    for s in sorted(syms):
        rec = cache.get(s) or {}
        beta = rec.get("beta")
        atr_d = rec.get("atr")
        price = px.get(s)
        atr_pct = (float(atr_d) / price * 100) if (atr_d and price) else None
        tier = hf.classify_volatility_tier(beta, atr_pct,
                                           rec.get("div_yield_pct"), rec.get("sector"))
        if not tier:
            counts["no_data"] += 1
            continue
        counts[tier] += 1
        tiers[s] = {"tier": tier, "beta": beta,
                    "atr_pct": round(atr_pct, 2) if atr_pct else None,
                    "div_yield_pct": rec.get("div_yield_pct"),
                    "sector": rec.get("sector"), "source": "volatility_tier_refresh",
                    "computed_at": now}

    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps(
        {"generated_at": now, "policy_version": hf._policy().get("version"),
         "counts": counts, "tiers": tiers}, indent=1))

    db_n = 0
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(DDL)
        for s, r in tiers.items():
            cur.execute("""INSERT INTO symbol_volatility_tiers
                             (symbol, tier, beta, atr_pct, div_yield_pct, sector, source, computed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                           ON CONFLICT (symbol) DO UPDATE SET tier=EXCLUDED.tier,
                             beta=EXCLUDED.beta, atr_pct=EXCLUDED.atr_pct,
                             div_yield_pct=EXCLUDED.div_yield_pct, sector=EXCLUDED.sector,
                             source=EXCLUDED.source, computed_at=NOW()""",
                        (s, r["tier"], r["beta"], r["atr_pct"],
                         r["div_yield_pct"], r["sector"], r["source"]))
            db_n += 1
        conn.commit()
    except Exception as e:
        print(f"volatility_tier_refresh: DB upsert skipped ({e})", file=sys.stderr)

    if not quiet:
        print(f"volatility_tier_refresh: {len(tiers)} classified "
              f"(low {counts['low']} · medium {counts['medium']} · high {counts['high']} · "
              f"no-data {counts['no_data']}) · db rows {db_n} · {STATE_OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
