#!/usr/bin/env python3
"""hermes_private_proxy_research.py — discover the FULL public-market PROXY GRAPH for a PRIVATE company
that can't be bought directly, then score + rank every proxy and bucket them into decision cards.

Operator use case: Anthropic IPO. The operator supplied ONE proxy (Zoom / ZM). That is NOT the answer —
Hermes must discover the whole graph: direct/strategic/CVC investors, convertible/preferred holders,
cloud providers, chip suppliers, major customers/partners, public comparables, and thematic ETFs.

Pipeline per target:
  1. target-level research (10 standing questions, IPO status/window/valuation, citations) via the FREE
     web-grounded OAuth lanes (Grok/ChatGPT)
  2. proxy-GRAPH discovery — the lane enumerates every public proxy it can source (seeded with the
     registry's known_proxy_tickers but NOT limited to them), each with proxy_type, evidence_summary,
     estimated stake value (or unknown), catalyst_type, confidence / materiality / dilution / disclosure
     scores, why-not risk, and CITATIONS (required — a proxy with no source is rejected, never fabricated)
  3. live enrichment — market cap (schwab get_fundamentals) + optionability (options_chain feasibility);
     degrades to unknown when the market/broker is closed (refreshed by the next market-hours run)
  4. rank (direct exposure > materiality-vs-market-cap > disclosure > catalyst > liquidity > options >
     dilution risk) and bucket (best direct / best materiality / best options / best lower-risk equity /
     too-diluted-watch / rejected)
  5. persist one row per proxy in private_company_proxies (rows for the slug are replaced each run)

ADVISORY / RESEARCH ONLY — no trading surface, no auto-promotion, no live path. Proxy theses are
event-driven and UNVALIDATED until paper outcomes exist. Options rows are never live-eligible.

  python3 scripts/hermes_private_proxy_research.py [--target anthropic] [--apply] [--list]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

REGISTRY = PROJECT_ROOT / "config" / "private_company_proxies.yaml"

# proxy_type taxonomy (operator spec). DIRECT = confirmed economic exposure to the private target.
DIRECT_TYPES = {"direct_equity_stake", "convertible_note", "preferred_stock", "corporate_venture_investor"}
STRATEGIC_TYPES = {"strategic_partner"}
SUPPLY_TYPES = {"cloud_provider", "chip_supplier", "customer"}
WEAK_TYPES = {"public_comparable", "ETF"}
ALL_TYPES = DIRECT_TYPES | STRATEGIC_TYPES | SUPPLY_TYPES | WEAK_TYPES
CATALYST_TYPES = {"IPO", "S-1 filing", "valuation mark-up", "funding round", "acquisition",
                  "partnership expansion", "earnings disclosure"}

# The ten standing target-level questions (operator spec). Kept in code so the prompt + the stored
# research_answers keys stay in lock-step and the card can render them in order.
QUESTIONS = [
    ("ipo_timing", "When is {target} expected to IPO? Give the best-supported window or say unknown."),
    ("confidential_filing", "Has {target} confidentially filed (draft/confidential S-1)? yes/no/unknown + source."),
    ("latest_valuation", "What is the latest reported {target} valuation (USD) and as-of date?"),
    ("public_investors", "Which PUBLIC companies own or have invested in {target}? List ticker + stake."),
    ("most_material_proxy", "Which public company has the most MATERIAL exposure relative to its market cap?"),
    ("proxy_discloses", "Do those public holders disclose the {target} investment value in SEC filings?"),
    ("stake_vs_mktcap", "For the biggest public holders, how large is the stake vs their market cap (rough %)?"),
    ("rerate_events", "What events could re-rate the proxies (S-1, fair-value mark, IPO pricing, lockup)?"),
    ("equity_strategy", "What regular-stock strategy fits a proxy position (starter / staged add / watch-only)?"),
    ("options_strategy", "What options strategy fits (deep ITM/LEAPS, call debit spread, CSP)? What to AVOID?"),
]

TARGET_PROMPT = """You are an equity research analyst studying a PRIVATE company that cannot be bought directly.

PRIVATE TARGET: {target}
OPERATOR CONTEXT: {context}

