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
    try:
        from scripts.lib.ticker_knowledge_graph import build_profile, classify_artifact
    except Exception:
        build_profile = classify_artifact = None
    profile = build_profile(sym) if build_profile else None
    if profile:
        out["ticker_guid"] = profile["ticker_guid"]

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
    ri = _q("""SELECT topic, summary, thesis, confidence_score, quality_score, freshness_date, research_type,
                      source_urls_json, status, created_at
               FROM hermes_research_intelligence WHERE symbol=%s AND status NOT IN ('rejected','superseded')
               AND summary IS NOT NULL ORDER BY COALESCE(quality_score,0) DESC, created_at DESC LIMIT %s""",
            (sym, research_limit))
    research_rows = []
    for x in ri:
        row = dict(x)
        artifact = classify_artifact(sym, {
            "source_id": f"{row.get('research_type')}:{row.get('topic')}",
            "source_type": row.get("research_type"),
            "source_url": (_parse_urls(row.get("source_urls_json")) or [None])[0],
            "title": row.get("topic"), "summary": row.get("summary"),
            "as_of": row.get("freshness_date") or row.get("created_at"),
            "relationship": "LINEAR",
        }, profile=profile) if classify_artifact else {}
        research_rows.append({
        "topic": row.get("topic"), "thesis": (str(row.get("thesis") or "")[:240]),
        "summary": (str(dict(x).get("summary") or "")[:280]),
        "confidence": row.get("confidence_score"), "quality": row.get("quality_score"),
        "as_of": str(row.get("freshness_date") or row.get("created_at") or "")[:19],
        "type": row.get("research_type"), "status": row.get("status"),
        "source_urls": _parse_urls(row.get("source_urls_json")),
        "research_artifact_guid": artifact.get("research_artifact_guid"),
        "relationship_guids": artifact.get("relationship_guids") or [],
        })
    out["research"] = research_rows

    # external-lane opinions (Grok / ChatGPT)
    ex = _q("""SELECT lane, recommendation, confidence, dissent, risk_flags, created_at
               FROM hermes_external_research WHERE symbol=%s AND recommendation IS NOT NULL
               ORDER BY created_at DESC LIMIT %s""", (sym, external_limit))
    out["external_lanes"] = [{
        "lane": dict(x).get("lane"), "recommendation": dict(x).get("recommendation"),
        "confidence": dict(x).get("confidence"), "dissent": dict(x).get("dissent"),
        "risk_flags": dict(x).get("risk_flags"), "as_of": str(dict(x).get("created_at") or "")[:10],
        "research_artifact_guid": (classify_artifact(sym, {
            "source_id": f"external:{dict(x).get('lane')}:{dict(x).get('created_at')}",
            "source_type": f"hermes_external_{dict(x).get('lane') or 'lane'}",
            "summary": dict(x).get("recommendation"), "as_of": dict(x).get("created_at"),
            "relationship": "LATERAL",
        }, profile=profile).get("research_artifact_guid") if classify_artifact else None),
    } for x in ex]
    return out


def _parse_urls(value):
    if isinstance(value, list):
        return [str(x) for x in value if x]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return _parse_urls(parsed)
        except Exception:
            return [value] if value.startswith(("http://", "https://")) else []
    return []


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
