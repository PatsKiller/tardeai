#!/usr/bin/env python3
"""One-shot, idempotent source transformer for the Defense/Sectors hardening branch.

The workflow runs this in an isolated GitHub runner, validates the result, and commits
only after all focused tests and frontend render gates pass.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex(text: str, pattern: str, replacement: str, label: str) -> str:
    if replacement in text:
        return text
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    return out


# ── Configuration ──────────────────────────────────────────────────────────────

def patch_configs() -> None:
    path = ROOT / "config" / "defense_recommendations.json"
    cfg = json.loads(path.read_text())
    cfg["allocation_policy"] = {
        "default_benchmark": "equal_sector",
        "benchmarks": {
            "equal_sector": {s: 9.1 for s in (
                "Technology", "Financials", "Healthcare", "Energy", "Industrials",
                "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials",
                "Real Estate", "Communications")},
        },
        "account_mandates": {
            "schwab_taxable": "total_return",
            "schwab_rollover_ira": "retirement_income",
            "schwab_roth_ira": "retirement_income",
            "tradeai_automated": "research",
        },
        "mandates": {
            "total_return": {"sector_tilts_pct": {}},
            "research": {"sector_tilts_pct": {}},
            "retirement_income": {"sector_tilts_pct": {
                "Utilities": 1.0, "Consumer Staples": 1.0, "Healthcare": 1.0,
                "Financials": 0.5, "Technology": -1.0,
            }},
        },
        "target_annualized_vol_pct": 22.0,
        "vol_scalar_floor": 0.45,
        "vol_scalar_cap": 1.20,
        "correlation_soft_limit": 0.85,
        "correlation_penalty": 0.75,
        "max_active_tilt_pct": 4.0,
        "sector_cap_pct": 25.0,
        "min_capacity_pct": 1.0,
        "benchmark_note": "equal-sector is an explicit selectable policy, not universal truth",
    }
    cfg["stock_quality"] = {
        "min_coverage": 0.60,
        "min_score": 60.0,
        "min_roic_pct": 8.0,
        "max_debt_equity": 2.0,
        "hard_fail_debt_equity": 4.0,
        "max_short_float_pct": 12.0,
        "hard_fail_short_float_pct": 25.0,
        "max_beta": 1.7,
        "max_above_sma50_pct": 12.0,
        "requires_close_confirmed_industry": True,
    }
    lean = cfg.setdefault("rotation_pairs", {}).setdefault("defensive_lean", {})
    lean.setdefault("set_at", "2026-07-18")
    lean["review_after_days"] = 5
    lean["review_policy"] = "retain until operator adjudication; never auto-revoke"
    lean["evidence_required"] = [
        "full-universe breadth", "small-vs-large trend", "equal-vs-cap trend",
        "sector and industry close confirmation", "portfolio capacity and risk budget",
    ]
    path.write_text(json.dumps(cfg, indent=2) + "\n")

    fpath = ROOT / "config" / "fund_lookthrough.json"
    fcfg = json.loads(fpath.read_text())
    fcfg["_schema_version"] = "fund-lookthrough-provenance-v2"
    fcfg["_default_refresh_sla_days"] = 100
    for sym, fund in fcfg.get("funds", {}).items():
        source = fund.get("source", "")
        if "Schwab" in source:
            provider = "Schwab"
        elif "JPM" in source:
            provider = "JPMorgan"
        elif "ARK" in source:
            provider = "ARK Invest"
        elif "SPDR" in fund.get("name", "") or sym in {"XLI", "XLB", "XAR"}:
            provider = "State Street SPDR"
        elif sym == "BND":
            provider = "Vanguard"
        elif sym == "DIVI":
            provider = "Franklin Templeton"
        else:
            provider = "operator configuration"
        fund["provider"] = provider
        if "2026Q2" in source:
            fund["factsheet_as_of"] = "2026-06-30"
            fund["refresh_due"] = "2026-10-01"
        elif "definitional" in source:
            fund["factsheet_as_of"] = "definitional"
            fund["refresh_due"] = None
        else:
            fund.setdefault("factsheet_as_of", None)
            fund.setdefault("refresh_due", fcfg.get("_refresh_due"))
        fund["mapping_quality"] = "estimate" if "ESTIMATE" in source else (
            "not_decomposed" if fund.get("lookthrough") == "none" else "factsheet")
        if fund.get("weights"):
            coverage = sum(float(v) for v in fund["weights"].values())
            fund["coverage_pct"] = round(coverage * 100, 2)
            fund["unmapped_weight_pct"] = round(max(0.0, 1.0 - coverage) * 100, 2)
    fpath.write_text(json.dumps(fcfg, indent=2) + "\n")


# ── Fund look-through ─────────────────────────────────────────────────────────

FUND_LOOKTHROUGH = '''#!/usr/bin/env python3
"""Effective sector exposure with field-level fund provenance.

Effective exposure = direct holdings + configured factsheet sector weights.  Every
fund contribution now carries provider, factsheet date, refresh SLA, coverage and
unmapped weight.  Unknown weights remain explicitly unmapped; they are never guessed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from defense_data_quality import snapshot_hash

