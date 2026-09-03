#!/usr/bin/env python3
"""
Phase 2b — Finviz Analyst Intelligence + Weekly Report Enhancement
Fixes:
1. finviz_enrichment.py: add view 121 (Valuation) for target_price, eps, forward_pe
2. finviz_enrichment.py: fix recom parsing (currently stores as % string, not float)
3. finviz_enrichment.py: add analyst_rating text mapping from recom score
4. portfolio_weekly_report.py: inject analyst data + Brave search into prompts
5. portfolio_weekly_report.py: add rebalancing WHY section with source citations
"""

import ast, re
from pathlib import Path

root = Path(".")
ok = []
fail = []

# ═══════════════════════════════════════════════════════════
# FIX 1: finviz_enrichment.py — add view 121, fix recom
# ═══════════════════════════════════════════════════════════
path = root / "scripts/finviz_enrichment.py"
c = path.read_text()

# Add view 121 (Valuation) to VIEWS dict
old_views_end = """    171: {  # Technical — RSI, SMA, ATR, Beta (NO COOKIE NEEDED)
        1: "ticker", 2: "beta", 3: "atr",
        4: "sma20_pct", 5: "sma50_pct", 6: "sma200_pct",
        7: "week52_high_pct", 8: "week52_low_pct",
        9: "rsi", 10: "price", 11: "change_pct",
        12: "change_from_open_pct", 13: "gap_pct", 14: "volume",
    },
}"""

new_views_end = """    121: {  # Valuation — EPS, Forward PE, Target Price
        1: "ticker", 2: "market_cap_b3",
        3: "pe2", 4: "forward_pe", 5: "peg",
        6: "ps", 7: "pb", 8: "pc", 9: "pfcf",
        10: "eps_ttm", 11: "eps_next_q", 12: "eps_next_y",
        13: "eps_next_5y", 14: "eps_past_5y",
        15: "sales_past_5y", 16: "eps_qoq", 17: "sales_qoq",
        18: "price2", 19: "change_pct2", 20: "volume2",
    },
    171: {  # Technical — RSI, SMA, ATR, Beta (NO COOKIE NEEDED)
        1: "ticker", 2: "beta", 3: "atr",
        4: "sma20_pct", 5: "sma50_pct", 6: "sma200_pct",
        7: "week52_high_pct", 8: "week52_low_pct",
        9: "rsi", 10: "price", 11: "change_pct",
        12: "change_from_open_pct", 13: "gap_pct", 14: "volume",
    },
}"""

if old_views_end in c:
    c = c.replace(old_views_end, new_views_end)
    ok.append("Fix 1a: View 121 (Valuation/EPS) added to VIEWS")
else:
    fail.append("Fix 1a: VIEWS end marker not found")

# Add view 121 duplicate skip fields
old_skip = 'SKIP_DUPLICATES = {"price", "change_pct", "volume", "market_cap_b2",\n                   "avg_vol_m2", "earnings_date2"}'
new_skip = 'SKIP_DUPLICATES = {"price", "change_pct", "volume", "market_cap_b2", "market_cap_b3",\n                   "avg_vol_m2", "earnings_date2", "pe2", "price2", "change_pct2", "volume2"}'
if old_skip in c:
    c = c.replace(old_skip, new_skip)
    ok.append("Fix 1b: SKIP_DUPLICATES updated for view 121")
else:
    fail.append("Fix 1b: SKIP_DUPLICATES marker not found")

# Add view 121 to default views list
old_default_views = "views = [111, 131, 141, 171]  # skip 161 by default (fundamentals slow)"
new_default_views = "views = [111, 121, 131, 141, 171]  # 121=valuation/EPS, skip 161 (fundamentals slow)"
if old_default_views in c:
    c = c.replace(old_default_views, new_default_views)
    ok.append("Fix 1c: View 121 added to default enrichment views")
else:
    fail.append("Fix 1c: default views marker not found")

