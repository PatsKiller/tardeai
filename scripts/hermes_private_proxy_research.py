#!/usr/bin/env python3
"""hermes_private_proxy_research.py — research PRIVATE companies (not directly buyable) and map them to
PUBLIC-market proxies, then score materiality / catalyst / disclosure quality / confidence.

Operator use case: Anthropic IPO → Zoom (ZM) as public proxy because Zoom Ventures invested in Anthropic.

Answers ten standing research questions per target via the FREE web-grounded OAuth lanes (Grok/ChatGPT),
stores a structured, cited row in private_company_proxies. ADVISORY / RESEARCH ONLY — no trading surface,
no auto-promotion, no live path. Anthropic/Zoom-style proxy theses are event-driven and UNVALIDATED until
paper outcomes exist.

  python3 scripts/hermes_private_proxy_research.py [--target anthropic] [--apply]
  python3 scripts/hermes_private_proxy_research.py --list
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

REGISTRY = PROJECT_ROOT / "config" / "private_company_proxies.yaml"

# The ten standing research questions (operator spec). Kept in code so the prompt + the stored
# research_answers keys stay in lock-step and the card can render them in order.
QUESTIONS = [
    ("ipo_timing", "When is {target} expected to IPO? Give the best-supported window or say unknown."),
    ("confidential_filing", "Has {target} confidentially filed (draft/confidential S-1)? State yes/no/unknown with source."),
    ("latest_valuation", "What is the latest reported {target} valuation (USD) and as-of date?"),
    ("public_investors", "Which PUBLIC companies own or have invested in {target}? List ticker + what is known of the stake."),
    ("most_material_proxy", "Which public company has the most MATERIAL exposure relative to its market cap? Name the ticker and reasoning."),
    ("proxy_discloses", "Does {proxy} disclose its {target} investment value in SEC filings? How, and how current?"),
    ("stake_vs_mktcap", "How large is {proxy}'s {target} stake relative to {proxy}'s market cap (rough %)?"),
    ("rerate_events", "What events could re-rate {proxy} on this thesis (S-1, fair-value mark, IPO pricing, lockup)?"),
    ("equity_strategy", "What regular-stock strategy fits a {proxy} proxy position (starter / staged add / watch-only)?"),
    ("options_strategy", "What options strategy fits (deep ITM/LEAPS, call debit spread, CSP)? Note what to AVOID."),
]

PROMPT = """You are an equity research analyst building a PUBLIC-MARKET PROXY thesis for a PRIVATE company
that cannot be bought directly.

PRIVATE TARGET: {target}
PRIMARY PUBLIC PROXY: {proxy} (proxy_type: {proxy_type})
OPERATOR PRIOR: {why}

Use current web-grounded knowledge (SEC filings, reputable financial press, the company's own
disclosures). Cite sources. Where you are uncertain, say so — do NOT fabricate figures or filing facts.

