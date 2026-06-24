#!/usr/bin/env python3
"""hermes_data_access.py — the ONE canonical way every consumer reads Hermes intelligence.

All agents (Maria/Steph/Risk/Aegis/Alex/watchlist agents), the local LLMs (gemma), and the OAuth
lanes (Grok/ChatGPT) read Hermes data through here — so "what does Hermes know about SYM" has a single,
consistent answer everywhere instead of each surface re-querying ad hoc.

  get_hermes_context(symbol) -> structured dict (score/rank, research notes, external-lane opinions)
  hermes_prompt_block(symbol) -> compact markdown to inject into any LLM prompt

Read-only / advisory. Safe to import anywhere (degrades to empty on any DB error).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _q(sql: str, params=()):
    try:
        from db_adapter import _execute
        return _execute(sql, params, fetch="all") or []
    except Exception:
        return []


def get_hermes_context(symbol: str, *, research_limit: int = 3, external_limit: int = 3) -> dict:
    """Everything Hermes knows about one symbol: composite score+rank, graded research, external lanes."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return {}
    out: dict = {"symbol": sym}

    # composite score + rank (latest)
    sc = _q("""SELECT composite_score, rank, components, scored_at FROM hermes_score_history
               WHERE symbol=%s ORDER BY scored_at DESC LIMIT 1""", (sym,))
    if sc:
        r = dict(sc[0])
        comp = r.get("components")
        if isinstance(comp, str):
            try:
                comp = json.loads(comp)
            except Exception:
                comp = None
        out["score"] = {"composite": r.get("composite_score"), "rank": r.get("rank"),
                        "components": comp, "as_of": str(r.get("scored_at") or "")[:19]}

    # graded research intelligence (web-grounded)
    ri = _q("""SELECT topic, summary, thesis, confidence_score, quality_score, freshness_date, research_type
               FROM hermes_research_intelligence WHERE symbol=%s AND status NOT IN ('rejected','superseded')
               AND summary IS NOT NULL ORDER BY COALESCE(quality_score,0) DESC, created_at DESC LIMIT %s""",
            (sym, research_limit))
    out["research"] = [{
        "topic": dict(x).get("topic"), "thesis": (str(dict(x).get("thesis") or "")[:240]),
        "summary": (str(dict(x).get("summary") or "")[:280]),
        "confidence": dict(x).get("confidence_score"), "quality": dict(x).get("quality_score"),
        "as_of": str(dict(x).get("freshness_date") or "")[:10], "type": dict(x).get("research_type"),
    } for x in ri]

    # external-lane opinions (Grok / ChatGPT)
    ex = _q("""SELECT lane, recommendation, confidence, dissent, risk_flags, created_at
               FROM hermes_external_research WHERE symbol=%s AND recommendation IS NOT NULL
               ORDER BY created_at DESC LIMIT %s""", (sym, external_limit))
    out["external_lanes"] = [{
        "lane": dict(x).get("lane"), "recommendation": dict(x).get("recommendation"),
        "confidence": dict(x).get("confidence"), "dissent": dict(x).get("dissent"),
        "risk_flags": dict(x).get("risk_flags"), "as_of": str(dict(x).get("created_at") or "")[:10],
    } for x in ex]
    return out


def hermes_prompt_block(symbol: str) -> str:
    """Compact markdown block for injecting Hermes intelligence into ANY LLM/agent prompt."""
    c = get_hermes_context(symbol)
    if not c or (not c.get("score") and not c.get("research") and not c.get("external_lanes")):
        return ""
    lines = [f"HERMES INTELLIGENCE — {c['symbol']} (advisory research; verify before acting):"]
    s = c.get("score") or {}
    if s.get("composite") is not None:
        lines.append(f"- Composite score {s['composite']} · rank #{s.get('rank')} (as of {s.get('as_of')})")
    for r in (c.get("research") or [])[:3]:
        lines.append(f"- Research [{r.get('as_of') or '—'}] {r.get('topic') or r.get('type') or ''}: "
                     f"{r.get('thesis') or r.get('summary') or ''} (conf {r.get('confidence')})")
    for e in (c.get("external_lanes") or [])[:3]:
        d = f" — dissent: {e['dissent']}" if e.get("dissent") else ""
        lines.append(f"- {str(e.get('lane') or '').title()} lane: {e.get('recommendation')} "
                     f"(conf {e.get('confidence')}){d}")
    return "\n".join(lines)


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "V"
    print(json.dumps(get_hermes_context(sym), indent=2, default=str))
    print("\n--- prompt block ---\n" + hermes_prompt_block(sym))