ROOT = Path(__file__).resolve().parent.parent
_CFG = None
_CANON = None


def _cfg_all() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = json.loads((ROOT / "config" / "fund_lookthrough.json").read_text())
    return _CFG


def _cfg() -> dict:
    return _cfg_all()["funds"]


def canon_sector(name: str) -> str:
    global _CANON
    if _CANON is None:
        aliases = json.loads((ROOT / "config" / "sector_momentum.json").read_text()).get("sector_aliases", {})
        _CANON = {alias: canonical for canonical, values in aliases.items() for alias in values}
    return _CANON.get(name, name)


def _fund_meta(sym: str, fund: dict, allocated_weight: float) -> dict:
    due = fund.get("refresh_due")
    stale = False
    if due:
        try:
            stale = datetime.now(timezone.utc).date() > datetime.fromisoformat(str(due)[:10]).date()
        except Exception:
            stale = True
    return {
        "fund": sym,
        "provider": fund.get("provider"),
        "factsheet_as_of": fund.get("factsheet_as_of"),
        "refresh_due": due,
        "stale": stale,
        "mapping_quality": fund.get("mapping_quality", "unknown"),
        "coverage_pct": round(allocated_weight * 100, 2),
        "unmapped_weight_pct": round(max(0.0, 1.0 - allocated_weight) * 100, 2),
    }


def effective_sector_exposure(rows: list) -> dict:
    cfg_all, cfg = _cfg_all(), _cfg()
    agg: dict = {}
    not_decomposed = []
    provenance = {}
    total = 0.0
    unmapped_dollars = 0.0

    def bucket(sector):
        return agg.setdefault(sector, {"dollars": 0.0, "direct_dollars": 0.0,
                                      "lookthrough_dollars": 0.0, "contributors": []})

    for r in rows:
        sym = r.get("symbol")
        val = float(r.get("value") or 0)
        if val <= 0:
            continue
        total += val
        fund = cfg.get(sym)
        if fund and fund.get("weights"):
            allocated = sum(float(w) for w in fund["weights"].values())
            meta = _fund_meta(sym, fund, allocated)
            provenance[sym] = meta
            for sector, weight in fund["weights"].items():
                dollars = val * float(weight)
                b = bucket(sector)
                b["dollars"] += dollars
                b["lookthrough_dollars"] += dollars
                b["contributors"].append({**meta, "dollars": round(dollars)})
            remainder = max(0.0, val * (1.0 - allocated))
            if remainder > 1:
                unmapped_dollars += remainder
                b = bucket("Other")
                b["dollars"] += remainder
                b["lookthrough_dollars"] += remainder
                b["contributors"].append({**meta, "dollars": round(remainder),
                                           "unmapped_remainder": True})
        elif fund and fund.get("lookthrough") == "none":
            meta = _fund_meta(sym, fund, 0.0)
            provenance[sym] = meta
            not_decomposed.append({"symbol": sym, "dollars": round(val),
                                   "why": fund.get("why", ""), **meta})
        else:
            sector = canon_sector(r.get("sector") or "Other")
            b = bucket(sector)
            b["dollars"] += val
            b["direct_dollars"] += val
            b["contributors"].append({"fund": sym, "dollars": round(val), "direct": True,
                                      "provider": "holding record", "mapping_quality": "direct"})

    for sector, b in agg.items():
        b["dollars"] = round(b["dollars"])
        b["direct_dollars"] = round(b["direct_dollars"])
        b["lookthrough_dollars"] = round(b["lookthrough_dollars"])
        b["pct"] = round(b["dollars"] / total * 100, 1) if total else 0.0
        b["direct_pct"] = round(b["direct_dollars"] / total * 100, 1) if total else 0.0
        b["contributors"] = sorted(b["contributors"], key=lambda c: -c["dollars"])[:8]

    agg["_total"] = round(total)
    agg["_not_decomposed"] = {"dollars": round(sum(x["dollars"] for x in not_decomposed)),
                              "positions": not_decomposed}
    agg["_provenance"] = {
        "schema_version": cfg_all.get("_schema_version"),
        "config_hash": snapshot_hash(cfg_all),
        "funds": provenance,
        "stale_funds": sorted(sym for sym, meta in provenance.items() if meta.get("stale")),
        "unmapped_dollars": round(unmapped_dollars),
        "unmapped_pct_of_book": round(unmapped_dollars / total * 100, 2) if total else 0.0,
    }
    return agg
