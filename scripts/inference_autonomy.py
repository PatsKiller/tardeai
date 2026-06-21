#!/usr/bin/env python3
"""Inference Layers — autonomous gap-detection → prioritize → act pass.

The generalized "mind of its own" step. After the prior layers have produced their
inferences, this runs ONE structured LLM call to surface gaps / opportunities the
pipeline did *not* already cover — across regional, journal, valuation, modeling,
research and risk dimensions — then acts on the highest-priority items, within the
per-cycle proactive budget shared with the regional layer.

Wired to the REAL repo APIs (no placeholders):
  * inference_hermes_query.proactive_query  → Hermes/LLM follow-up (RAG-grounded)
  * inference_financial_modeling.nav_premium_discount → valuation actions
  * topic_curator / topic_monitor           → research-topic suggestions (advisory)

Every action becomes an auditable Inference (persisted by the engine) and, for
Hermes queries, a row in inference_proactive_queries. Advisory only — research-topic
suggestions are recorded, never auto-injected into the live ingestion pipeline.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from inference_layer_engine import Inference, remember
import inference_hermes_query as hq

log = logging.getLogger("inference_autonomy")

# gap type → the inference_type we file the resulting action under
_TYPE_MAP = {
    "regional": "regional_impact",
    "journal": "journal_pattern",
    "valuation": "nav_signal",
    "modeling": "opportunity",
    "research": "research_gap",
    "risk": "risk",
}


def _proactive_remaining(ctx) -> int:
    budget = int((ctx.cfg.get("proactive", {}) or {}).get("max_queries_per_run", 3))
    return max(0, budget - int(ctx.scratch.get("proactive_used", 0)))


def _state_summary(ctx, res) -> dict:
    """Compact snapshot of what the pipeline already knows, for gap detection."""
    ing = ctx.get("ingestion")
    feat = ctx.get("features")
    reg = ctx.store.get("regional")
    covered = []
    for store in ctx.store.values():
        covered += [i.title for i in store.inferences]
    covered += [i.title for i in res.inferences]
    positions = ing.get("positions", [])
    return {
        "regime": ctx.regime,
        "sentiment": feat.get("sentiment"),
        "top_bucket": f"{feat.get('top_bucket')} {feat.get('top_bucket_pct')}%",
        "held_symbols": [p.get("symbol") for p in positions if p.get("symbol")][:30],
        "open_proposals": [{"symbol": p.get("symbol"), "strategy": p.get("strategy_id")}
                           for p in ing.get("proposals", [])[:10]],
        "active_topics": [t.get("display_name") for t in ing.get("topics", [])[:15]],
        "regional_signals": [{"region": i.payload.get("region"), "dir": i.payload.get("direction")}
                             for i in (reg.inferences if reg else []) if i.inference_type == "regional_impact"],
        "journal_edge": ctx.scratch.get("journal_edge", {}),
        "already_covered": covered[:40],
    }


def detect_gaps(ctx, res) -> list:
    """One structured LLM call → a prioritized list of gap/opportunity items."""
    state = _state_summary(ctx, res)
    prompt = (
        "You are the autonomous inference layer for a US retirement trading system. "
        "Given the CURRENT STATE below (regime, holdings, open proposals, active research "
        "topics, regional signals, journal edge, and what has ALREADY been inferred this "
        "cycle), identify the highest-value GAPS and OPPORTUNITIES the pipeline has NOT yet "
        "covered. Prioritize: Asia→US/ETF/CEF transmission (e.g. PTY), journal patterns by "
        "setup/emotion, NAV premium/discount opportunities, retirement-income fit, and any "
        "research the system should run next. Do NOT repeat anything in already_covered.\n\n"
        f"CURRENT STATE:\n{json.dumps(state, default=str)[:6000]}"
    )
    default_priority = float((ctx.cfg.get("autonomy", {}) or {}).get("min_priority", 6))
    # Small local models (gemma3:4b) intermittently return an empty/unparseable object
    # for this prompt; a single cheap retry reliably recovers the run (observed
    # 0 then 7 items from the identical prompt). Detection calls don't count against
    # the proactive budget.
    # Gap detection can run on a dedicated lane (e.g. grok) so it doesn't compete
    # with the local model — keeps the autonomy pass fast/reliable under GPU load.
    detect_lane = (ctx.cfg.get("autonomy", {}) or {}).get("detection_lane") or None
    items: list = []
    for attempt in range(2):
        out = hq.llm_json(prompt, caller="inference_autonomy", salience=0.7, cfg=ctx.cfg,
                          want_keys=["gaps", "opportunities", "reasoning"],
                          force_lane=detect_lane)
        for bucket in ("gaps", "opportunities"):
            for it in (out.get(bucket) or []):
                norm = _coerce_item(it, bucket, default_priority)
                if norm:
                    norm["_detect_lane"] = out.get("_lane", "local")  # provenance
                    items.append(norm)
        if items:
            break
        log.info("autonomy gap detection empty (attempt %d) — retrying", attempt + 1)
    if not items:
        # LLM flaked (gemma3:4b can return empty/unparseable on the big prompt even
        # twice) — fall back to deterministic, state-grounded gaps so the autonomy
        # pass is never dead. These are real, not invented.
        items = _heuristic_gaps(ctx, res, default_priority)
        if items:
            log.info("autonomy: using %d heuristic gaps (LLM detection empty)", len(items))
    return items


def _heuristic_gaps(ctx, res, default_priority: float) -> list:
    """Deterministic gaps derived from current state when the LLM returns nothing."""
    gaps = []
    ing = ctx.get("ingestion")
    held = {(p.get("symbol") or "").upper() for p in ing.get("positions", []) if p.get("symbol")}
    funds = [f.upper() for f in (ctx.cfg.get("regional", {}) or {}).get("income_funds", [])]
    covered_navs = {i.subject.upper() for i in res.inferences if i.inference_type == "nav_signal"}

    # 1) held income funds with no NAV read this cycle → valuation gap
    for f in funds:
        if f in held and f not in covered_navs:
            gaps.append({"kind": "gaps", "type": "valuation", "priority": default_priority + 1,
                         "description": f"No NAV premium/discount read this cycle for held income fund {f}",
                         "related_assets": [f]})
    # 2) journal strategies with negative edge → journal/research gap
    for strat, edge in (ctx.scratch.get("journal_edge", {}) or {}).items():
        if edge is not None and float(edge) <= -0.3:
            gaps.append({"kind": "gaps", "type": "research", "priority": default_priority,
                         "suggested_query": f"What recurring mistakes drive losses in '{strat}' trades, "
                                            "and how should entries/sizing change?",
                         "description": f"Negative journal edge ({edge:+.2f}) in strategy '{strat}'"})
    # 3) risk-off / high-vol regime → defensive-positioning research
    if ctx.regime in ("risk_off", "high_vol"):
        gaps.append({"kind": "gaps", "type": "research", "priority": default_priority,
                     "suggested_query": f"In a {ctx.regime} regime, which defensive adjustments best "
                                        "protect a US retirement-income portfolio over 1-2 weeks?",
                     "description": f"{ctx.regime} regime — confirm defensive positioning"})
    return gaps[:5]


def _coerce_item(it, bucket: str, default_priority: float) -> Optional[dict]:
    """Normalize a model item (dict OR bare string) into a uniform gap dict.

    Small local models frequently emit gaps/opportunities as plain strings; treat
    those as research-type items at the action threshold so they aren't silently
    dropped. Dicts are passed through with sane defaults filled in.
    """
    if isinstance(it, dict):
        if not (it.get("description") or it.get("gap") or it.get("opportunity")):
            return None
        it.setdefault("kind", bucket)
        it.setdefault("type", "research")
        it.setdefault("priority", default_priority)
        return it
    if isinstance(it, str) and it.strip():
        return {"kind": bucket, "type": "research", "description": it.strip(),
                "priority": default_priority}
    return None


def _norm_assets(item) -> list:
    a = item.get("related_assets") or item.get("assets") or []
    if isinstance(a, str):
        a = [a]
    return [str(s).upper().strip() for s in a if s and len(str(s)) <= 6][:6]


def act_on_gaps(ctx, items: list, res) -> int:
    """Act on the top items within budget. Appends Inferences to res. Returns count acted."""
    aut = ctx.cfg.get("autonomy", {}) or {}
    max_actions = int(aut.get("max_actions_per_run", 3))
    min_priority = float(aut.get("min_priority", 6))
    action_lane = aut.get("action_lane") or None      # e.g. "grok" → run actions off-box

    def prio(it):
        try:
            return float(it.get("priority", 5))
        except (TypeError, ValueError):
            return 5.0

    items = [it for it in items if prio(it) >= min_priority]
    items.sort(key=prio, reverse=True)
    acted = 0

    for it in items:
        if acted >= max_actions:
            break
        gtype = (it.get("type") or it.get("kind") or "research").lower()
        desc = str(it.get("description") or it.get("opportunity") or it.get("gap") or "")[:1500]
        assets = _norm_assets(it)
        conf = float(it.get("confidence", 0.5) or 0.5)
        subject = (assets[0] if assets else gtype)
        inf_type = _TYPE_MAP.get(gtype, "data_gap")
        need_query = gtype in ("regional", "research", "modeling") or it.get("action") == "query_hermes"

        try:
            if gtype == "valuation" and assets:
                # real NAV premium/discount read
                import inference_financial_modeling as fm
                nav = fm.nav_premium_discount(assets[0], ctx=ctx, cfg=ctx.cfg,
                                              force_lane=action_lane)
                body = nav.get("note") or desc
                conf = float(nav.get("confidence", conf) or conf)
                res.inferences.append(Inference(
                    inference_type="nav_signal", subject=assets[0],
                    title=f"[autonomy] {assets[0]}: {nav.get('signal','valuation').replace('_',' ')}",
                    body=body, confidence=conf, severity="medium" if nav.get("held") else "low",
                    source_lane=nav.get("source", "local"),
                    reasoning_trace=nav.get("reasoning", []),
                    payload={"gap": it, "nav": {k: nav.get(k) for k in
                             ("price", "nav", "premium_pct", "measured", "direction")}}))

            elif need_query and _proactive_remaining(ctx) > 0:
                # autonomous Hermes/LLM follow-up (counts against shared budget)
                q = it.get("suggested_query") or f"Research this gap for the portfolio: {desc}"
                ans = hq.proactive_query(ctx, subject, q, trigger=f"autonomy:{gtype}",
                                         salience=min(1.0, 0.5 + prio(it) / 20.0),
                                         want_keys=["answer", "direction", "confidence", "reasoning"],
                                         force_lane=action_lane)
                res.inferences.append(Inference(
                    inference_type=inf_type if inf_type != "research_gap" else "research_gap",
                    subject=subject,
                    title=f"[autonomy] {gtype}: {desc[:90]}",
                    body=str(ans.get("answer") or "")[:4000],
                    confidence=float(ans.get("confidence", conf) or conf),
                    severity="medium" if prio(it) >= 8 else "low",
                    source_lane=ans.get("_lane", "local"),
                    reasoning_trace=ans.get("reasoning", []) if isinstance(ans.get("reasoning"), list) else [],
                    payload={"gap": it, "assets": assets}))
                if gtype == "research":
                    # advisory topic suggestion — recorded, NOT auto-injected into ingestion
                    remember(f"topic_suggestion:{subject}:{desc[:40]}", "watch",
                             {"suggested_query": q, "priority": prio(it), "assets": assets},
                             salience=min(1.0, prio(it) / 10.0))

            else:
                # no-budget or note-only gap → record as advisory inference + memory
                res.inferences.append(Inference(
                    inference_type=inf_type, subject=subject,
                    title=f"[autonomy] {gtype}: {desc[:90]}",
                    body=desc, confidence=conf,
                    severity="low", source_lane=it.get("_detect_lane", "heuristic"),
                    payload={"gap": it, "assets": assets,
                             "note": "recorded (proactive budget exhausted)" if need_query else "note"}))
            remember(f"gap_detected:{gtype}:{subject}", "gap",
                     {"description": desc, "priority": prio(it), "assets": assets}, salience=conf)
            acted += 1
        except Exception as e:
            log.warning("autonomy action failed (%s/%s): %s", gtype, subject, e)
    return acted


def run_autonomy(ctx, res) -> dict:
    """Entry point called by HigherOrderLayer. Returns {detected, acted}."""
    if (ctx.cfg.get("autonomy", {}) or {}).get("enabled", True) is False:
        return {"detected": 0, "acted": 0}
    try:
        items = detect_gaps(ctx, res)
    except Exception as e:
        log.warning("gap detection failed: %s", e)
        return {"detected": 0, "acted": 0}
    acted = act_on_gaps(ctx, items, res)
    log.info("autonomy: detected=%d acted=%d (proactive_used=%d)",
             len(items), acted, ctx.scratch.get("proactive_used", 0))
    return {"detected": len(items), "acted": acted}