Use current web-grounded knowledge (SEC filings, reputable financial press, company disclosures). Cite
sources. Where uncertain, say so — do NOT fabricate figures or filing facts.

Answer each question, then give target-level facts. Respond with ONLY a JSON object, no prose:
{{
  "answers": {{
{answer_keys}
  }},
  "ipo_status": "private_no_public_s1|confidential_s1_reported|s1_public|priced|ipo_complete",
  "expected_ipo_window": "<e.g. 2026-H2 / 2027 / unknown>",
  "latest_valuation_usd": <number or null>,
  "citations": [{{"claim": "...", "source": "publisher/filing", "url": "...", "as_of": "YYYY-MM or null"}}]
}}"""

GRAPH_PROMPT = """You are mapping the FULL public-market PROXY GRAPH for a PRIVATE company that cannot be
bought directly. The operator named some tickers — DO NOT stop there. Enumerate every PUBLIC company
whose value is plausibly tied to {target}, across ALL of these relationship types:
  direct_equity_stake, convertible_note, preferred_stock, corporate_venture_investor, strategic_partner,
  cloud_provider, chip_supplier, customer, public_comparable, ETF

PRIVATE TARGET: {target}
CANDIDATES TO INVESTIGATE (confirm or reject each WITH a citation; also discover others): {seeds}

Rules:
- Every proxy you list MUST have at least one citation to a current, credible source. If you cannot
  source a relationship, either omit it or list it with "confirmed": false and explain in why_not — never
  fabricate a stake, filing, or number.
- If a stake value is unknown, set estimated_stake_value_usd to null and stake_known to false. Do not guess.
- Include the operator's ticker(s) if real, but they are NOT the whole answer.
- Prefer named, confirmable relationships (SEC filings, press) over vague "AI beneficiary" claims; you may
  still include pure thematic/infrastructure beneficiaries as public_comparable, marked as such.

Respond with ONLY a JSON object, no prose:
{{
  "proxies": [
    {{
      "ticker": "AMZN",
      "company": "Amazon.com, Inc.",
      "proxy_type": "<one of the relationship types above>",
      "confirmed": <true|false — is the relationship confirmed by a current source?>,
      "relationship": "<one line>",
      "evidence_summary": "<=300 chars: the confirmed relationship + what's known of the stake>",
      "estimated_stake_value_usd": <number or null>,
      "stake_known": <true|false>,
      "catalyst_type": "IPO|S-1 filing|valuation mark-up|funding round|acquisition|partnership expansion|earnings disclosure",
      "confidence_score": <0-100 — confidence the relationship is real AND current>,
      "materiality_score": <0-100 — how much this stake could move THIS stock (small cap + big stake = high)>,
      "dilution_score": <0-100 — how much the private thesis is drowned out by the proxy's own size/business; mega-cap = high>,
      "disclosure_quality": <0-100 — how clearly/currently the holder discloses the stake value>,
      "why_not": "<=200 chars: the main risk / why this proxy could fail the thesis>",
      "citations": [{{"claim": "...", "source": "publisher/filing", "url": "...", "as_of": "YYYY-MM or null"}}]
    }}
  ]
}}
List as many sourced proxies as you can (aim for 6-12). Rank does not matter — include weak/diluted ones too."""


def _load_registry():
    import yaml
    return yaml.safe_load(REGISTRY.read_text()) or {}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS private_company_proxies (
            id serial PRIMARY KEY,
            slug text NOT NULL,
            private_target_name text,
            proxy_ticker text NOT NULL,
            primary_proxy boolean DEFAULT false,
            proxy_type text,
            ipo_status text,
            expected_ipo_window text,
            latest_valuation numeric,
            materiality_score int,
            catalyst_score int,
            valuation_disclosure_quality int,
            source_confidence int,
            why text,
            research_notes text,
            research_answers jsonb,
            citations jsonb,
            strategy_candidates jsonb,
            model_used text,
            researched_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now(),
            UNIQUE (slug, proxy_ticker)
        )""")
    # graph-discovery columns (added incrementally; safe to re-run)
    for col, typ in [
        ("proxy_company", "text"), ("discovered", "boolean DEFAULT false"),
        ("confirmed", "boolean"), ("dilution_score", "int"), ("market_cap", "numeric"),
        ("estimated_stake_value", "numeric"), ("stake_known", "boolean"),
        ("stake_to_mktcap_pct", "numeric"), ("catalyst_type", "text"),
        ("evidence_summary", "text"), ("optionability", "jsonb"),
        ("has_options", "boolean"), ("option_liquidity_score", "int"),
        ("leaps_available", "boolean"), ("rank_overall", "int"), ("rank_score", "numeric"),
        ("bucket", "text"), ("accepted", "boolean DEFAULT true"), ("rejected_reason", "text"),
        ("ticker_plan", "jsonb"),
    ]:
        cur.execute(f"ALTER TABLE private_company_proxies ADD COLUMN IF NOT EXISTS {col} {typ}")


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0)[: m.group(0).rfind("}") + 1])
        except Exception:
            return None


