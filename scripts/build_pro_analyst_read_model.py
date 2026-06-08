#!/usr/bin/env python3
"""build_pro_analyst_read_model.py — Gate A: unified professional-analyst read model + coverage + divergence.

ADVISORY/READ-ONLY. One row per symbol (actionable + held universe) combining:
  - Yahoo analyst consensus (PREFERRED): recommendation_key/mean, analyst count, targets, upside.
  - Finviz target_price (SUPPLEMENTAL only — its rating is target-distance, NOT consensus; never used as rating).
  - Latest analyst_upgrade/analyst_downgrade catalyst headline (EVENT pill, not consensus).
  - Internal-vs-professional divergence (fused_signals direction vs Street consensus): aligned/mixed/divergent/unavailable.
  - confidence, stale flag, raw provenance.
Writes data/runtime/pro_analyst_pills_latest.json (+ coverage by tier). No scoring/trade/holdings change.
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"
STALE_DAYS = 7
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2
import psycopg2.extras


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"), cursor_factory=psycopg2.extras.RealDictCursor)


def main():
    c = _db(); cur = c.cursor()
    # universe with tier membership
    cur.execute("""
        SELECT symbol,
          bool_or(src='held') held, bool_or(src='paper') open_paper, bool_or(src='proposal') open_proposal,
          bool_or(src='scalp') scalp, bool_or(src='watch') watchlist
        FROM (
          SELECT symbol,'paper' src FROM paper_trades WHERE entry_time>now()-interval '30 days' AND symbol IS NOT NULL
          UNION ALL SELECT symbol,'proposal' FROM paper_trade_proposals WHERE status IN('PENDING','APPROVED') AND symbol IS NOT NULL
          UNION ALL SELECT symbol,'scalp' FROM trade_ai_scans WHERE run_date>=current_date AND decision IN('GO','WAIT') AND symbol IS NOT NULL
          UNION ALL SELECT symbol,'watch' FROM watchlist_items WHERE status='active' AND symbol IS NOT NULL
          UNION ALL SELECT symbol,'held' FROM watchlist_items WHERE source='portfolio' AND status<>'removed' AND symbol IS NOT NULL
        ) u GROUP BY symbol""")
    universe = {r["symbol"]: r for r in cur.fetchall()}

    def latest_yahoo(sym):
        cur.execute("""SELECT recommendation_key, recommendation_mean, number_of_analyst_opinions,
                       target_mean_price, target_high_price, target_low_price, target_median_price,
                       current_price, created_at FROM yahoo_analyst_targets_history
                       WHERE symbol=%s ORDER BY created_at DESC LIMIT 1""", (sym,))
        return cur.fetchone()

    def finviz_target(sym):
        cur.execute("""SELECT target_price, created_at FROM analyst_consensus_history
                       WHERE symbol=%s AND target_price IS NOT NULL AND target_price > 0 ORDER BY created_at DESC LIMIT 1""", (sym,))
        return cur.fetchone()

    def latest_event(sym):
        cur.execute("""SELECT catalyst_type, headline, source, created_at FROM catalyst_events
                       WHERE symbol=%s AND catalyst_type IN ('analyst_upgrade','analyst_downgrade','analyst')
                       ORDER BY created_at DESC LIMIT 1""", (sym,))
        return cur.fetchone()

    def internal_dir(sym):
        cur.execute("SELECT direction FROM fused_signals WHERE symbol=%s ORDER BY created_at DESC LIMIT 1", (sym,))
        r = cur.fetchone()
        return (r["direction"] or "").lower() if r else None

    now = datetime.now(timezone.utc)
    pills, cov = [], {"held": [0, 0], "open_paper": [0, 0], "open_proposal": [0, 0], "scalp": [0, 0], "watchlist": [0, 0]}
    for sym, mem in universe.items():
        y = latest_yahoo(sym)
        fv = finviz_target(sym)
        ev = latest_event(sym)
        idir = internal_dir(sym)
        has_consensus = bool(y and (y["recommendation_key"] not in (None, "none") or y["number_of_analyst_opinions"]))
        upside = None
        if y and y["target_mean_price"] and y["current_price"] and float(y["current_price"]) > 0:
            upside = round((float(y["target_mean_price"]) - float(y["current_price"])) / float(y["current_price"]) * 100, 1)
        stale = bool(y and (now - y["created_at"]).days > STALE_DAYS)
        # divergence: street (from recommendation_key) vs internal fused direction
        street = None
        if y and y["recommendation_key"] and y["recommendation_key"] != "none":
            street = "bullish" if "buy" in y["recommendation_key"] else "bearish" if "sell" in y["recommendation_key"] or "underperform" in y["recommendation_key"] else "neutral"
        if not street or not idir:
            divergence = "unavailable"
        elif street == idir:
            divergence = "aligned"
        elif "neutral" in (street, idir):
            divergence = "mixed"
        else:
            divergence = "divergent"
        pill = {
            "symbol": sym, "tiers": [k for k in ("held", "open_paper", "open_proposal", "scalp", "watchlist") if mem.get(k)],
            "analyst_rating_source": "yahoo" if has_consensus else ("finviz_target" if fv else "none"),
            "recommendation_key": (y or {}).get("recommendation_key") if has_consensus else None,
            "recommendation_mean": float(y["recommendation_mean"]) if (y and y["recommendation_mean"] is not None) else None,
            "number_of_analyst_opinions": (y or {}).get("number_of_analyst_opinions"),
            "target_mean_price": float(y["target_mean_price"]) if (y and y["target_mean_price"]) else (float(fv["target_price"]) if fv and fv["target_price"] else None),
            "target_high_price": float(y["target_high_price"]) if (y and y["target_high_price"]) else None,
            "target_low_price": float(y["target_low_price"]) if (y and y["target_low_price"]) else None,
            "current_price": float(y["current_price"]) if (y and y["current_price"]) else None,
            "upside_to_mean_target_pct": upside,
            "latest_event_headline": (ev or {}).get("headline"),
            "latest_event_type": (ev or {}).get("catalyst_type"),
            "latest_event_source": (ev or {}).get("source"),
            "latest_event_at": str(ev["created_at"]) if ev else None,
            "internal_direction": idir, "street_direction": street, "divergence": divergence,
            "confidence": "high" if (has_consensus and (y["number_of_analyst_opinions"] or 0) >= 5 and not stale)
                          else "low" if has_consensus else "none",
            "stale": stale, "has_professional_coverage": has_consensus,
            "provenance": {"yahoo_at": str(y["created_at"]) if y else None, "finviz_at": str(fv["created_at"]) if fv else None},
        }
        pills.append(pill)
        for k in cov:
            if mem.get(k):
                cov[k][0] += 1
                if has_consensus:
                    cov[k][1] += 1
    c.close()
    coverage = {k: {"symbols": v[0], "with_consensus": v[1], "pct": round(v[1] / v[0] * 100, 1) if v[0] else 0.0} for k, v in cov.items()}
    out = {"updated_at": now.isoformat(), "stale_days": STALE_DAYS, "symbol_count": len(pills),
           "coverage_by_tier": coverage,
           "note": "Yahoo = authoritative consensus (1-5 mean/key/targets). Finviz rating is target-distance (NOT used as rating; target only). "
                   "Upgrade/downgrade headlines are EVENT pills. Advisory; no scoring/trade change.",
           "pills": sorted(pills, key=lambda p: (not p["has_professional_coverage"], p["symbol"]))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({"symbols": len(pills), "coverage_by_tier": coverage,
                      "with_consensus": sum(1 for p in pills if p["has_professional_coverage"]),
                      "divergent": sum(1 for p in pills if p["divergence"] == "divergent")}, indent=2))


if __name__ == "__main__":
    main()