# Fix recom parsing — it's stored as % string, need to strip % and parse as float
# Add post-processing to convert recom to proper score + text label
old_postproc_marker = "    return results"
# Find it in the enrich function (not just any return)
# Add analyst rating computation after all views are merged
old_merge_end = """    for sym, data in results.items():
        # Compute derived fields
        price = data.get("price", 0) or 0
        sma200 = data.get("sma200_pct")
        rsi = data.get("rsi")
        data["rsi_status"] = (
            "overbought" if rsi and rsi > 70
            else "oversold" if rsi and rsi < 30
            else "neutral" if rsi else None
        )
        data["trend"] = (
            "above_200" if sma200 and sma200 > 0
            else "below_200" if sma200 and sma200 < 0
            else "at_200" if sma200 is not None else None
        )"""

new_merge_end = """    for sym, data in results.items():
        # Compute derived fields
        price = data.get("price", 0) or 0
        sma200 = data.get("sma200_pct")
        rsi = data.get("rsi")
        data["rsi_status"] = (
            "overbought" if rsi and rsi > 70
            else "oversold" if rsi and rsi < 30
            else "neutral" if rsi else None
        )
        data["trend"] = (
            "above_200" if sma200 and sma200 > 0
            else "below_200" if sma200 and sma200 < 0
            else "at_200" if sma200 is not None else None
        )
        # Fix recom: stored as "1.97%" string — strip %, parse as float, map to label
        recom_raw = data.get("recom")
        if recom_raw is not None:
            try:
                recom_score = float(str(recom_raw).replace("%","").strip())
                data["recom_score"] = round(recom_score, 2)
                data["analyst_rating"] = (
                    "Strong Buy"  if recom_score < 1.5 else
                    "Buy"         if recom_score < 2.5 else
                    "Hold"        if recom_score < 3.5 else
                    "Sell"        if recom_score < 4.5 else
                    "Strong Sell"
                )
            except (ValueError, TypeError):
                data["recom_score"] = None
                data["analyst_rating"] = None"""

if old_merge_end in c:
    c = c.replace(old_merge_end, new_merge_end)
    ok.append("Fix 1d: recom parsing fixed + analyst_rating text label added")
else:
    fail.append("Fix 1d: merge end marker not found")

try:
    ast.parse(c)
    path.write_text(c)
    ok.append("✅ finviz_enrichment.py syntax OK")
except SyntaxError as e:
    fail.append(f"❌ finviz_enrichment.py SYNTAX ERROR line {e.lineno}: {e.msg}")

# ═══════════════════════════════════════════════════════════
# FIX 2: portfolio_weekly_report.py — analyst intelligence section
# ═══════════════════════════════════════════════════════════
path = root / "scripts/portfolio_weekly_report.py"
c = path.read_text()

