#!/usr/bin/env python3
"""strategy_planner.py — interactive portfolio strategy planner (operator 2026-06-17).

The full loop the operator asked for:
  1. DECLARE  an intent ("roll Fidelity 401k to cash", "trim XLB 50sh", "add $20k income")
  2. IMPACT   what-if (read-only): look-through theme delta, account refactor, cash freed, income/goal hit
  3. ADVISE   goal-aligned redeploy ("what should I invest in") via the free LLM lane + watchlist candidates
  4. APPROVE  → persist to strategy_plans  +  sync to LEARNING (llm_feedback_observations)
              +  sync to DISCOVERY (auto-create watch_directives that seed the discovery/watchlist engine)

Reuses: lookthrough_themes.json (per-account theme exposure), holdings.json, llm_lane (CIO advisor),
watch_directives (discovery seed), llm_feedback_observations (learning loop). Advisory + read-only until
the operator approves; approval writes a plan and seeds discovery — it never places a trade.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATE = ROOT / "data" / "portfolios" / "state"

INCOME_TARGET = 55000          # operator annual passive-income goal (alex_retirement_advisor)
CONCENTRATION_LINE = 5.0       # single-name comfort line, %


def _load(p, d):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return d


def _holdings():
    return _load(STATE / "holdings.json", {}).get("holdings", [])


def _lookthrough():
    return _load(STATE / "lookthrough_themes.json", {"themes": {}, "accounts_detail": {}})


_YIELD_SANE_MAX = 25.0   # reject feed garbage (e.g. ticker_dividend_data had SCHD at 12.98%)


def _yield_map(symbols) -> dict:
    """Per-symbol dividend yield % from the computed dividend_calendar — the authoritative source: it is
    derived from the operator's actual holdings + real distributions ($14.5k/yr reconciled) and covers every
    meaningful payer (SCHD, JEPI, BDCs, BND, defense divs, …). The raw ticker_dividend_data feed is NOT used —
    it reported systematically inflated yields (SCHD 12.98%, BAH 12.33% vs ~3.6%/1.7% real). Symbols absent
    from the calendar are non-payers (growth stocks, accumulating/tax-deferred funds) → 0.0."""
    syms = {(s or "").upper() for s in symbols if s}
    out = {}
    if not syms:
        return out
    try:
        for p in _load(STATE / "dividend_calendar.json", {}).get("payers", []):
            sym = (p.get("symbol") or "").upper()
            y = p.get("yield_pct")
            if sym in syms and y is not None and 0 <= float(y) <= _YIELD_SANE_MAX:
                out[sym] = max(out.get(sym, 0.0), float(y))
    except Exception:
        pass
    return out


def _holding_income(rows, fraction=1.0) -> tuple[int, list, dict]:
    """Precise annual income for holding rows = sum(market_value × yield%) × fraction.
    Returns (total_income, per-symbol breakdown high→low, coverage{priced, no_yield_value})."""
    ymap = _yield_map([r.get("symbol") for r in rows])
    by_sym, covered_val, uncovered_val = {}, 0.0, 0.0
    for r in rows:
        sym = (r.get("symbol") or "").upper()
        mv = float(r.get("market_value") or 0) * fraction
        if sym in ymap:
            covered_val += mv
            inc = mv * (ymap[sym] / 100.0)
            if inc:
                by_sym[sym] = by_sym.get(sym, 0.0) + inc
        else:
            uncovered_val += mv
    breakdown = [{"symbol": s, "annual_income": round(v), "yield_pct": round(ymap.get(s, 0.0), 2)}
                 for s, v in sorted(by_sym.items(), key=lambda kv: -kv[1])]
    coverage = {"priced_value": round(covered_val), "no_yield_data_value": round(uncovered_val)}
    return round(sum(by_sym.values())), breakdown, coverage


# ── intent ──────────────────────────────────────────────────────────────────
def normalize_intent(intent: dict) -> dict:
    """Coerce the operator's intent into a canonical shape."""
    it = dict(intent or {})
    it["action"] = (it.get("action") or "liquidate").lower()
    it["account"] = it.get("account")
    it["symbol"] = (it.get("symbol") or "").upper() or None
    it["to"] = (it.get("to") or "cash").lower()
    it["amount"] = it.get("amount")          # dollars, shares, or "all"
    it["note"] = it.get("note") or ""
    return it