'''


# ── Sector engine ──────────────────────────────────────────────────────────────

def patch_sector_engine() -> None:
    path = "scripts/sector_momentum_engine.py"
    text = read(path)
    text = replace_once(
        text,
        'CFG = json.loads((ROOT / "config" / "sector_momentum.json").read_text())\n',
        'from defense_data_quality import (SECTOR_CALC_VERSION, snapshot_hash, staleness, truth_ref)\n\nCFG = json.loads((ROOT / "config" / "sector_momentum.json").read_text())\n',
        "sector imports",
    )
    breadth = '''def _breadth(cur, etf_sector_name):
    """Exact breadth: latest close vs mean of exactly 20 distinct trading sessions."""
    try:
        cur.execute(
            """SELECT DISTINCT m.symbol FROM screener_symbol_membership m
               JOIN trade_ai_scans t ON upper(t.symbol) = upper(m.symbol)
               WHERE t.sector = ANY(%s) LIMIT 500""", (_aliases(etf_sector_name),))
        members = [r[0] for r in cur.fetchall()]
        membership_n = len(members)
        if membership_n < CFG["breadth_min_members"]:
            return None, 0, membership_n, "insufficient_membership"
        cur.execute(
            """WITH daily AS (
                   SELECT symbol, price_date, max(close_price) AS close_price
                   FROM ticker_prices
                   WHERE symbol = ANY(%s) AND price_date > CURRENT_DATE - 90
                   GROUP BY symbol, price_date
               ), ranked AS (
                   SELECT symbol, price_date, close_price,
                          row_number() OVER (PARTITION BY symbol ORDER BY price_date DESC) AS rn
                   FROM daily
               ), exact20 AS (
                   SELECT symbol,
                          max(close_price) FILTER (WHERE rn = 1) AS last,
                          avg(close_price) FILTER (WHERE rn <= 20) AS dma20,
                          count(*) FILTER (WHERE rn <= 20) AS session_n
                   FROM ranked GROUP BY symbol
               )
               SELECT symbol, last, dma20, session_n FROM exact20 WHERE session_n = 20""",
            (members,),
        )
        rows = cur.fetchall()
        above = sum(1 for _sym, last, dma, _n in rows
                    if last is not None and dma is not None and float(last) > float(dma))
        coverage_n = len(rows)
        quality = "ok" if coverage_n >= CFG["breadth_min_members"] else "insufficient_price_coverage"
        pct = round(above / coverage_n * 100) if quality == "ok" else None
        return pct, coverage_n, membership_n, quality
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return None, 0, 0, "query_error"
'''
    text = replace_regex(text, r'def _breadth\(cur, etf_sector_name\):.*?(?=\n\ndef _hermes_pulse)', breadth,
                         "exact breadth")
    state_line = '''def market_state_line(market, sectors):
    """Template-driven one-liner; capped mover counts are never called market breadth."""
    spy = next((i for i in market["indices"] if i["symbol"] == "SPY"), {})
    eq = next((s for s in market["styles"] if s["key"] == "equal_vs_cap"), {})
    sm = next((s for s in market["styles"] if s["key"] == "small_vs_large"), {})
    nh = market.get("internals", {}).get("new_high")
    nl = market.get("internals", {}).get("new_low")
    lag = sum(1 for r in sectors if r.get("state") == "LAGGING")
    parts = []
    if spy.get("short") is not None:
        parts.append(f"SPY {spy['short']:+.1f}% wk")
    if eq.get("s20") is not None:
        parts.append(("equal-weight leading cap-weight" if eq["s20"] > 0 else
                      "cap-weight leading equal-weight") + f" ({eq['s20']:+.1f}% 20d)")
    if sm.get("s20") is not None:
        parts.append("small caps " + ("leading" if sm["s20"] > 0 else "lagging"))
    if nh is not None and nl is not None:
        parts.append(f"top-movers NH/NL sample {nh}/{nl}")
    parts.append(f"{lag}/11 sectors lagging")
    return "Market: " + " · ".join(parts)
'''
    text = replace_regex(text, r'def market_state_line\(market, sectors\):.*?(?=\n\ndef _book_weights)',
                         state_line, "sample label")
    book = '''def _book_weights():
    """Effective sector weights with factsheet provenance and unmapped coverage."""
    try:
        import api_v2
        from fund_lookthrough import effective_sector_exposure
        bm = api_v2._portfolio_book_map() or {}
        eff = effective_sector_exposure(bm.get("rows", []))
        out = {}
        for sector, b in eff.items():
            if sector.startswith("_"):
                continue
            out[sector] = {"dollars": b["dollars"], "pct": b["pct"],
                           "direct_pct": b["direct_pct"],
                           "lookthrough_dollars": b["lookthrough_dollars"],
                           "contributors": b["contributors"]}
        out["_not_decomposed"] = eff.get("_not_decomposed")
        out["_provenance"] = eff.get("_provenance")
        return out
    except Exception:
        return {}
