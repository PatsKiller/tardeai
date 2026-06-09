#!/usr/bin/env python3
# phase2_sector_resolver.py
# Resolves sector/industry for every ticker using priority chain:
# 1. manual_sector_map.json (highest trust — handles Fidelity proprietary funds)
# 2. finvizfinance classification
# 3. yfinance classification
# 4. Finviz API data (from v=152 which returns sector)
# 5. "Other / Unclassified" fallback
# Writes resolved_sectors to holdings.json for CC sector widget fallback.

from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path


def _safe_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def resolve_sector(rec: dict, manual_map: dict) -> tuple:
    """Returns (sector, industry, source)."""
    sym = rec.get("symbol", "")

    # Priority 1: manual map (Fidelity proprietary funds etc.)
    if sym in manual_map:
        entry = manual_map[sym]
        return entry.get("sector", "Other"), entry.get("industry", ""), "manual_map"

    c = rec.get("classification", {}) or {}
    f = rec.get("fundamentals", {}) or {}

    # Priority 2: finvizfinance classification
    if c.get("fv_sector"):
        return c["fv_sector"], c.get("fv_industry", ""), "fv_classification"

    # Priority 3: yfinance classification
    if c.get("yf_sector"):
        return c["yf_sector"], c.get("yf_industry", ""), "yf_classification"

    # Priority 4: fundamentals bucket (finvizfinance stores it there sometimes)
    if f.get("fv_sector"):
        return f["fv_sector"], f.get("fv_industry", ""), "fv_fundamentals"
    if f.get("yf_sector"):
        return f["yf_sector"], f.get("yf_industry", ""), "yf_fundamentals"

    # Priority 5: Finviz API v=152 returns sector in column 3
    # This is stored in the finviz_quote_cache if present
    if c.get("sector"):
        return c["sector"], c.get("industry", ""), "finviz_cache"

    return "Other / Unclassified", "", "fallback"


def main():
    ap = argparse.ArgumentParser(description="Phase 2 sector resolver")
    ap.add_argument("--project-root", required=True)
    args = ap.parse_args()
    project_root = Path(args.project_root)
    state_dir = project_root / "data" / "portfolios" / "state"
    log_dir = project_root / "logs" / "phase2"
    log_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = state_dir / "ticker_snapshot_latest.json"
    holdings_path = state_dir / "holdings.json"
    manual_map    = _safe_json(state_dir / "manual_sector_map.json", {})
    data          = _safe_json(snapshot_path, {"_meta": {}, "tickers": {}})
    holdings      = _safe_json(holdings_path, {})

    unresolved = []
    bucket = defaultdict(float)
    resolution_log = []

    tickers = data.get("tickers", {})
    for sym, rec in tickers.items():
        rec.setdefault("symbol", sym)
        rec.setdefault("resolved", {})

        sector, industry, source = resolve_sector(rec, manual_map)
        rec["resolved"]["sector"]   = sector
        rec["resolved"]["industry"] = industry
        rec["resolved"]["source"]   = source

        mv = float((rec.get("holdings_context", {}) or {})
                   .get("market_value_total") or 0)
        if mv > 0:
            bucket[sector] += mv

        resolution_log.append({
            "symbol":  sym,
            "sector":  sector,
            "industry": industry,
            "source":  source,
            "market_value": mv,
        })

        if source == "fallback":
            unresolved.append({"symbol": sym, "market_value": mv})

    total = sum(bucket.values()) or 0.0
    resolved_sectors = []
    for sector, value in sorted(bucket.items(), key=lambda x: x[1], reverse=True):
        resolved_sectors.append({
            "sector": sector,
            "value":  round(value, 2),
            "pct":    round((value / total * 100) if total else 0, 2),
        })

    # Write resolved_sectors into holdings.json
    holdings["resolved_sectors"] = resolved_sectors
    from holdings_guard import protected_holdings_write  # MANDATORY wipe-guard
    protected_holdings_write(holdings, source="phase2_sector_resolver", target_path=str(holdings_path))

    # Write updated snapshot
    data["_meta"]["phase2_sectors_resolved_at"] = \
        __import__("datetime").datetime.now().isoformat()
    snapshot_path.write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8")

    # Write logs
    (log_dir / "phase2_unresolved_sectors.json").write_text(
        json.dumps(unresolved, indent=2, default=str), encoding="utf-8")
    (log_dir / "phase2_resolution_log.json").write_text(
        json.dumps(resolution_log, indent=2, default=str), encoding="utf-8")

    print(f"[phase2_sectors] Resolved {len(tickers)} symbols")
    print(f"[phase2_sectors] Sectors: {len(resolved_sectors)}")
    print(f"[phase2_sectors] Unresolved (fallback): {len(unresolved)}")
    for entry in resolved_sectors[:5]:
        print(f"  {entry['sector']}: ${entry['value']:,.0f} ({entry['pct']}%)")
    print(f"[phase2_sectors] Written: {holdings_path}")
    print(f"[phase2_sectors] Written: {snapshot_path}")


if __name__ == "__main__":
    main()