def _clamp(v, lo=0, hi=100):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except Exception:
        return None


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def _lane_order():
    """Preferred lane order — available() first, but keep both because the free OAuth proxies flap
    (available() can pass while generate() 502s), so we always keep a fallback lane in the list."""
    import llm_lane
    avail = [l for l in ("deepseek-flash", "grok", "chatgpt") if llm_lane.available(l)]
    return avail + [l for l in ("deepseek-flash", "grok", "chatgpt") if l not in avail]


def _llm(prompt, attempts=4, backoff=8):
    """Generate across lanes with per-lane retries — resilient to the free OAuth proxies' transient
    502s (they flap: one call can 502 while the other lane is fine, and both can be down for a minute).
    Interleaves lanes each round and sleeps between rounds to ride out the flap. Returns (text, model,
    lane); raises only if every lane fails every round."""
    import llm_lane, time
    lanes = _lane_order()
    last = None
    for rnd in range(attempts):
        for lane in lanes:
            try:
                out = llm_lane.generate(prompt, lane=lane, timeout=180)
                if out and out.strip():
                    return out, ("grok-3-mini" if lane == "grok" else "gpt-5.4"), lane
            except Exception as e:
                last = e
        if rnd < attempts - 1:
            time.sleep(backoff)
    raise RuntimeError(f"all LLM lanes failed after {attempts} rounds: {str(last)[:140]}")


# ── live enrichment (read-only; degrades to unknown when market/broker closed) ──────────────────────

def _market_caps(tickers):
    """{ticker: market_cap or None} via schwab get_fundamentals (one batched read). Never raises."""
    out = {t: None for t in tickers}
    try:
        import schwab_transport as st
        f = st.get_fundamentals(list(tickers)) or {}
        for t in tickers:
            row = f.get(t) or f.get(t.upper()) or {}
            out[t] = _num(row.get("market_cap"))
    except Exception:
        pass
    return out


def _optionability(ticker):
    """has_options / liquidity / LEAPS / spread / CSP from a read-only chain snapshot.
    Unknown (all None) when the chain is unavailable — never fabricates."""
    unknown = {"has_options": None, "option_liquidity_score": None, "leaps_available": None,
               "spread_candidate": None, "csp_candidate": None, "source": "chain_unavailable"}
    try:
        from strategy_research import options_chain as oc
        snap = oc.fetch_chain_snapshot(ticker, strike_count=20)
        if not snap.get("available"):
            return {**unknown, "source": snap.get("reason") or "chain_unavailable"}
        feas = oc.strategy_feasibility(snap) or {}
        if not feas:
            return {**unknown, "source": "no_feasibility"}
        scores = [v.get("score", 0) for v in feas.values() if isinstance(v, dict)]
        liq = int(round(sum(scores) / len(scores))) if scores else 0
        return {
            "has_options": True, "option_liquidity_score": liq,
            "leaps_available": bool(feas.get("leaps_long_call", {}).get("feasible")),
            "spread_candidate": bool(feas.get("call_spread", {}).get("feasible")),
            "csp_candidate": bool(feas.get("cash_secured_put", {}).get("feasible")),
            "source": "schwab_chain",
        }
    except Exception:
        return unknown


# ── scoring / ranking / bucketing ───────────────────────────────────────────────────────────────────