# Add analyst intelligence builder function
if "_build_analyst_intelligence" not in c:
    insert_before = "def _generate_narrative"
    analyst_func = '''def _build_analyst_intelligence(holdings_data: Dict, enrichment: Dict) -> Dict:
    """Build analyst intelligence: ratings, targets, rebalancing WHY, Brave commentary."""
    holdings = holdings_data.get("holdings", [])
    CASH_SYMS = {"CASH","--","SNSXX","SWVXX","SPRXX","VMFXX","FDRXX"}

    analyst_data = []
    for h in sorted(holdings, key=lambda x: x.get("market_value",0), reverse=True):
        sym = h.get("symbol","")
        if not sym or sym in CASH_SYMS or ("-" in sym and len(sym) > 5):
            continue
        e = enrichment.get(sym, {})
        if not isinstance(e, dict):
            continue

        # Finviz consensus: 1=Strong Buy → 5=Strong Sell
        rating   = e.get("analyst_rating")          # text label we just added
        score    = e.get("recom_score")              # numeric 1.0-5.0
        pe       = e.get("pe")
        fwd_pe   = e.get("forward_pe")
        eps_next = e.get("eps_next_q")
        eps_next_y = e.get("eps_next_y")
        sma200   = e.get("sma200_pct")
        rsi      = e.get("rsi")
        inst_own = e.get("inst_own_pct")
        inst_txn = e.get("inst_trans_pct")          # +ve = buying, -ve = selling
        short_f  = e.get("short_float_pct")
        target   = e.get("target_price")             # from view 121 if available

        mv       = h.get("market_value", 0) or 0
        port_pct = h.get("portfolio_pct", 0) or 0
        cost     = h.get("cost_basis")
        gain_pct = h.get("gain_loss_pct")

        analyst_data.append({
            "symbol":      sym,
            "account":     h.get("account_display", h.get("account","")),
            "market_value": mv,
            "portfolio_pct": port_pct,
            "cost_basis":  cost,
            "gain_loss_pct": gain_pct,
            "analyst_rating": rating or "—",
            "recom_score": score,
            "target_price": target,
            "pe":          pe,
            "forward_pe":  fwd_pe,
            "eps_next_q":  eps_next,
            "eps_next_y":  eps_next_y,
            "sma200_pct":  sma200,
            "rsi":         rsi,
            "inst_own_pct": inst_own,
            "inst_trans_pct": inst_txn,
            "short_float_pct": short_f,
            "source": "Finviz Elite (consensus)"
        })

    # Sort: highest concern first (sell ratings, overbought, high concentration)
    def _concern_score(a):
        s = 0
        if a.get("recom_score") and a["recom_score"] >= 3.5: s += 30
        if a.get("rsi") and a["rsi"] > 70: s += 20
        if a.get("portfolio_pct", 0) > 15: s += 20
        if a.get("inst_trans_pct") and a["inst_trans_pct"] < -2: s += 10
        return s

    analyst_data.sort(key=_concern_score, reverse=True)
    return {"positions": analyst_data, "source": "Finviz Elite consensus ratings"}


def _build_rebalance_rationale(risk_data: Dict, holdings_data: Dict,
                                enrichment: Dict) -> list:
    """Build rebalancing WHY with drift explanation and analyst context."""
    positions = risk_data.get("positions", {})
    if not isinstance(positions, dict):
        return []

    rationale = []
    for sym, pos in positions.items():
        if not isinstance(pos, dict) or not pos.get("action"):
            continue
        action    = pos.get("action","")
        amount    = pos.get("amount", 0)
        note      = pos.get("note","")
        account   = pos.get("account","")
        e         = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}
        rating    = e.get("analyst_rating","—")
        score     = e.get("recom_score")
        sma200    = e.get("sma200_pct")
        rsi       = e.get("rsi")
        inst_txn  = e.get("inst_trans_pct")

        # Build WHY explanation
        reasons = []
        if note:
            reasons.append(f"Drift: {note}")
        if score and score >= 3.5:
            reasons.append(f"Analyst consensus: {rating} ({score:.1f}/5.0) — unfavorable")
        elif score and score <= 2.0:
            reasons.append(f"Analyst consensus: {rating} ({score:.1f}/5.0) — favorable")
        if rsi and rsi > 70 and action == "SELL":
            reasons.append(f"Technically overbought (RSI {rsi:.0f})")
        if rsi and rsi < 30 and action == "BUY":
            reasons.append(f"Technically oversold (RSI {rsi:.0f}) — potential entry")
        if sma200 and sma200 > 0 and action == "BUY":
            reasons.append(f"Above SMA200 (+{sma200:.1f}%) — uptrend confirmed")
        if sma200 and sma200 < -5 and action == "SELL":
            reasons.append(f"Below SMA200 ({sma200:.1f}%) — downtrend risk")
        if inst_txn and inst_txn < -2:
            reasons.append(f"Institutions reducing position ({inst_txn:+.1f}%)")
        elif inst_txn and inst_txn > 2:
            reasons.append(f"Institutions increasing position ({inst_txn:+.1f}%)")

        rationale.append({
            "symbol":   sym,
            "account":  account,
            "action":   action,
            "amount":   amount,
            "analyst_rating": rating,
            "recom_score": score,
            "reasons":  reasons,
            "source":   "Finviz Elite (consensus rating, technical, institutional flow)"
        })

    return sorted(rationale, key=lambda x: abs(x.get("amount",0)), reverse=True)


def _get_brave_analyst_commentary(symbols: list, brave_api_key: str) -> Dict:
    """Analyst commentary discovered via the governed Brave research router.

    This function used to hold its own key read, its own ``urlopen`` and its own
    cap ("top 5 to stay within 2000/mo free tier"). Three things were wrong with
    that:

    * **It bypassed the ledger entirely.** None of these calls were counted, so
      the budget alarm reported a healthy percentage against an unrepresentative
      sensor while the provider approached its ceiling.
    * **The tier was invented, and disagreed with the other invented tier.**
      ``brave_search`` hardcoded 1,000/month; this said 2,000. Measured live
      2026-09-03 the plan publishes ``50;w=1, 0;w=2592000`` — 50 requests per
      *second* and no metered monthly window at all. Neither number was real.
    * **``except Exception: pass`` erased the reason.** A 401, a rate-limit and
      a genuinely quiet week were indistinguishable, so a silent bypass looked
      exactly like a stock nobody wrote about.

    Commentary is discovery evidence: every snippet is attributed
    ``SEARCH_DISCOVERY`` and is never analyst fact.
    """
    if not symbols:
        return {}

    try:
        from scripts.lib import brave_research_router as _router
    except ImportError:                                      # pragma: no cover
        try:
            from lib import brave_research_router as _router  # type: ignore
        except ImportError:
            print("  [brave] research router unavailable — DENY (never fail open)")
            return {}

    REPUTABLE = (
        "reuters", "bloomberg", "wsj", "barrons", "marketwatch", "cnbc",
        "seekingalpha", "zacks", "tipranks", "benzinga", "fool", "finviz",
        "nasdaq", "investing",
    )

    commentary: Dict = {}
    for sym in symbols:
        outcome = _router.search(
            f"{sym} stock analyst rating price target 2026",
            purpose=_router.Purpose.EVIDENCE_GAP,
            priority=_router.Priority.HELD_CAPITAL,
            caller="phase2b_analyst",
            count=3, freshness="pw",
        )
        if outcome.status in (_router.Status.DENIED_BUDGET,
                              _router.Status.DENIED_RESERVE,
                              _router.Status.DENIED_PURPOSE_QUOTA,
                              _router.Status.BUDGET_UNAVAILABLE):
            # Budget is a run-level condition, not a per-symbol one: stop rather
            # than burn the loop re-asking a question already answered "no".
            print(f"  [brave] {outcome.status.value} at {sym} — "
                  f"{outcome.degradation_note()}")
            break
        if outcome.degraded:
            print(f"  [brave] {sym}: {outcome.status.value} — "
                  f"{outcome.degradation_note()}")
            continue

        snippets = [
            {"title": r.title[:100], "snippet": r.description[:200],
             "source": r.source_domain, "url": r.url,
             "attribution": r.attribution}
            for r in outcome.results
            if any(d in (r.source_domain or "") for d in REPUTABLE)
        ]
        if snippets:
            commentary[sym] = snippets
            _router.record_adoption(outcome.fingerprint, purpose=outcome.purpose)

    return commentary



'''
    if insert_before in c:
        c = c.replace(insert_before, analyst_func + insert_before)
        ok.append("Fix 2a: Analyst intelligence builder functions added")
    else:
        fail.append("Fix 2a: insert point not found")