'''
    text = replace_regex(text, r'def _book_weights\(\):.*?(?=\n\ndef main\(\))', book,
                         "book provenance")
    text = replace_once(
        text,
        '    weights = _book_weights()\n    rows = compute_states(cur)\n    market = compute_market(cur)\n',
        '    weights = _book_weights()\n    rows = compute_states(cur)\n    market = compute_market(cur)\n    latest_as_of = max((r.get("as_of") for r in rows if r.get("as_of")), default=None)\n    for row in rows:\n        freshness = staleness(row.get("as_of"), latest_as_of, CFG.get("max_row_staleness_days", 4))\n        row.update({"freshness": freshness, "quarantined": freshness["stale"]})\n        if freshness["stale"] and row.get("state"):\n            row["state_raw"] = row["state"]\n            row["state"] = None\n            row["quarantine_reason"] = "stale_row"\n',
        "sector stale quarantine",
    )
    text = replace_once(text, '        b_pct, b_n = _breadth(cur, name)\n',
                        '        b_pct, b_n, b_members, b_quality = _breadth(cur, name)\n',
                        "breadth unpack")
    old_update = '''        row.update({"breadth_pct": b_pct, "breadth_n": b_n, "hermes_pulse": hp,
                    "hermes_delta": hd, "news_negatives": nn, "top_negative": top_neg,
                    "book_pct": w.get("pct"), "book_dollars": w.get("dollars"),
                    "book_direct_pct": w.get("direct_pct"),
                    "book_contributors": w.get("contributors")})
'''
    new_update = '''        row.update({"breadth_pct": b_pct, "breadth_n": b_n,
                    "breadth_coverage_n": b_n, "breadth_membership_n": b_members,
                    "breadth_quality": b_quality, "hermes_pulse": hp,
                    "hermes_delta": hd, "news_negatives": nn, "top_negative": top_neg,
                    "book_pct": w.get("pct"), "book_dollars": w.get("dollars"),
                    "book_direct_pct": w.get("direct_pct"),
                    "book_contributors": w.get("contributors"),
                    "calculation_version": SECTOR_CALC_VERSION,
                    "quality": "narrow_participation" if b_pct is not None and b_pct < 35 else b_quality,
                    "truth": truth_ref(source="ticker_prices + exact screener membership",
                                       as_of=row.get("as_of"), calculation_version=SECTOR_CALC_VERSION,
                                       cadence="daily close", quality=b_quality,
                                       coverage_n=b_n, coverage_total=b_members)})
'''
    text = replace_once(text, old_update, new_update, "sector truth row")
    old_snap = '''    snap = {"generated_at": datetime.now(timezone.utc).isoformat(),
            "rows": rows, "market": market, "transitions_today": alerts,
            "not_decomposed": weights.get("_not_decomposed"),
            "exposure_basis": "effective (direct + config fund lookthrough, factsheet weights)"}
'''
    new_snap = '''    snap = {"generated_at": datetime.now(timezone.utc).isoformat(),
            "as_of": latest_as_of, "calculation_version": SECTOR_CALC_VERSION,
            "rows": rows, "market": market, "transitions_today": alerts,
            "not_decomposed": weights.get("_not_decomposed"),
            "exposure_provenance": weights.get("_provenance"),
            "exposure_basis": "effective (direct + config fund lookthrough, dated factsheet weights)",
            "truth_ledger": {
                "sector_returns": truth_ref(source="ticker_prices distinct closes", as_of=latest_as_of,
                    calculation_version=SECTOR_CALC_VERSION, cadence="daily close"),
                "breadth": truth_ref(source="ticker_prices exact 20 distinct sessions", as_of=latest_as_of,
                    calculation_version="breadth-exact20-v1", cadence="daily close"),
                "market_movers": truth_ref(source="market_movers capped top-15 per signal", as_of="latest capture",
                    calculation_version="movers-sample-v1", cadence="intraday", quality="capped_sample",
                    notes=["not comprehensive market breadth"]),
            }}
    snap["snapshot_hash"] = snapshot_hash(snap)
'''
    text = replace_once(text, old_snap, new_snap, "sector snapshot truth")
    write(path, text)


# ── Industry engine ────────────────────────────────────────────────────────────

def patch_industry_engine() -> None:
    path = "scripts/finviz_industry_groups.py"
    text = read(path)
    text = replace_once(
        text,
        'from sector_momentum_engine import CFG, classify, _closes, _ret  # noqa: E402\n',
        'from sector_momentum_engine import CFG, classify  # noqa: E402\nfrom defense_data_quality import (INDUSTRY_CALC_VERSION, canonical_industry_sector,\n                                  load_industry_map, snapshot_hash, truth_ref)  # noqa: E402\nfrom finviz_enrichment import _fetch_view as _finviz_fetch_view  # noqa: E402\n',
        "industry imports",
    )
    sector_map = '''def sector_map() -> dict:
    """Versioned deterministic mapping configuration; never a modal DB inference."""
    return load_industry_map(ROOT)
'''
    text = replace_regex(text, r'def sector_map\(cur\) -> dict:.*?(?=\n\ndef book_watch_industries)',
                         sector_map, "canonical industry mapping")
    spy = '''def spy_baseline():
    """SPY week/month performance from the same Finviz view and run as industries."""
    rows = _finviz_fetch_view(["SPY"], 141, ROOT)
    rec = rows.get("SPY") or {}
    return {
        "w1": rec.get("perf_week_pct"),
        "m1": rec.get("perf_month_pct"),
        "provider": "finviz_elite_view_141",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quality": "same_vendor_same_run" if rec.get("perf_week_pct") is not None and rec.get("perf_month_pct") is not None else "missing",
    }