def _direct_points(ptype):
    if ptype in DIRECT_TYPES:
        return 30.0
    if ptype in STRATEGIC_TYPES:
        return 14.0
    if ptype in SUPPLY_TYPES:
        return 7.0
    return 0.0


def _catalyst_proximity(ipo_status):
    return {"s1_public": 90, "priced": 95, "confidential_s1_reported": 70,
            "private_no_public_s1": 40, "ipo_complete": 30}.get(ipo_status, 40)


def _liquidity_from_mktcap(mc):
    if mc is None:
        return 50  # neutral when unknown
    for thresh, score in [(5e11, 100), (1e11, 85), (2e10, 70), (5e9, 55), (1e9, 40)]:
        if mc >= thresh:
            return score
    return 25


def _rank_score(p, catalyst_prox):
    conf = (p.get("source_confidence") or 0) / 100.0
    opt_liq = p.get("option_liquidity_score")
    opt_term = (opt_liq if opt_liq is not None else 50) * 0.08
    return round(
        _direct_points(p.get("proxy_type")) * conf                       # confirmed direct exposure
        + (p.get("materiality_score") or 0) * 0.30                       # materiality vs market cap
        + (p.get("valuation_disclosure_quality") or 0) * 0.10           # disclosure quality
        + catalyst_prox * 0.08                                          # catalyst proximity
        + _liquidity_from_mktcap(p.get("market_cap")) * 0.06            # stock liquidity
        + opt_term                                                      # options liquidity
        - (p.get("dilution_score") or 0) * 0.15,                        # dilution-risk penalty
        2)


def _ticker_plan(p):
    """Deterministic per-ticker plan templated from proxy_type + optionability + scores. These are
    generic strategy templates, NOT sourced claims — the sourced claim is evidence_summary/citations."""
    ptype = p.get("proxy_type")
    direct = ptype in DIRECT_TYPES
    strategic = ptype in STRATEGIC_TYPES
    diluted = (p.get("dilution_score") or 0) >= 70
    has_opt = p.get("has_options")
    leaps = p.get("leaps_available")
    tkr = p["proxy_ticker"]

    if direct and not diluted:
        regular = f"Starter equity in {tkr}; stage adds on a confirmed stake mark / S-1 disclosure."
    elif direct and diluted:
        regular = f"{tkr} is a diluted direct holder — small satellite position or watch; the stake won't dominate the tape."
    elif strategic:
        regular = f"{tkr} strategic exposure — position on its own fundamentals; treat the private thesis as a kicker."
    else:
        regular = f"{tkr} is a comparable/thematic proxy — watchlist-only unless its own setup is compelling."

    if has_opt is False:
        options = "No listed options — equity only."
    elif has_opt is None:
        options = "Optionability unknown (chain closed at scan) — refreshes on the next market-hours run."
    elif leaps:
        options = f"Deep-ITM LEAPS as a stock replacement; call debit spread around the catalyst window; CSP if willing to own {tkr} lower. Avoid short-dated OTM calls."
    else:
        options = f"Options present but no long-dated LEAPS — defined-risk call debit spread around the catalyst; CSP if willing to own {tkr}. Avoid short-dated OTM calls."

    watch = ["Anthropic / target S-1 + IPO timeline", "target valuation mark-ups / new funding rounds",
             f"{tkr} SEC disclosures on the strategic investment", f"{tkr} earnings + core-business AI revenue"]
    invalidation = [f"{tkr}'s relationship to the target is unconfirmed or denied by current sources",
                    f"{tkr} core-business deterioration swamps the proxy thesis", "IPO slips materially or prices below expectations"]
    why_not = (p.get("_why_not") or "").strip() or (
        "Diluted by the proxy's own market cap — the stake may be immaterial to the tape." if diluted
        else "Proxy trades mostly on its own business; the private-company link is real but loose.")
    return {"regular_plan": regular, "options_plan": options, "watch_triggers": watch,
            "invalidation_triggers": invalidation, "why_not": why_not}