Answer each question, then score the proxy. Respond with ONLY a JSON object, no prose:
{{
  "answers": {{
{answer_keys}
  }},
  "ipo_status": "private_no_public_s1|confidential_s1_reported|s1_public|priced|ipo_complete",
  "expected_ipo_window": "<e.g. 2026-H2 / 2027 / unknown>",
  "latest_valuation_usd": <number or null>,
  "materiality_score": <0-100 — stake value relative to proxy market cap; higher = more material>,
  "catalyst_score": <0-100 — how discrete/near/impactful the re-rate catalyst is>,
  "valuation_disclosure_quality": <0-100 — how clearly/currently the proxy discloses the stake value>,
  "source_confidence": <0-100 — your confidence in these facts given source quality>,
  "research_notes": "<=400 chars — the honest caveat: what really drives the proxy, and why this is event-driven/unvalidated>",
  "citations": [{{"claim": "...", "source": "publisher/filing", "url": "...", "as_of": "YYYY-MM or null"}}]
}}"""


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


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        # tolerate trailing prose / minor issues by trimming to the last closing brace
        try:
            return json.loads(m.group(0)[: m.group(0).rfind("}") + 1])
        except Exception:
            return None


def _clamp(v, lo=0, hi=100):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except Exception:
        return None


def research_target(tgt, apply=False):
    import llm_lane
    lane = "grok" if llm_lane.available("grok") else ("chatgpt" if llm_lane.available("chatgpt") else None)
    if lane is None:
        return {"ok": False, "error": "no OAuth web lane available (Grok/ChatGPT) — proxy research needs a grounded model"}

    proxies = tgt.get("proxies") or []
    primary = next((p for p in proxies if p.get("primary")), (proxies[0] if proxies else None))
    if not primary:
        return {"ok": False, "error": f"{tgt.get('slug')} has no proxy tickers"}
    proxy = primary["ticker"].upper()
    target = tgt["private_target_name"]

    q_fmt = [(k, q.format(target=target, proxy=proxy)) for k, q in QUESTIONS]
    answer_keys = ",\n".join(f'    "{k}": "<answer to: {q}>"' for k, q in q_fmt)
    prompt = PROMPT.format(target=target, proxy=proxy, proxy_type=primary.get("proxy_type", "?"),
                           why=(primary.get("why") or "").strip(), answer_keys=answer_keys)

    try:
        out = llm_lane.generate(prompt, lane=lane, timeout=180)
    except Exception as e:
        alt = "chatgpt" if lane == "grok" else "grok"
        if llm_lane.available(alt):
            try:
                out = llm_lane.generate(prompt, lane=alt, timeout=180); lane = alt
            except Exception as e2:
                return {"ok": False, "error": f"both lanes failed: {str(e2)[:100]}"}
        else:
            return {"ok": False, "error": f"lane error: {str(e)[:100]}"}

    p = _parse(out)
    if not p:
        return {"ok": False, "error": "unparseable research response", "raw": (out or "")[:200]}

    # merge seed strategy scaffolding (never LLM-authored — operator-defined structures with the
    # speculative / caps_upside safety flags)
    strategy = {"regular": tgt.get("regular_strategy_candidates") or [],
                "options": tgt.get("options_strategy_candidates") or []}
    model = "grok-3-mini" if lane == "grok" else "gpt-5.4"
    row = {
        "slug": tgt["slug"], "private_target_name": target, "proxy_ticker": proxy,
        "primary_proxy": True, "proxy_type": primary.get("proxy_type"),
        "ipo_status": p.get("ipo_status") or tgt.get("ipo_status"),
        "expected_ipo_window": p.get("expected_ipo_window") or tgt.get("expected_ipo_window"),
        "latest_valuation": p.get("latest_valuation_usd"),
        "materiality_score": _clamp(p.get("materiality_score")),
        "catalyst_score": _clamp(p.get("catalyst_score")),
        "valuation_disclosure_quality": _clamp(p.get("valuation_disclosure_quality")),
        "source_confidence": _clamp(p.get("source_confidence")),
        "why": (primary.get("why") or "").strip(),
        "research_notes": (p.get("research_notes") or primary.get("research_notes") or "")[:500],
        "research_answers": p.get("answers") or {},
        "citations": p.get("citations") or [],
        "strategy_candidates": strategy, "model_used": model,
    }

    if not apply:
        return {"ok": True, "dry_run": True, "proxy": proxy, "row": row}

    conn = _conn(); cur = conn.cursor()
    _ensure_table(cur)
    cur.execute("""
        INSERT INTO private_company_proxies
            (slug, private_target_name, proxy_ticker, primary_proxy, proxy_type, ipo_status,
             expected_ipo_window, latest_valuation, materiality_score, catalyst_score,
             valuation_disclosure_quality, source_confidence, why, research_notes,
             research_answers, citations, strategy_candidates, model_used, researched_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), now())
        ON CONFLICT (slug, proxy_ticker) DO UPDATE SET
            primary_proxy=EXCLUDED.primary_proxy, proxy_type=EXCLUDED.proxy_type,
            ipo_status=EXCLUDED.ipo_status, expected_ipo_window=EXCLUDED.expected_ipo_window,
            latest_valuation=EXCLUDED.latest_valuation, materiality_score=EXCLUDED.materiality_score,
            catalyst_score=EXCLUDED.catalyst_score,
            valuation_disclosure_quality=EXCLUDED.valuation_disclosure_quality,
            source_confidence=EXCLUDED.source_confidence, why=EXCLUDED.why,
            research_notes=EXCLUDED.research_notes, research_answers=EXCLUDED.research_answers,
            citations=EXCLUDED.citations, strategy_candidates=EXCLUDED.strategy_candidates,
            model_used=EXCLUDED.model_used, researched_at=now(), updated_at=now()
    """, (row["slug"], row["private_target_name"], row["proxy_ticker"], row["primary_proxy"],
          row["proxy_type"], row["ipo_status"], row["expected_ipo_window"], row["latest_valuation"],
          row["materiality_score"], row["catalyst_score"], row["valuation_disclosure_quality"],
          row["source_confidence"], row["why"], row["research_notes"],
          json.dumps(row["research_answers"]), json.dumps(row["citations"]),
          json.dumps(row["strategy_candidates"]), row["model_used"]))
    conn.commit()
    return {"ok": True, "proxy": proxy, "citations": len(row["citations"]),
            "scores": {k: row[k] for k in ("materiality_score", "catalyst_score",
                                           "valuation_disclosure_quality", "source_confidence")}}


def run(target_slug=None, apply=False):
    reg = _load_registry()
    targets = [t for t in (reg.get("targets") or []) if t.get("enabled", True)]
    if target_slug:
        targets = [t for t in targets if t.get("slug") == target_slug]
        if not targets:
            return {"ok": False, "error": f"no enabled target '{target_slug}'"}
    results = []
    for t in targets:
        r = research_target(t, apply=apply)
        r["target"] = t.get("slug")
        results.append(r)
        print(f"  {t.get('slug')}: {'OK' if r.get('ok') else 'FAIL'} "
              f"{r.get('proxy','')} {r.get('scores') or r.get('error','')}")
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
            px = ", ".join(f"{p['ticker']}{'*' if p.get('primary') else ''}" for p in (t.get("proxies") or []))
            print(f"{t.get('slug'):16} {t.get('private_target_name'):16} → {px}")
        return
    print(json.dumps(run(target_slug=a.target, apply=a.apply), default=str, indent=2))


if __name__ == "__main__":
    main()