'''
    text = replace_regex(text, r'def spy_baseline\(cur\):.*?(?=\n\ndef main\(\))', spy,
                         "same vendor SPY")
    text = replace_once(
        text,
        '    spy1w, spy1m = spy_baseline(cur)\n    if spy1w is None or spy1m is None:\n',
        '    spy = spy_baseline()\n    spy1w, spy1m = spy.get("w1"), spy.get("m1")\n    if spy1w is None or spy1m is None:\n',
        "industry SPY call",
    )
    text = replace_once(text, '    smap = sector_map(cur)\n    book, watch = book_watch_industries(cur)\n',
                        '    mapping_cfg = sector_map()\n    book, watch = book_watch_industries(cur)\n',
                        "industry mapping call")
    old_loop = '''    for g in groups:
        g["sector"] = smap.get(g["industry"])
        g["rel1w"] = round(g["perf_week"] - spy1w, 2) if g["perf_week"] is not None else None
        g["rel1m"] = round(g["perf_month"] - spy1m, 2) if g["perf_month"] is not None else None
        g["state"] = classify(g["rel1m"], g["rel1w"])
        g["held"] = book.get(g["industry"], [])
        g["watched"] = watch.get(g["industry"], [])
'''
    new_loop = '''    for g in groups:
        mapping = canonical_industry_sector(g["industry"], mapping_cfg)
        g.update(mapping)
        g["rel1w"] = round(g["perf_week"] - spy1w, 2) if g["perf_week"] is not None else None
        g["rel1m"] = round(g["perf_month"] - spy1m, 2) if g["perf_month"] is not None else None
        g["state"] = classify(g["rel1m"], g["rel1w"])
        g["held"] = book.get(g["industry"], [])
        g["watched"] = watch.get(g["industry"], [])
        g["quarantined"] = mapping["mapping_quality"] == "unmapped"
        g["quality"] = "quarantined_unmapped" if g["quarantined"] else spy["quality"]
        g["truth"] = truth_ref(source="finviz_elite_view_141", as_of=spy["captured_at"],
                               calculation_version=INDUSTRY_CALC_VERSION,
                               cadence="midday refresh + close capture", quality=g["quality"])
'''
    text = replace_once(text, old_loop, new_loop, "industry mapped rows")
    text = replace_once(text,
                        '    lagging = [g for g in groups if g["state"] == "LAGGING"]\n    improving = [g for g in groups if g["state"] == "IMPROVING"]\n',
                        '    lagging = [g for g in groups if g["state"] == "LAGGING" and not g.get("quarantined")]\n    improving = [g for g in groups if g["state"] == "IMPROVING" and not g.get("quarantined")]\n',
                        "industry quarantine candidates")
    old_snap = '''    snap = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_kind": "close" if args.close else "refresh",
        "spy_baseline": {"w1": round(spy1w, 2), "m1": round(spy1m, 2)},
        "quadrant_mapping": "level=perf_month−SPY21d, direction=perf_week−SPY5d (same classify as sectors)",
        "industries": groups,
        "by_sector": by_sector,
        "top10": [g["industry"] for g in ranked[:10]],
        "bottom10": [g["industry"] for g in ranked[-10:]][::-1],
        "candidates": {
            "source_type": "industry_momentum",
            "defensive_short_pool": [
                {"industry": g["industry"], "sector": g["sector"], "rel1w": g["rel1w"]}
                for g in sorted(lagging, key=lambda x: x["rel1w"] or 0)[:POOL_N]],
            "watch_rail": [
                {"industry": g["industry"], "sector": g["sector"], "rel1w": g["rel1w"]}
                for g in sorted(improving, key=lambda x: x["rel1w"] or 0, reverse=True)[:POOL_N]],
        },
        "transitions_confirmed": confirmed,
        "alerts": alerts,
        "counts": {s: sum(1 for g in groups if g["state"] == s) for s in
                   ("LEADING", "WEAKENING", "LAGGING", "IMPROVING")},
    }
