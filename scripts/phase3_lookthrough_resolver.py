#!/usr/bin/env python3
# phase3_lookthrough_resolver.py
# Look-through aware sector resolver.
# For funds/ETFs with lookthrough data: distributes market value by sector weights.
# For direct stocks: uses existing classification chain.
# Writes resolved_sectors + overlap_analysis to holdings.json.
# Overlap detection: passive only — logged for Steph to surface on query.

from __future__ import annotations
import argparse, json
from collections import defaultdict
from datetime import date
from pathlib import Path


def _safe_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _resolve_direct_stock(rec: dict, manual_map: dict) -> tuple:
    """Resolve sector for direct stock holdings. Returns (sector, industry, source)."""
    sym = rec.get("symbol", "")

    if sym in manual_map:
        entry = manual_map[sym]
        return entry.get("sector", "Other"), entry.get("industry", ""), "manual_map"

    c = rec.get("classification", {}) or {}
    f = rec.get("fundamentals", {}) or {}

    for key in ("fv_sector", "yf_sector", "sector"):
        if c.get(key):
            industry = c.get("fv_industry") or c.get("yf_industry") or c.get("industry", "")
            return c[key], industry, f"classification_{key}"

    for key in ("fv_sector", "yf_sector"):
        if f.get(key):
            return f[key], f.get(f"{'fv' if 'fv' in key else 'yf'}_industry", ""), f"fundamentals_{key}"

    # Fallback: yfinance-backed GICS sector lookup (cached). Auto-classifies any stock/sector-ETF the
    # snapshot didn't, so new holdings never silently land in "Other". Diversified ETFs → None → Other.
    try:
        from sector_cache import get_sector
        yf_sec = get_sector(sym)
        if yf_sec:
            return yf_sec, "", "yfinance_cache"
    except Exception:
        pass

    return "Other / Unclassified", "", "fallback"


def build_overlap_analysis(
    holdings: list,
    lookthrough: dict,
    snapshot_tickers: dict
) -> dict:
    """
    Detect when a direct holding also appears in a fund's top holdings.
    Returns overlap_analysis dict for Steph to surface on query.
    Passive only — not alerting, just logging.
    """
    # Build direct holdings index
    direct = {}
    for h in holdings:
        sym = h.get("symbol", "")
        mv = float(h.get("market_value") or 0)
        if sym and not h.get("is_loan") and not h.get("is_cash"):
            # Only count non-fund direct positions
            if sym not in lookthrough:
                direct[sym] = direct.get(sym, 0) + mv

    overlaps = []
    for fund_sym, fund_entry in lookthrough.items():
        if fund_sym == "_meta":
            continue
        top_holdings = fund_entry.get("top_holdings", [])
        if not top_holdings:
            continue

        # Get fund market value from holdings
        fund_mv = sum(
            float(h.get("market_value") or 0)
            for h in holdings
            if h.get("symbol") == fund_sym and not h.get("is_loan")
        )
        if fund_mv <= 0:
            continue

        for holding in top_holdings:
            h_ticker = (holding.get("ticker") or "").upper()
            h_pct = float(holding.get("pct") or 0)
            h_name = holding.get("name", "")

            if h_ticker in direct and h_pct > 0:
                direct_mv = direct[h_ticker]
                indirect_mv = fund_mv * (h_pct / 100)
                total_combined = direct_mv + indirect_mv

                overlaps.append({
                    "ticker": h_ticker,
                    "name": h_name,
                    "direct_value": round(direct_mv, 2),
                    "indirect_via": fund_sym,
                    "indirect_fund_name": fund_entry.get("fund_name", fund_sym),
                    "indirect_pct_in_fund": round(h_pct, 2),
                    "indirect_value": round(indirect_mv, 2),
                    "combined_value": round(total_combined, 2),
                })

    # Sort by combined value descending
    overlaps.sort(key=lambda x: x["combined_value"], reverse=True)

    return {
        "generated_at": date.today().isoformat(),
        "overlaps": overlaps,
        "overlap_count": len(overlaps),
        "note": "Passive overlap detection. Ask Steph for analysis."
    }