# Wire analyst data into the main run_weekly_report function
# Find where data is loaded and add analyst + rebalance rationale
old_data_load = """    risk_data = _load_state("risk_management.json")"""
new_data_load = """    risk_data = _load_state("risk_management.json")
    holdings_raw = _load_state("holdings.json")

    # Build analyst intelligence
    analyst_intel = _build_analyst_intelligence(holdings_raw, data.get("enrichment", {}))
    rebal_rationale = _build_rebalance_rationale(
        risk_data, holdings_raw, data.get("enrichment", {}))

    # Brave analyst commentary for top 5 holdings by value
    import os as _os
    brave_key = _os.getenv("BRAVE_API_KEY", "")
    top_syms = [p["symbol"] for p in analyst_intel.get("positions", [])[:5]]
    brave_commentary = _get_brave_analyst_commentary(top_syms, brave_key)
    if brave_commentary:
        print(f"[weekly-report] Brave: {len(brave_commentary)} symbols with commentary")"""

if old_data_load in c and "_build_analyst_intelligence" in c:
    if "analyst_intel" not in c:
        c = c.replace(old_data_load, new_data_load)
        ok.append("Fix 2b: Analyst data wired into weekly run")
    else:
        ok.append("Fix 2b: Already wired (skipped)")
else:
    fail.append("Fix 2b: risk_data marker not found")

# Add analyst section to JSON output
old_json_end = """        "narratives": narratives,
        "html_path": str(html_path),
        "docx_path": str(docx_path) if docx_path else "",
    }"""