'''
    new_snap = '''    captured_at = datetime.now(timezone.utc).isoformat()
    unmapped = [g["industry"] for g in groups if g.get("quarantined")]
    snap = {
        "captured_at": captured_at,
        "capture_kind": "close" if args.close else "refresh",
        "calculation_version": INDUSTRY_CALC_VERSION,
        "spy_baseline": {**spy, "w1": round(spy1w, 2), "m1": round(spy1m, 2)},
        "quadrant_mapping": "level=Finviz month−Finviz SPY month, direction=Finviz week−Finviz SPY week",
        "industries": groups,
        "by_sector": by_sector,
        "top10": [g["industry"] for g in ranked[:10]],
        "bottom10": [g["industry"] for g in ranked[-10:]][::-1],
        "candidates": {
            "source_type": "industry_momentum",
            "mode": "close_observed" if args.close else "intraday_research_only",
            "defensive_short_pool": [
                {"industry": g["industry"], "sector": g["sector"], "rel1w": g["rel1w"]}
                for g in sorted(lagging, key=lambda x: x["rel1w"] or 0)[:POOL_N]],
            "watch_rail": [
                {"industry": g["industry"], "sector": g["sector"], "rel1w": g["rel1w"]}
                for g in sorted(improving, key=lambda x: x["rel1w"] or 0, reverse=True)[:POOL_N]],
        },
        "transitions_confirmed": confirmed if args.close else [],
        "alerts": alerts,
        "counts": {s: sum(1 for g in groups if g["state"] == s and not g.get("quarantined")) for s in
                   ("LEADING", "WEAKENING", "LAGGING", "IMPROVING")},
        "data_quality": {"provider_alignment": spy["quality"],
                         "mapping_version": mapping_cfg.get("version"),
                         "unmapped_count": len(unmapped), "unmapped": unmapped},
        "truth_ledger": truth_ref(source="finviz_elite_view_141", as_of=captured_at,
                                  calculation_version=INDUSTRY_CALC_VERSION,
                                  cadence="midday refresh + close capture",
                                  quality="ok" if not unmapped else "partial_mapping",
                                  coverage_n=len(groups) - len(unmapped), coverage_total=len(groups)),
    }
    snap["snapshot_hash"] = snapshot_hash(snap)