# ── stage 2: impact (what-if) ────────────────────────────────────────────────
def compute_impact(intent: dict) -> dict:
    it = normalize_intent(intent)
    lt = _lookthrough()
    holdings = _holdings()
    total = sum(float(h.get("market_value") or 0) for h in holdings if not h.get("is_cash")) or 1.0
    acct = it["account"]
    ad = (lt.get("accounts_detail") or {}).get(acct or "", {})

    # what's being freed (income_rows + income_fraction drive the precise per-holding income math)
    income_rows, income_fraction = [], 1.0
    if it["action"] == "liquidate" and acct:
        rows = [h for h in holdings if h.get("account") == acct and not h.get("is_cash")]
        cash_freed = sum(float(h.get("market_value") or 0) for h in rows)
        before_positions = [{"symbol": h.get("symbol"), "value": round(float(h.get("market_value") or 0))}
                            for h in sorted(rows, key=lambda r: -(float(r.get("market_value") or 0)))]
        income_rows = rows                       # whole account liquidated → full income of every row
    elif it["action"] == "trim" and it["symbol"]:
        rows = [h for h in holdings if (h.get("symbol") or "").upper() == it["symbol"]
                and (not acct or h.get("account") == acct)]
        amt = it["amount"]
        held_val = sum(float(h.get("market_value") or 0) for h in rows)
        cash_freed = held_val if amt in ("all", None) else float(str(amt).replace("$", "").replace(",", ""))
        cash_freed = min(cash_freed, held_val)
        before_positions = [{"symbol": it["symbol"], "value": round(held_val), "trimming": round(cash_freed)}]
        income_rows = rows                        # trimming a fraction loses that fraction of the income
        income_fraction = (cash_freed / held_val) if held_val else 0.0
    else:  # add / rebalance — cash deployed in, not freed
        amt = it["amount"] or 0
        cash_freed = float(str(amt).replace("$", "").replace(",", "")) if amt else 0
        before_positions = []

    # precise annual income lost = sum(market_value * dividend yield%), per affected holding
    income_lost, income_breakdown, income_coverage = _holding_income(income_rows, income_fraction)
    blended_yield = round(income_lost / cash_freed * 100, 2) if cash_freed else 0.0
    _uncov = income_coverage.get("no_yield_data_value", 0)
    income_note = ("freed cash earns ~0 until redeployed — income gap widens until you reinvest"
                   if income_lost else
                   (f"no dividend data for ${_uncov:,} of these holdings (e.g. tax-deferred 401k funds — "
                    "their distributions reinvest and don't count toward the spendable income goal)"
                    if _uncov else "these holdings pay no distributions"))

    # look-through theme delta (per-account exposure is pre-computed)
    theme_delta = []
    acct_themes = ad.get("themes", {}) if it["action"] == "liquidate" else {}
    pf_themes = lt.get("themes", {})
    for name, tv in pf_themes.items():
        before_val = float(tv.get("value") or 0)
        lost = float((acct_themes.get(name) or {}).get("value") or 0)
        after_val = max(0.0, before_val - lost)
        if before_val <= 0 and after_val <= 0:
            continue
        bpct, apct = round(before_val / total * 100, 2), round(after_val / total * 100, 2)
        if abs(bpct - apct) >= 0.05:
            theme_delta.append({"theme": name, "before_pct": bpct, "after_pct": apct,
                                "delta_pct": round(apct - bpct, 2), "value_lost": round(lost)})
    theme_delta.sort(key=lambda d: d["delta_pct"])   # biggest drops first

    # cash % shift (cash stays in the portfolio for a roll-to-cash)
    cash_now = sum(float(h.get("market_value") or 0) for h in holdings if h.get("is_cash"))
    cash_after = cash_now + (cash_freed if it["action"] in ("liquidate", "trim") else 0)


    return {
        "intent": it,
        "portfolio_total": round(total),
        "cash_freed": round(cash_freed),
        "cash_pct_before": round(cash_now / total * 100, 2),
        "cash_pct_after": round(cash_after / total * 100, 2),
        "account_refactor": {"account": acct, "before": before_positions,
                             "after": ("100% cash" if it["action"] == "liquidate"
                                       else f"-{round(cash_freed)} from {it['symbol']}" if it["action"] == "trim"
                                       else f"+{round(cash_freed)} deployed")},
        "lookthrough_delta": theme_delta[:12],
        "income": {"target": INCOME_TARGET, "annual_income_lost": income_lost,
                   "blended_yield_pct": blended_yield, "by_holding": income_breakdown,
                   "coverage": income_coverage,
                   "method": "precise: sum(market_value × dividend yield% per holding)",
                   "note": income_note},
        "underweight_themes": [name for name, _ in
                               sorted(pf_themes.items(), key=lambda kv: float(kv[1].get("pct") or 0))[:5]],
    }