def _rank_and_bucket(proxies, ipo_status):
    """Rank accepted proxies and tag a primary bucket. Rejected proxies keep their reason.
    Returns the full list (accepted + rejected), each with rank_score/rank_overall/bucket/ticker_plan."""
    catalyst_prox = _catalyst_proximity(ipo_status)
    for p in proxies:
        # stake materiality refinement when both stake value and market cap are known
        sv, mc = p.get("estimated_stake_value"), p.get("market_cap")
        if sv and mc:
            pct = round(sv / mc * 100, 3)
            p["stake_to_mktcap_pct"] = pct
            # blend the LLM materiality prior with the computed stake/market-cap signal
            computed = _clamp(min(100, pct * 12))  # ~8%+ of market cap → maxed materiality
            base = p.get("materiality_score") or 0
            p["materiality_score"] = _clamp(round(0.5 * base + 0.5 * computed))
        p["rank_score"] = _rank_score(p, catalyst_prox)
        p["ticker_plan"] = _ticker_plan(p)

    accepted = [p for p in proxies if p.get("accepted")]
    accepted.sort(key=lambda x: -(x.get("rank_score") or 0))
    for i, p in enumerate(accepted, 1):
        p["rank_overall"] = i

    # primary bucket per accepted row (a proxy may qualify for several; store the most decision-useful)
    for p in accepted:
        ptype = p.get("proxy_type")
        diluted = (p.get("dilution_score") or 0) >= 70 or (
            p.get("stake_to_mktcap_pct") is not None and p["stake_to_mktcap_pct"] < 0.5)
        if ptype in DIRECT_TYPES and diluted:
            p["bucket"] = "too_diluted_watch"
        elif ptype in DIRECT_TYPES:
            p["bucket"] = "direct"
        elif ptype in STRATEGIC_TYPES:
            p["bucket"] = "strategic"
        elif ptype in SUPPLY_TYPES:
            p["bucket"] = "infrastructure"
        else:
            p["bucket"] = "comparable"
    for p in proxies:
        if not p.get("accepted"):
            p["bucket"] = "rejected"
            p["rank_overall"] = None
    return proxies


def _normalize_proxy(raw, target_name):
    """Validate one LLM proxy dict → a storable row, or (None, reason) if it must be rejected."""
    tkr = str(raw.get("ticker") or "").strip().upper()
    if not tkr or not re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", tkr):
        return None
    ptype = str(raw.get("proxy_type") or "").strip()
    if ptype not in ALL_TYPES:
        ptype = "public_comparable"  # unknown/garbled type → weakest bucket, never dropped silently
    cites = [c for c in (raw.get("citations") or []) if isinstance(c, dict) and (c.get("url") or c.get("source"))]
    ctype = raw.get("catalyst_type") if raw.get("catalyst_type") in CATALYST_TYPES else None
    p = {
        "proxy_ticker": tkr, "proxy_company": (raw.get("company") or "").strip() or None,
        "proxy_type": ptype, "discovered": True, "confirmed": bool(raw.get("confirmed")),
        "why": (raw.get("relationship") or "").strip()[:400] or None,
        "evidence_summary": (raw.get("evidence_summary") or "").strip()[:600] or None,
        "estimated_stake_value": _num(raw.get("estimated_stake_value_usd")),
        "stake_known": bool(raw.get("stake_known")),
        "catalyst_type": ctype,
        "source_confidence": _clamp(raw.get("confidence_score")),
        "materiality_score": _clamp(raw.get("materiality_score")),
        "dilution_score": _clamp(raw.get("dilution_score")),
        "valuation_disclosure_quality": _clamp(raw.get("disclosure_quality")),
        "catalyst_score": None,  # set to target catalyst proximity below
        "citations": cites, "_why_not": (raw.get("why_not") or "").strip()[:300],
        "accepted": True, "rejected_reason": None,
    }
    # rejection gates — require source evidence; drop rumor-only unconfirmed direct claims
    if not cites:
        p["accepted"] = False
        p["rejected_reason"] = "no source evidence for the claimed relationship"
    elif (p["source_confidence"] or 0) < 25 and not p["confirmed"]:
        p["accepted"] = False
        p["rejected_reason"] = "relationship unconfirmed / rumor-only in current sources"
    return p