'''
    text = replace_once(text, old_snap, new_snap, "industry snapshot truth")
    text = text.replace("One Finviz Elite groups export", "Two Finviz Elite exports (groups + same-run SPY performance)")
    text = text.replace("Budget: 1 export/run", "Budget: 2 exports/run")
    write(path, text)


# ── Recommendations ───────────────────────────────────────────────────────────

def patch_recommendations() -> None:
    path = "scripts/defense_recommendations.py"
    text = read(path)
    text = replace_once(
        text,
        'SNAP = ROOT / "data" / "runtime" / "defense_recommendations_latest.json"\n',
        'SNAP = ROOT / "data" / "runtime" / "defense_recommendations_latest.json"\n\nfrom defense_data_quality import (RECOMMENDATION_CALC_VERSION, allocation_decision,\n    directive_review_status, peer_medians, realized_vol_corr, snapshot_hash,\n    stock_quality_assessment, truth_ref)\n',
        "recommendation imports",
    )
    rotate = '''def rotate_in(sectors, cur, enrich, as_of, equities=None) -> list:
    """Risk-aware rotate-in cards.  Missing risk/industry/quality evidence fails closed."""
    c = CFG["rotate_in"]
    cards = []
    ranked = sorted([r for r in sectors if r.get("state") in ("LEADING", "IMPROVING")
                     and not r.get("quarantined")], key=lambda r: -(r.get("rs20") or 0))
    lean = (CFG.get("rotation_pairs") or {}).get("defensive_lean") or {}
    if lean.get("enabled"):
        ranked = [r for r in ranked if r["sector"] in lean.get("defensive_sectors", [])]
    industry_snap = _load("industry_momentum_latest.json")
    industry_close = industry_snap.get("capture_kind") == "close"
    industry_rows = {g.get("industry"): g for g in industry_snap.get("industries", [])
                     if not g.get("quarantined")}

    for r in ranked:
        risk = realized_vol_corr(cur, r["etf"], CFG.get("benchmark", "SPY"))
        decisions = {account: allocation_decision(
            CFG, sector=r["sector"], current_weight_pct=float(r.get("book_pct") or 0),
            risk_context=risk, account=account) for account in sorted(CAPS.keys())}
        accounts = [a for a, d in decisions.items() if d.get("eligible")]
        if not accounts:
            continue

        cur.execute("""SELECT DISTINCT ON (h.symbol) h.symbol, h.composite_score
                       FROM hermes_score_history h JOIN trade_ai_scans t ON t.symbol = h.symbol
                       WHERE t.sector = ANY(%s) AND h.scored_at > now() - interval '3 days'
                       ORDER BY h.symbol, h.scored_at DESC""",
                    ([r["sector"]] + _sector_aliases(r["sector"]),))
        scored = sorted([(s, float(sc)) for s, sc in cur.fetchall() if sc is not None],
                        key=lambda x: -x[1])
        aliases = set([r["sector"]] + _sector_aliases(r["sector"]))
        peers = peer_medians([v for v in enrich.values() if (v or {}).get("sector") in aliases])
        picks = []
        px = _prices(cur, [s for s, _ in scored[:60]])
        for sym, legacy_rank in scored[:60]:
            e = enrich.get(sym) or {}
            price = px.get(sym) or 0
            dollar_vol_m = (e.get("avg_vol_m") or 0) * 1000 * price / 1e6 if price else 0
            prof_e = _profiles_one(cur, sym)
            industry = e.get("industry")
            industry_row = industry_rows.get(industry) or {}
            quality = stock_quality_assessment(e, peers, CFG)
            if dollar_vol_m < c["constituent_min_dollar_vol_m"]:
                continue
            if (e.get("sma50_pct") or 0) > c["constituent_max_ext_above_sma50_pct"]:
                continue
            if _earnings_soon(prof_e, c["earnings_blackout_days"]):
                continue
            if CFG.get("stock_quality", {}).get("requires_close_confirmed_industry") and (
                    not industry_close or industry_row.get("state") not in ("LEADING", "IMPROVING")):
                continue
            if not quality["passed"]:
                continue
            picks.append({"symbol": sym, "legacy_rank": round(legacy_rank, 1),
                          "institutional_quality": quality, "industry": industry})
            if len(picks) >= c["top_constituents"]:
                break

        max_capacity = max(decisions[a]["capacity_pct"] for a in accounts)
        low = min(float(c["size_band_pct"][0]), max_capacity)
        high = min(float(c["size_band_pct"][1]), max_capacity)
        if high < 1.0:
            continue
        low = min(low, high)
        etf_px = _prices(cur, [r["etf"]]).get(r["etf"])
        etf_e = enrich.get(r["etf"]) or {}
        sma20_lvl = round(etf_px / (1 + (etf_e.get("sma20_pct") or 0) / 100), 2) if etf_px else None
        instruments = [{"symbol": r["etf"], "kind": "sector ETF", "note": "policy and risk-capacity qualified", "price": etf_px}]
        instruments += [{"symbol": p["symbol"], "kind": "constituent",
                         "note": f"institutional quality {p['institutional_quality']['score']:.0f}; {p['industry']}",
                         "price": px.get(p["symbol"]), "quality": p["institutional_quality"]}
                        for p in picks]
        if not picks:
            instruments[0]["note"] += " — ETF only; no stock passed close-industry + quality rails"
        pct_band = [round(low, 2), round(high, 2)]
        band = dollars_band(pct_band, accounts, equities or {})
        cards.append({
            "id": f"rotatein-{r['etf']}-{as_of}", "group": "get_into",
            "title": f"ROTATE-IN · {r['sector']} ({r['state']}, RS20 {r['rs20']:+.1f})",
            "instruments": instruments, "accounts": accounts, "direction": "long",
            "size_band": f"{pct_band[0]}–{pct_band[1]}% of account equity",
            "entry_logic": "stagger only on pullbacks toward the 20DMA; capacity is volatility/correlation adjusted",
            "invalidation": f"{r['sector']} exits {r['state']} on a two-close confirmation or risk capacity falls below 1%",
            "factors": [
                {"name": "sector state", "value": r["state"]},
                {"name": "RS20 vs SPY", "value": f"{r['rs20']:+.2f}%"},
                {"name": "book weight", "value": f"{r.get('book_pct') or 0}%"},
                {"name": "breadth", "value": f"{r.get('breadth_pct')}% exact-20-session measure"},
                {"name": "realized volatility", "value": f"{risk.get('annualized_vol_pct')}%"},
                {"name": "correlation to SPY", "value": str(risk.get("correlation"))},
                {"name": "max policy capacity", "value": f"{max_capacity:.2f}%"},
            ],
            "as_of": as_of, "mode": "SHADOW",
            "levels": {"price": etf_px, "entry_zone": f"pullback toward 20DMA ≈ ${sma20_lvl}" if sma20_lvl else "stagger on pullbacks",
                       "stop": f"thesis stop: {r['sector']} exits {r['state']} (two-close)"},
            "dollars_by_account": band, "impact_dollars": max((v[1] for v in band.values()), default=0),
            "allocation_policy": decisions, "risk_context": risk,
            "quality_gate": {"industry_capture_kind": industry_snap.get("capture_kind"),
                             "stock_picks_passed": len(picks), "version": RECOMMENDATION_CALC_VERSION},
            "routes": {"proposal": "watch-directive path — operator approves; nothing self-executes"},
        })
        if len(cards) >= c["max_cards"]:
            break
    return cards
'''
    text = replace_regex(text, r'def rotate_in\(sectors, cur, enrich, as_of, equities=None\) -> list:.*?(?=\n\n_ALIAS_CACHE = None)',
                         rotate, "risk aware rotate in")
    text = replace_once(
        text,
        '    sectors = sector_snap.get("rows") or []\n    market = sector_snap.get("market") or {}\n',
        '    sectors = sector_snap.get("rows") or []\n    market = sector_snap.get("market") or {}\n    lean_review = directive_review_status((CFG.get("rotation_pairs") or {}).get("defensive_lean") or {}, sectors)\n',
        "directive review",
    )
    old_empty = '''        "get_into": ("DEFENSIVE LEAN active: cyclical rotate-ins excluded — no defensive sector "
                     "(Utilities/Staples/Healthcare) is LEADING+underweight right now"
                     if (CFG.get("rotation_pairs") or {}).get("defensive_lean", {}).get("enabled")
                     else "no LEADING/IMPROVING sector is underweight vs your neutral map"),