# ── stage 3: advise (goal-aligned redeploy) ──────────────────────────────────
def _candidates(limit=12):
    """Top watchlist names to redeploy into — reconciled against the CIO holistic verdict + analyst coverage
    depth so a momentum-ranked name the CIO says AVOID (or with 0-1 analysts) isn't handed to the LLM as a
    buy. Hermes rank ranks; the CIO view + coverage are the conviction check."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""SELECT w.symbol, w.hermes_rank, w.score, p.sector,
                              fs.recommendation AS cio_view, an.nop AS analyst_opinions
                       FROM watchlist_items w
                       LEFT JOIN symbol_profiles p ON p.symbol = w.symbol
                       LEFT JOIN LATERAL (SELECT recommendation FROM watchlist_final_synthesis f
                                          WHERE upper(f.symbol)=upper(w.symbol) ORDER BY created_at DESC LIMIT 1) fs ON true
                       LEFT JOIN LATERAL (SELECT number_of_analyst_opinions nop FROM yahoo_analyst_targets_history y
                                          WHERE upper(y.symbol)=upper(w.symbol) ORDER BY created_at DESC LIMIT 1) an ON true
                       WHERE w.status IN ('active','researched') AND w.symbol ~ '^[A-Z]{1,5}$'
                       ORDER BY w.hermes_rank ASC NULLS LAST LIMIT %s""", (limit * 3,))
        AVOID = {"AVOID", "IGNORE", "REBALANCE_TRIM"}
        out = []
        for r in cur.fetchall():
            cio = (r[4] or "").upper()
            if cio in AVOID:
                continue  # CIO rejected — never offer it as a redeploy buy
            nop = int(r[5]) if r[5] is not None else None
            out.append({"symbol": r[0], "rank": r[1], "score": float(r[2]) if r[2] else None, "sector": r[3],
                        "cio_view": cio or None, "analyst_opinions": nop,
                        "thin_coverage": nop is None or nop < 3})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def advise(intent: dict, impact: dict, lane: str | None = None) -> dict:
    cands = _candidates()
    try:
        import llm_lane
        use = lane or ("grok" if llm_lane.available("grok") else "local")
        prompt = (
            "You are the portfolio CIO/retirement strategist for a disability-optimized book. The operator is "
            "planning a portfolio move and needs a concrete redeploy plan ALIGNED TO GOALS.\n"
            f"GOALS: passive income target ${INCOME_TARGET:,}/yr; preserve disability benefits; tax-aware "
            "(Roth golden-window conversions); a standing AI-defense/aerospace thesis tilt.\n\n"
            f"PLANNED MOVE: {json.dumps(impact['intent'])}\n"
            f"WHAT-IF IMPACT (computed):\n{json.dumps({k: impact[k] for k in ('cash_freed','cash_pct_after','lookthrough_delta','income','account_refactor')}, indent=2)[:3500]}\n\n"
            f"REDEPLOY CANDIDATES (Hermes-ranked, CIO-AVOID names already removed; each shows cio_view + "
            f"analyst_opinions + thin_coverage — DISTRUST a thin-coverage upside):\n{json.dumps(cands)[:1800]}\n\n"
            "Give a SPECIFIC redeploy plan for the freed cash: a sleeve allocation (e.g. income / growth / "
            "defense / cash buffer) with rough %, and 3-6 concrete tickers or ETFs (prefer the candidates "
            "above + broad income/defense ETFs) with one-line rationale each tied to the income gap, the "
            "look-through gaps this move opens, and tax/benefit constraints. Be concrete and decision-useful, "
            "8-12 sentences. End with the single highest-priority next action.")
        text = llm_lane.generate(prompt, lane=use, timeout=120)
        return {"provider": "grok-3-mini" if use == "grok" else "local-gemma", "advice": str(text).strip(),
                "candidates": cands}
    except Exception as e:
        return {"provider": "none", "advice": f"(advisor unavailable: {str(e)[:120]})", "candidates": cands}