def discover_graph(tgt, apply=False, option_probe=8):
    slug, target = tgt["slug"], tgt["private_target_name"]

    # 1) target-level research (10 answers, ipo status/window/valuation, citations)
    q_fmt = [(k, q.format(target=target)) for k, q in QUESTIONS]
    answer_keys = ",\n".join(f'    "{k}": "<answer to: {q}>"' for k, q in q_fmt)
    context = "; ".join(filter(None, [tgt.get("sector"), f"seed proxies: {tgt.get('known_proxy_tickers')}"]))
    tprompt = TARGET_PROMPT.format(target=target, context=context, answer_keys=answer_keys)
    try:
        _out, model, lane = _llm(tprompt)
        tj = _parse(_out) or {}
    except Exception as e:
        return {"ok": False, "error": f"target research failed: {str(e)[:120]}"}
    ipo_status = tj.get("ipo_status") or tgt.get("ipo_status")
    ipo_window = tj.get("expected_ipo_window") or tgt.get("expected_ipo_window")
    latest_val = _num(tj.get("latest_valuation_usd"))
    target_answers = tj.get("answers") or {}
    target_cites = [c for c in (tj.get("citations") or []) if isinstance(c, dict)]

    # 2) proxy-graph discovery
    seeds = ", ".join(tgt.get("known_proxy_tickers") or []) or "(none supplied)"
    gprompt = GRAPH_PROMPT.format(target=target, seeds=seeds)
    try:
        _gout, _gmodel, _glane = _llm(gprompt)
        gj = _parse(_gout) or {}
    except Exception as e:
        return {"ok": False, "error": f"graph discovery failed: {str(e)[:120]}"}
    raw_proxies = gj.get("proxies") or []

    proxies, seen = [], set()
    for raw in raw_proxies:
        p = _normalize_proxy(raw, target)
        if p and p["proxy_ticker"] not in seen:
            seen.add(p["proxy_ticker"])
            proxies.append(p)
    if not proxies:
        return {"ok": False, "error": "discovery returned no usable proxies", "raw": json.dumps(gj)[:200]}

    # 3) live enrichment — market cap (batched) + optionability (top candidates by prelim confidence)
    caps = _market_caps([p["proxy_ticker"] for p in proxies])
    for p in proxies:
        p["market_cap"] = caps.get(p["proxy_ticker"])
        p["catalyst_score"] = _catalyst_proximity(ipo_status)
    probe = sorted([p for p in proxies if p["accepted"]],
                   key=lambda x: -((x.get("source_confidence") or 0) + (x.get("materiality_score") or 0)))[:option_probe]
    for p in probe:
        opt = _optionability(p["proxy_ticker"])
        p["optionability"] = opt
        p["has_options"] = opt.get("has_options")
        p["option_liquidity_score"] = opt.get("option_liquidity_score")
        p["leaps_available"] = opt.get("leaps_available")

    # 4) rank + bucket
    proxies = _rank_and_bucket(proxies, ipo_status)

    # attach registry strategy scaffolding + operator prior (why) to any seeded ticker
    reg_options = tgt.get("options_strategy_candidates") or []
    reg_regular = tgt.get("regular_strategy_candidates") or []
    seed_priors = {(pr.get("ticker") or "").upper(): pr for pr in (tgt.get("proxies") or [])}
    for p in proxies:
        pr = seed_priors.get(p["proxy_ticker"])
        if pr:
            p["discovered"] = False  # operator-seeded (also confirmed by discovery)
            if pr.get("why") and not p.get("why"):
                p["why"] = pr["why"]

    summary = {"ok": True, "slug": slug, "target": target, "model": model, "lane": lane,
               "ipo_status": ipo_status, "expected_ipo_window": ipo_window, "latest_valuation": latest_val,
               "accepted": sum(1 for p in proxies if p["accepted"]), "rejected": sum(1 for p in proxies if not p["accepted"]),
               "ranked": [{"rank": p.get("rank_overall"), "ticker": p["proxy_ticker"], "type": p["proxy_type"],
                           "bucket": p.get("bucket"), "score": p.get("rank_score"),
                           "materiality": p.get("materiality_score"), "market_cap": p.get("market_cap"),
                           "cites": len(p.get("citations") or [])}
                          for p in sorted(proxies, key=lambda x: (x.get("rank_overall") or 999))],
               "citations_total": sum(len(p.get("citations") or []) for p in proxies)}

    if not apply:
        summary["dry_run"] = True
        return summary

    # 5) persist — replace all rows for this slug, then insert every proxy (accepted + rejected)
    conn = _conn(); cur = conn.cursor()
    _ensure_table(cur)
    cur.execute("DELETE FROM private_company_proxies WHERE slug=%s", (slug,))
    best_direct = next((p["proxy_ticker"] for p in sorted(proxies, key=lambda x: (x.get("rank_overall") or 999))
                        if p["accepted"] and p["proxy_type"] in DIRECT_TYPES), None)
    for p in proxies:
        strat = {"regular": reg_regular, "options": reg_options} if seed_priors.get(p["proxy_ticker"]) else {}
        cur.execute("""
            INSERT INTO private_company_proxies
              (slug, private_target_name, proxy_ticker, primary_proxy, proxy_type, ipo_status,
               expected_ipo_window, latest_valuation, materiality_score, catalyst_score,
               valuation_disclosure_quality, source_confidence, why, research_notes, research_answers,
               citations, strategy_candidates, model_used, proxy_company, discovered, confirmed,
               dilution_score, market_cap, estimated_stake_value, stake_known, stake_to_mktcap_pct,
               catalyst_type, evidence_summary, optionability, has_options, option_liquidity_score,
               leaps_available, rank_overall, rank_score, bucket, accepted, rejected_reason, ticker_plan,
               researched_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), now())
        """, (
            slug, target, p["proxy_ticker"], p["proxy_ticker"] == best_direct, p["proxy_type"], ipo_status,
            ipo_window, latest_val, p.get("materiality_score"), p.get("catalyst_score"),
            p.get("valuation_disclosure_quality"), p.get("source_confidence"), p.get("why"),
            (p.get("_why_not") or None), json.dumps(target_answers), json.dumps(p.get("citations") or []),
            json.dumps(strat), model, p.get("proxy_company"), p.get("discovered"), p.get("confirmed"),
            p.get("dilution_score"), p.get("market_cap"), p.get("estimated_stake_value"), p.get("stake_known"),
            p.get("stake_to_mktcap_pct"), p.get("catalyst_type"), p.get("evidence_summary"),
            json.dumps(p.get("optionability") or {}), p.get("has_options"), p.get("option_liquidity_score"),
            p.get("leaps_available"), p.get("rank_overall"), p.get("rank_score"), p.get("bucket"),
            p.get("accepted"), p.get("rejected_reason"), json.dumps(p.get("ticker_plan") or {})))
    # stash the target-level citations on the top row's research bundle is not needed; target cites live
    # per-proxy already. Commit.
    conn.commit()
    summary["target_citations"] = len(target_cites)
    return summary