'''
    new_empty = '''        "get_into": ("DEFENSIVE LEAN active and due for dated review; non-defensive leadership remains research-only"
                     if lean_review.get("requires_review") else
                     "no LEADING/IMPROVING sector has benchmark-, mandate-, volatility- and correlation-adjusted capacity"),
'''
    text = replace_once(text, old_empty, new_empty, "empty reason")
    old_tail = '''        "sources": {
            "sectors": sector_snap.get("generated_at"),
            "industries": industries.get("captured_at"),
            "hedging_radar": (_load("hedging_radar_latest.json") or {}).get("captured_at"),
        },
    }
'''
    new_tail = '''        "sources": {
            "sectors": sector_snap.get("generated_at"),
            "industries": industries.get("captured_at"),
            "hedging_radar": (_load("hedging_radar_latest.json") or {}).get("captured_at"),
        },
        "calculation_version": RECOMMENDATION_CALC_VERSION,
        "directive_reviews": [lean_review],
        "truth_ledger": truth_ref(source="sector + industry + holdings + account capabilities",
            as_of=as_of, calculation_version=RECOMMENDATION_CALC_VERSION,
            cadence="nightly", quality="shadow_advisory",
            notes=["no broker, order, approval or configuration-promotion authority"]),
    }
    snap["snapshot_hash"] = snapshot_hash(snap)
'''
    text = replace_once(text, old_tail, new_tail, "recommendation snapshot truth")
    write(path, text)


# ── Focused wiring tests and documentation ─────────────────────────────────────

def write_wiring_tests() -> None:
    write("tests/test_defense_data_hardening_wiring.py", '''from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_sector_engine_uses_exact_20_distinct_sessions_and_sample_label():
    text = (ROOT / "scripts/sector_momentum_engine.py").read_text()
    assert "GROUP BY symbol, price_date" in text
    assert "WHERE session_n = 20" in text
    assert "top-movers NH/NL sample" in text
    assert "broad strength" not in text


def test_industry_engine_uses_same_finviz_view_for_spy_and_groups():
    text = (ROOT / "scripts/finviz_industry_groups.py").read_text()
    assert '_finviz_fetch_view(["SPY"], 141' in text
    assert "same_vendor_same_run" in text
    assert "sector_map(cur)" not in text


def test_recommendations_are_risk_and_quality_aware():
    text = (ROOT / "scripts/defense_recommendations.py").read_text()
    for token in ("allocation_decision", "realized_vol_corr", "stock_quality_assessment",
                  "requires_close_confirmed_industry", "directive_reviews"):
        assert token in text


def test_fund_lookthrough_exposes_provenance_and_unmapped_weight():
    text = (ROOT / "scripts/fund_lookthrough.py").read_text()
    for token in ("factsheet_as_of", "refresh_due", "coverage_pct", "unmapped_weight_pct", "_provenance"):
        assert token in text
''')
    write("docs/architecture/DEFENSE_SECTORS_DATA_HARDENING_2026-07-24.md", '''# Defense/Sectors Data Hardening — 2026-07-24

Status: draft, SHADOW/advisory only. No deployment, broker, order, approval, 2FA, service or production-config action.

## Implemented

1. Sector breadth now uses exactly 20 distinct daily closes per covered constituent and reports membership/coverage quality.
2. Capped market-mover counts are labeled as a top-movers sample, never comprehensive breadth.
3. Sector, industry, fund and recommendation snapshots carry source/as-of/calculation/quality coverage and SHA-256 snapshot hashes.
4. Industry groups and SPY use Finviz Elite performance view 141 in the same run; missing SPY data fails closed.
5. Sector rows older than the configured calendar-day tolerance are quarantined and cannot drive transitions or recommendations.
6. Industry-to-sector assignment uses a reviewed, versioned exact/rule map; unmapped groups are explicit and quarantined.
7. Rotate-in capacity is tied to an explicit benchmark and account mandate, then scaled by realized volatility and correlation and capped by sector policy.
8. Stock candidates require close-observed industry confirmation plus transparent valuation, growth, ROIC, leverage, profitability, crowding, beta and extension coverage. Missing evidence fails closed; ETF-only is allowed.
9. Fund look-through now exposes provider, factsheet date, refresh due date, mapped coverage, unmapped weight, quality and config hash.
10. The July 18 defensive lean receives a deterministic dated review record. It remains active until operator adjudication and is never auto-revoked.

## Render gate

Playwright intercepts representative payloads transcribed from the operator-provided live endpoint screenshots and renders `/v3/defense` and `/v3/sectors` at 1440px and 390px. The gate asserts truth labels and no horizontal overflow, then uploads four screenshots.

This fixture gate validates the frontend branch deterministically. A final host-side smoke remains required after deployment because GitHub runners cannot reach the private Tailnet host.
''')


def main() -> None:
    patch_configs()
    write("scripts/fund_lookthrough.py", FUND_LOOKTHROUGH)
    patch_sector_engine()
    patch_industry_engine()
    patch_recommendations()
    write_wiring_tests()
    print("Defense/Sectors data hardening applied")


if __name__ == "__main__":
    main()