# ── stage 1+2+3 entry ────────────────────────────────────────────────────────
def plan(intent: dict, with_advice: bool = True, lane: str | None = None) -> dict:
    impact = compute_impact(intent)
    out = {"ok": True, "impact": impact}
    if with_advice:
        out["advice"] = advise(intent, impact, lane=lane)
    return out


# ── stage 4: approve → persist + sync to learning + discovery ─────────────────
def _ensure_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS strategy_plans (
        id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ DEFAULT now(),
        intent JSONB, impact JSONB, advice TEXT, advice_provider TEXT,
        target_directives JSONB, status TEXT DEFAULT 'approved',
        learning_obs_id BIGINT, directive_ids BIGINT[])""")


def approve(intent: dict, impact: dict, advice: dict, directives: list | None = None) -> dict:
    """Persist the approved plan, record a learning observation, and seed discovery via watch_directives."""
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    _ensure_table(cur)
    import json as _j
    it = normalize_intent(intent)
    directives = directives or []
    # 1) discovery: create operator watch_directives for the redeploy targets → discovery engine sources them.
    #    Matches the app-role create contract (kind ticker|sector|trend, spec jsonb). Commit per directive so
    #    one bad row never loses the rest or the plan itself.
    dir_ids = []
    for d in directives:
        kind = (d.get("kind") or "ticker").lower()
        if kind not in ("ticker", "sector", "trend"):
            kind = "ticker"
        label = (d.get("label") or d.get("spec") or "redeploy").strip()
        spec = {"symbol": label.upper()} if kind == "ticker" else {"term": label}
        try:
            # Watch Desk v2 (B1): family gate — alias into the survivor, no near-dups
            if kind == "trend":
                from lib.watch_directive_gate import family_gate, attach_alias
                _g = family_gate(label, "trend")
                if not _g["allow"]:
                    attach_alias(_g["survivor_id"], label,
                                 rationale=d.get("rationale"), created_by="strategy_planner")
                    dir_ids.append(_g["survivor_id"])
                    continue
            cur.execute("""INSERT INTO watch_directives
                (kind, label, spec, rationale, created_by, ttl_days, priority, status, trade_ai_enabled, hermes_enabled)
                VALUES (%s,%s,%s::jsonb,%s,'strategy_planner',%s,'normal','active',true,true) RETURNING id""",
                        (kind, label, _j.dumps(spec),
                         d.get("rationale") or f"Redeploy target from strategy plan: {it.get('note') or it['action']}",
                         int(d.get("ttl_days") or 30)))
            dir_ids.append(cur.fetchone()[0]); conn.commit()
        except Exception:
            conn.rollback()   # schema/dup → skip this directive, keep the plan
    # 2) learning: one observation so the approved direction trains the models
    obs_id = None
    try:
        cur.execute("""INSERT INTO llm_feedback_observations
            (source_table, workflow, model_role, model_name, decision_action, human_review_label, notes, metadata_json)
            VALUES ('strategy_plans','strategy_plan','operator',%s,%s,'approved',%s,%s) RETURNING id""",
            (advice.get("provider"), it["action"], (it.get("note") or "")[:500],
             json.dumps({"intent": it, "cash_freed": impact.get("cash_freed"),
                         "lookthrough_delta": impact.get("lookthrough_delta", [])[:6],
                         "directives": [d.get("label") for d in directives]})))
        obs_id = cur.fetchone()[0]
    except Exception:
        pass
    # 3) persist the plan
    cur.execute("""INSERT INTO strategy_plans (intent, impact, advice, advice_provider, target_directives,
                     learning_obs_id, directive_ids)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (json.dumps(it), json.dumps(impact), advice.get("advice"), advice.get("provider"),
                 json.dumps(directives), obs_id, dir_ids))
    plan_id = cur.fetchone()[0]
    conn.commit()
    return {"ok": True, "plan_id": plan_id, "learning_obs_id": obs_id, "directive_ids": dir_ids,
            "synced": {"learning": obs_id is not None, "discovery": len(dir_ids)},
            "message": f"Plan #{plan_id} approved → {len(dir_ids)} discovery directive(s) + learning observation recorded"}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="fidelity_401k")
    ap.add_argument("--action", default="liquidate")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
    print(json.dumps(plan({"action": a.action, "account": a.account, "to": "cash", "amount": "all"}), indent=2, default=str))