def run(target_slug=None, apply=False):
    reg = _load_registry()
    targets = [t for t in (reg.get("targets") or []) if t.get("enabled", True)]
    if target_slug:
        targets = [t for t in targets if t.get("slug") == target_slug]
        if not targets:
            return {"ok": False, "error": f"no enabled target '{target_slug}'"}
    results = []
    for t in targets:
        r = discover_graph(t, apply=apply)
        r["target"] = t.get("slug")
        results.append(r)
        if r.get("ok"):
            print(f"  {t.get('slug')}: OK — {r.get('accepted')} accepted / {r.get('rejected')} rejected, "
                  f"{r.get('citations_total')} citations; top: "
                  + ", ".join(f"{x['ticker']}({x['score']})" for x in r.get("ranked", [])[:5] if x.get("rank")))
        else:
            print(f"  {t.get('slug')}: FAIL {r.get('error')}")
    return {"ok": True, "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None, help="slug (default: all enabled)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        reg = _load_registry()
        for t in (reg.get("targets") or []):
            seeds = ", ".join(t.get("known_proxy_tickers") or [])
            print(f"{t.get('slug'):16} {t.get('private_target_name'):16} seeds: {seeds}")
        return
    print(json.dumps(run(target_slug=a.target, apply=a.apply), default=str, indent=2))


if __name__ == "__main__":
    main()