new_json_end = """        "narratives": narratives,
        "html_path": str(html_path),
        "docx_path": str(docx_path) if docx_path else "",
        "analyst_positions": analyst_intel.get("positions", [])[:10] if 'analyst_intel' in dir() else [],
        "rebal_rationale": rebal_rationale[:8] if 'rebal_rationale' in dir() else [],
        "brave_commentary": brave_commentary if 'brave_commentary' in dir() else {},
    }"""

if old_json_end in c and "analyst_positions" not in c:
    c = c.replace(old_json_end, new_json_end)
    ok.append("Fix 2c: Analyst data added to weekly JSON")
else:
    fail.append("Fix 2c: JSON end marker not found or already patched")

# Add analyst-aware prompt to _generate_narrative
# Add a 6th narrative section for analyst intelligence
old_action_return = """    narratives["action"] = _ollama(prompt5)

    return narratives"""

new_action_return = '''    narratives["action"] = _ollama(prompt5)

    # ── PROMPT 6: Analyst Intelligence & Rebalancing WHY ─────────────────────
    # Build analyst context string
    analyst_lines = ""
    for p in analyst_intel.get("positions", [])[:8] if "analyst_intel" in dir() else []:
        score = p.get("recom_score")
        score_str = f"{score:.1f}" if score else "—"
        analyst_lines += (
            f"  {p['symbol']}: {p['analyst_rating']} ({score_str}/5.0) "
            f"RSI={p.get('rsi') or '—'} SMA200={p.get('sma200_pct',0):+.1f}% "
            f"InstFlow={p.get('inst_trans_pct',0):+.1f}% "
            f"Port={p.get('portfolio_pct',0):.1f}%\\n"
        )

    rebal_lines = ""
    for r in rebal_rationale[:5] if "rebal_rationale" in dir() else []:
        reasons_str = " | ".join(r.get("reasons", [])[:3])
        rebal_lines += (
            f"  {r['action']} {r['symbol']} ${abs(r.get('amount',0)):,.0f} "
            f"({r['analyst_rating']}) — {reasons_str}\\n"
        )

    brave_lines = ""
    for sym, items in (brave_commentary.items() if "brave_commentary" in dir() else {}.items()):
        for item in items[:1]:
            brave_lines += f"  {sym} ({item['source']}): {item['snippet'][:150]}\\n"

    prompt6 = f"""/no_think
You are a professional wealth manager. Analyze analyst consensus and rebalancing rationale for John W. Whiting.
SOURCE: Finviz Elite consensus ratings (institutional, not individual advisor)

ANALYST RATINGS BY POSITION (1=Strong Buy, 3=Hold, 5=Strong Sell):
{analyst_lines if analyst_lines else "Run pipeline with Finviz Elite to populate"}

REBALANCING ORDERS WITH RATIONALE:
{rebal_lines if rebal_lines else "No rebalancing orders computed"}

RECENT ANALYST COMMENTARY (from public sources):
{brave_lines if brave_lines else "Brave search not configured or no results"}

Write 3 sentences:
1. Which positions have the strongest analyst support and why the data supports holding/buying
2. Which positions analysts are cautious on and why the rebalancing is recommended (cite the drift/technical/rating reason)
3. One contrarian note — where Finviz consensus might be wrong based on John's personal thesis (AI WWIII defense, Roth conversion priority)
Be specific. Cite Finviz as source. Never fabricate analyst firm names."""

    narratives["analyst_intelligence"] = _ollama(prompt6)

    return narratives'''

if old_action_return in c:
    c = c.replace(old_action_return, new_action_return)
    ok.append("Fix 2d: Analyst intelligence prompt (section 6) added")
else:
    fail.append("Fix 2d: action return marker not found")

try:
    ast.parse(c)
    path.write_text(c)
    ok.append("✅ portfolio_weekly_report.py syntax OK")
except SyntaxError as e:
    fail.append(f"❌ portfolio_weekly_report.py SYNTAX ERROR line {e.lineno}: {e.msg}")
    lines = c.splitlines()
    for i in range(max(0, e.lineno - 4), min(len(lines), e.lineno + 3)):
        fail.append(f"  {i + 1}: {lines[i]}")

# ═══════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 2b RESULTS — Analyst Intelligence")
print("=" * 60)
for msg in ok:
    print(f"  ✅ {msg}")
for msg in fail:
    print(f"  ❌ {msg}")
print(f"\n{len(ok)} OK, {len(fail)} failed")