def main():
    ap = argparse.ArgumentParser(description="Phase 3 look-through sector resolver")
    ap.add_argument("--project-root", required=True)
    args = ap.parse_args()
    project_root = Path(args.project_root)
    state_dir = project_root / "data" / "portfolios" / "state"
    log_dir = project_root / "logs" / "phase3"
    log_dir.mkdir(parents=True, exist_ok=True)

    holdings_path  = state_dir / "holdings.json"
    snapshot_path  = state_dir / "ticker_snapshot_latest.json"
    lookthrough_path = state_dir / "fund_lookthrough.json"
    manual_map_path = state_dir / "manual_sector_map.json"

    holdings_data  = _safe_json(holdings_path, {})
    snapshot_data  = _safe_json(snapshot_path, {"_meta": {}, "tickers": {}})
    lookthrough    = _safe_json(lookthrough_path, {})
    manual_map     = _safe_json(manual_map_path, {})

    holdings_list = holdings_data.get("holdings", [])
    snapshot_tickers = snapshot_data.get("tickers", {})

    # Bucket: sector → total value (global) + per-account so the UI can filter the allocation by account
    sector_bucket = defaultdict(float)
    sector_by_account = defaultdict(lambda: defaultdict(float))
    # sector → list of position contributions (fund look-through slices + direct stocks)
    # key: (sector, symbol, account, method) → allocated $
    contributor_bucket: dict[tuple, float] = defaultdict(float)
    # sector → underlying ticker → $ (from fund top_holdings when ticker sector matches)
    underlying_bucket: dict[tuple, float] = defaultdict(float)
    underlying_via: dict[tuple, set] = defaultdict(set)  # (sector, ticker) → fund symbols
    # Per-symbol resolution log
    resolution_log = []
    unresolved = []

    def _add_contributor(sector: str, symbol: str, account: str, method: str, value: float):
        if value <= 0 or not sector or not symbol:
            return
        contributor_bucket[(sector, symbol, account, method)] += value

    for h in holdings_list:
        sym = h.get("symbol", "")
        mv = float(h.get("market_value") or 0)
        acct = h.get("account") or h.get("account_id") or "unknown"

        if not sym or h.get("is_loan") or h.get("is_cash") or mv <= 0:
            continue

        # ── FUND / ETF: use look-through ──────────────────────────────────────
        if sym in lookthrough and lookthrough[sym] != "_meta":
            entry = lookthrough[sym]
            weights = entry.get("sector_weights", {})
            fund_name = entry.get("fund_name", sym)
            asset_class = entry.get("asset_class", "")
            data_age = (
                date.today() - date.fromisoformat(entry.get("fetched_date", "2000-01-01"))
            ).days if entry.get("fetched_date") else 9999

            if weights:
                total_weight = sum(weights.values())
                for sector, weight in weights.items():
                    # Normalize weights in case they don't sum to 100
                    normalized_pct = (weight / total_weight * 100) if total_weight else weight
                    allocated = mv * (normalized_pct / 100)
                    sector_bucket[sector] += allocated
                    sector_by_account[acct][sector] += allocated
                    _add_contributor(sector, sym, acct, "lookthrough", allocated)

                # Top underlyings: attribute fund MV × holding % into the ticker's own sector
                for th in (entry.get("top_holdings") or []):
                    tick = str(th.get("ticker") or "").upper()
                    pct = float(th.get("pct") or 0)
                    if not tick or pct <= 0:
                        continue
                    uval = mv * (pct / 100.0)
                    usec = None
                    try:
                        from sector_cache import get_sector
                        usec = get_sector(tick)
                    except Exception:
                        usec = None
                    if not usec:
                        # Fall back: leave unassigned to sector underlyings
                        continue
                    underlying_bucket[(usec, tick)] += uval
                    underlying_via[(usec, tick)].add(sym)

                resolution_log.append({
                    "symbol": sym,
                    "method": "lookthrough",
                    "fund_name": fund_name,
                    "asset_class": asset_class,
                    "market_value": round(mv, 2),
                    "sectors_allocated": len(weights),
                    "data_age_days": data_age,
                    "sector_breakdown": {s: round(mv * (w / total_weight), 2) if total_weight else 0
                                        for s, w in weights.items()}
                })
            else:
                # No weights yet — fall back to asset class label
                label = asset_class or "Other / Unclassified"
                sector_bucket[label] += mv
                sector_by_account[acct][label] += mv
                _add_contributor(label, sym, acct, "asset_class_label", mv)
                resolution_log.append({
                    "symbol": sym,
                    "method": "asset_class_label",
                    "market_value": round(mv, 2),
                    "sector": label,
                })
            continue

        # ── DIRECT STOCK: use classification chain ────────────────────────────
        rec = snapshot_tickers.get(sym, {"symbol": sym})
        sector, industry, source = _resolve_direct_stock(rec, manual_map)
        sector_bucket[sector] += mv
        sector_by_account[acct][sector] += mv
        _add_contributor(sector, sym, acct, "direct_stock", mv)

        if sector == "Other / Unclassified":
            unresolved.append({"symbol": sym, "market_value": round(mv, 2)})

        resolution_log.append({
            "symbol": sym,
            "method": "direct_stock",
            "sector": sector,
            "industry": industry,
            "source": source,
            "market_value": round(mv, 2),
        })

    # Build resolved_sectors list sorted by value
    total = sum(sector_bucket.values()) or 1.0
    resolved_sectors = [
        {
            "sector": sector,
            "value": round(value, 2),
            "pct": round(value / total * 100, 2)
        }
        for sector, value in sorted(sector_bucket.items(), key=lambda x: x[1], reverse=True)
    ]

    # Per-account sector breakdown (so the UI Allocation can filter by selected account)
    resolved_sectors_by_account = {}
    for acct, buckets in sector_by_account.items():
        atot = sum(buckets.values()) or 1.0
        resolved_sectors_by_account[acct] = [
            {"sector": s, "value": round(v, 2), "pct": round(v / atot * 100, 2)}
            for s, v in sorted(buckets.items(), key=lambda x: x[1], reverse=True)
        ]

    # Position-level contributors per sector (Allocation drill-down)
    resolved_sector_contributors: dict[str, list] = defaultdict(list)
    for (sector, symbol, account, method), val in contributor_bucket.items():
        sec_tot = sector_bucket.get(sector) or 1.0
        resolved_sector_contributors[sector].append({
            "symbol": symbol,
            "account": account,
            "method": method,
            "value": round(val, 2),
            "pct_of_sector": round(val / sec_tot * 100, 2),
        })
    for sector in resolved_sector_contributors:
        resolved_sector_contributors[sector].sort(key=lambda x: -x["value"])

    # Underlying names (stocks inside funds) per sector
    resolved_sector_underlyings: dict[str, list] = defaultdict(list)
    for (sector, ticker), val in underlying_bucket.items():
        sec_tot = sector_bucket.get(sector) or 1.0
        resolved_sector_underlyings[sector].append({
            "symbol": ticker,
            "value": round(val, 2),
            "pct_of_sector": round(val / sec_tot * 100, 2),
            "via": sorted(underlying_via.get((sector, ticker)) or []),
        })
    for sector in resolved_sector_underlyings:
        resolved_sector_underlyings[sector].sort(key=lambda x: -x["value"])
        resolved_sector_underlyings[sector] = resolved_sector_underlyings[sector][:25]

    # Build overlap analysis (passive)
    overlap_analysis = build_overlap_analysis(holdings_list, lookthrough, snapshot_tickers)

    # Write to holdings.json
    holdings_data["resolved_sectors"] = resolved_sectors
    holdings_data["resolved_sectors_by_account"] = resolved_sectors_by_account
    holdings_data["resolved_sector_contributors"] = dict(resolved_sector_contributors)
    holdings_data["resolved_sector_underlyings"] = dict(resolved_sector_underlyings)
    holdings_data["overlap_analysis"] = overlap_analysis
    holdings_data["lookthrough_as_of"] = date.today().isoformat()
    from holdings_guard import protected_holdings_write  # MANDATORY wipe-guard
    protected_holdings_write(holdings_data, source="phase3_lookthrough_resolver", target_path=str(holdings_path))

    # Write logs
    (log_dir / "phase3_resolution_log.json").write_text(
        json.dumps(resolution_log, indent=2, default=str), encoding="utf-8")
    (log_dir / "phase3_unresolved.json").write_text(
        json.dumps(unresolved, indent=2, default=str), encoding="utf-8")
    (log_dir / "phase3_overlap_analysis.json").write_text(
        json.dumps(overlap_analysis, indent=2, default=str), encoding="utf-8")

    # Print summary
    other_pct = next((s["pct"] for s in resolved_sectors if "Unclassified" in s["sector"]), 0)
    print(f"[phase3_resolver] Resolved {len(holdings_list)} holdings")
    print(f"[phase3_resolver] Sectors: {len(resolved_sectors)}")
    print(f"[phase3_resolver] Unresolved: {len(unresolved)} symbols ({other_pct:.1f}%)")
    print(f"[phase3_resolver] Overlaps detected: {overlap_analysis['overlap_count']}")
    print(f"[phase3_resolver] Top sectors:")
    for s in resolved_sectors[:6]:
        print(f"  {s['sector']:35s}: ${s['value']:>10,.0f}  ({s['pct']:.1f}%)")
    print(f"[phase3_resolver] Written: {holdings_path}")

    if overlap_analysis["overlaps"]:
        print(f"[phase3_resolver] Top overlaps (ask Steph for analysis):")
        for o in overlap_analysis["overlaps"][:5]:
            print(f"  {o['ticker']:8s} direct ${o['direct_value']:>8,.0f} "
                  f"+ {o['indirect_via']} ${o['indirect_value']:>8,.0f} "
                  f"= ${o['combined_value']:>8,.0f}")


if __name__ == "__main__":
    main()
