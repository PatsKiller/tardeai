"""memory_influence.py — the influence ladder per surface (Wave 3 O-W3-4; 08 §2–§4).

SHADOW → ADVISORY → WEIGHTED → ENFORCED, per surface, from ``config/memory_influence_policy.json`` →
``influence.surfaces``. Until this module nothing read that section and the code knew only SHADOW/ENFORCED.

* ``mode_for(surface)`` — the surface's mode; ``TRADEAI_INTELLIGENCE_MODE=SHADOW`` is the global kill switch.
* ``advisory_block(ctx)`` — the text a model SEES under ADVISORY (08 §2): a named "MEMORY SAYS" section with
  lineage, and the flags RECONSIDER / CONTESTED / STALE. It may not change the primary stance or ranking;
  it is appended to the prompt, never merged into the evidence.
* ``influence_for(ctx, surface, rendered)`` — the ``influence`` dict the façade writes on commit:
  {consulted, changed_decision, mode, surface, memory_content_present}. MIR (08 §4) = consulted AND mode ≥
  ADVISORY AND memory content present.

Under SHADOW ``advisory_block`` still returns the text (so a receipt can carry ``would_render``) but callers
must not inject it; ``render(surface, ctx)`` returns "" unless the surface mode ≥ ADVISORY. Authority
READ_ONLY_ADVISORY; MBI_BEHAVIOR = 0 — nothing here reaches sizing, orders, stops or weights.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

LADDER = ("SHADOW", "ADVISORY", "WEIGHTED", "ENFORCED")
SURFACES = ("research", "cio_decisions", "watchlists", "holdings_reviews", "options_advisory", "allocation_advice", "risk_advice")
FLAGS = ("RECONSIDER", "CONTESTED", "STALE")
MAX_FACTS = 6
MAX_CHARS = 1800


def _proj_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _policy(env: dict) -> dict:
    p = Path(env.get("TRADEAI_MEMORY_INFLUENCE_POLICY") or _proj_root() / "config" / "memory_influence_policy.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def mode_for(surface: str, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    if str(env.get("TRADEAI_INTELLIGENCE_MODE", "")).upper() == "SHADOW":
        return "SHADOW"
    forced = str(env.get("TRADEAI_MEMORY_INFLUENCE_MODE", "")).upper()
    if forced in LADDER:
        return forced
    inf = (_policy(env).get("influence") or {})
    m = str((inf.get("surfaces") or {}).get(surface) or inf.get("default") or "SHADOW").upper()
    return m if m in LADDER else "SHADOW"


def rank(mode: str) -> int:
    return LADDER.index(mode) if mode in LADDER else 0


def at_least(surface: str, floor: str, env: dict | None = None) -> bool:
    return rank(mode_for(surface, env)) >= rank(floor)


def flags_for(ctx: dict) -> list[str]:
    """RECONSIDER when a belief is refuted or a KEPT option is contradicted; CONTESTED when open contradictions
    exist; STALE when the thesis or facts are past their freshness."""
    out: list[str] = []
    if (ctx.get("open_contradictions_count") or 0) > 0 or ctx.get("contradiction_state") == "OPEN":
        out.append("CONTESTED")
    th = ctx.get("thesis") or {}
    fresh = str(th.get("freshness_state") or th.get("freshness") or "").upper()
    if fresh in ("STALE", "EXPIRED") or any("STALE" in str(r) for r in ctx.get("degraded_reasons") or []) \
            or any(str(f.get("freshness_state") or "").upper() in ("STALE", "EXPIRED") for f in ctx.get("facts") or [] if isinstance(f, dict)):
        out.append("STALE")
    if any(str(b.get("state") or b.get("status") or "").upper() in ("REFUTED", "FALSIFIED") for b in ctx.get("beliefs") or []):
        out.append("RECONSIDER")
    return out


def advisory_block(ctx: dict) -> str:
    """The named memory section (08 §2). Empty string when the context carries nothing worth saying."""
    facts = [f for f in (ctx.get("facts") or []) if isinstance(f, dict)][:MAX_FACTS]
    th = ctx.get("thesis") or {}
    beliefs = [b for b in (ctx.get("beliefs") or []) if isinstance(b, dict)][:4]
    lessons = [l for l in (ctx.get("lessons") or []) if isinstance(l, dict)][:4]
    contras = ctx.get("open_contradictions_count") or 0
    if not (facts or th or beliefs or lessons or contras):
        return ""
    lines = ["=== MEMORY SAYS (advisory; lineage below; may not change the primary stance or ranking) ==="]
    subj = ", ".join(str(s.get("symbol") or s.get("key") or "") for s in (ctx.get("subjects") or []) if isinstance(s, dict))
    if subj:
        lines.append(f"subjects: {subj} · context {ctx.get('context_id')} · as_of {ctx.get('as_of')}")
    fl = flags_for(ctx)
    if fl:
        lines.append("flags: " + ", ".join(fl))
    if th:
        stance = th.get("stance") or th.get("status") or ""
        fresh = th.get("freshness_state") or ""
        lines.append(f"thesis v{th.get('version')} ({stance} · {fresh} · {round(float(th.get('age_hours') or 0))}h old): "
                     f"{str(th.get('summary') or th.get('thesis') or '')[:280]} [cio_theses {th.get('thesis_id')} pin {th.get('pin') or ''}]")
        cats = th.get("catalysts") or []
        if cats:
            lines.append("  catalysts: " + "; ".join(str(c.get('text') if isinstance(c, dict) else c)[:80] for c in cats[:3]))
        inv = th.get("invalidation_conditions") or th.get("what_changes_my_mind") or []
        if inv:
            lines.append("  what changes the thesis: " + "; ".join(str(c.get('text') if isinstance(c, dict) else c)[:80] for c in inv[:2]))
    for f in facts:
        text = f.get("claim") or f.get("text") or f.get("statement")
        if text:
            lines.append(f"- fact: {str(text)[:200]} [{f.get('source') or f.get('store') or 'facts'} {f.get('fact_id') or f.get('id') or ''} {str(f.get('as_of') or '')[:10]}]")
        else:  # memory reference rows (agent_durable_memory): type / class / freshness / confidence / lineage, no prose
            syms = ",".join(str(s) for s in (f.get("symbols") or [])[:3])
            lines.append(f"- memory {str(f.get('memory_type') or 'FACT').lower()} on {syms or 'subject'}: {f.get('freshness_state') or ''}, "
                         f"confidence {f.get('confidence')}, {round(float(f.get('age_hours') or 0))}h old, contradiction {f.get('contradiction_state') or 'NONE'} "
                         f"[{f.get('fact_id') or ''} ← {f.get('lineage_ref') or ''}]")
    for b in beliefs:
        text = b.get("claim") or b.get("belief") or b.get("statement")
        if text:
            lines.append(f"- belief: {str(text)[:160]} ({b.get('state') or b.get('status') or 'held'}) [instrument_record {b.get('belief_key') or ''}]")
        else:  # calibrated belief rows: key + recommendation + track record
            lines.append(f"- belief {b.get('belief_key') or ''}: {b.get('recommendation') or ''} over {b.get('horizon') or ''} — "
                         f"{b.get('successful')}/{b.get('sample_size')} successful (rate {b.get('success_rate')}, rev {b.get('revision')}) "
                         f"[instrument_record {str(b.get('as_of') or '')[:10]}]")
    for l in lessons:
        lines.append(f"- lesson ({l.get('kind') or 'LESSON'}): {str(l.get('statement') or '')[:200]} [promoted {str(l.get('promoted_at') or '')[:10]} by {l.get('decided_by') or ''}]")
    if contras:
        lines.append(f"- {contras} open contradiction(s) on record [research_contradiction_candidates]")
    lines.append("=== END MEMORY ===")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 20] + "\n=== END MEMORY ==="


WEIGHTED_NOTE = ("=== MEMORY WEIGHT (weighted mode) === Rank and word your ADVICE with the memory above as a weighted input: a "
                 "refuted belief or an open contradiction lowers the weight of any option that relies on it; a promoted lesson "
                 "that applies raises the weight of options consistent with it. This never sets sizing, orders, stops or weights "
                 "of positions (MBI_BEHAVIOR = 0). State which memory items changed your ranking. === END MEMORY WEIGHT ===")


def render(surface: str, ctx: dict | None, env: dict | None = None) -> str:
    """The block to inject for this surface, or "" when the surface is SHADOW / the context is empty.
    ADVISORY: the block. WEIGHTED / ENFORCED: the block plus the weighting instruction (08 §3)."""
    if not ctx or not at_least(surface, "ADVISORY", env):
        return ""
    block = advisory_block(ctx)
    if block and at_least(surface, "WEIGHTED", env):
        return block + "\n" + WEIGHTED_NOTE
    return block


def influence_for(ctx: dict, surface: str, *, rendered: bool, env: dict | None = None, changed_decision: bool = False) -> dict:
    mode = mode_for(surface, env)
    consulted = bool(ctx.get("facts") or ctx.get("beliefs") or ctx.get("thesis") or ctx.get("lessons"))
    return {"consulted": consulted, "changed_decision": bool(changed_decision), "mode": mode, "surface": surface,
            "memory_content_present": bool(rendered), "mir": bool(consulted and rendered and rank(mode) >= 1),
            "flags": flags_for(ctx), "would_render": bool(advisory_block(ctx)) if not rendered else True}
