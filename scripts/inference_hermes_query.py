#!/usr/bin/env python3
"""Inference Layers — Hermes / LLM query interface.

The reasoning substrate shared by every inference layer. Wraps:
  * hermes_external_researcher    -> governed cloud lanes
  * rag_retrieval                 -> prior-intelligence context injection

and adds the engine's "mind of its own" primitive: proactive_query(), which lets
a layer decide on its own to ask Hermes a follow-up question when it detects a gap
or a high-salience signal, persisting the exchange to inference_proactive_queries
and inference_memory.

All structured calls return a dict with a reasoning trace + confidence so outputs
are auditable (compatible with llm_context_engine / RAG conventions).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from cio_agent_contract import extract_json_object, merge_structured_into_result

log = logging.getLogger("inference_hermes_query")


# ── JSON extraction (brace-matched, fence-tolerant) ───────────────────────────
def extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    t = text.strip()
    # strip code fences
    if "```" in t:
        m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
        if m:
            t = m.group(1).strip()
    # direct parse
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else {"_list": v}
    except Exception:
        pass
    # brace matching
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception:
                    return None
    return None


def llm_text(prompt: str, caller: str = "inference_engine", timeout: int = 180) -> str:
    """Governed cloud default. Failure remains a hard empty result."""
    try:
        from hermes_external_researcher import call_external
        return call_external("deepseek", "deepseek-v4-flash", prompt, max_tokens=1500) or ""
    except Exception as e:
        log.warning("governed cloud llm error: %s", e)
        return ""


def _external(lane: str, model: str, prompt: str, max_tokens: int = 1500) -> str:
    try:
        from hermes_external_researcher import call_external
        return call_external(lane, model, prompt, max_tokens=max_tokens) or ""
    except Exception as e:
        log.warning("external lane %s error: %s", lane, e)
        return ""


def llm_json(prompt: str, *, caller: str = "inference_engine", timeout: int = 180,
             salience: float = 0.0, cfg: Optional[dict] = None,
             want_keys: Optional[list] = None, force_lane: Optional[str] = None) -> dict:
    """Run a structured reasoning call and return parsed JSON.

    Lane selection:
      * force_lane (e.g. "grok"/"chatgpt") — explicit per-call override; used when a
        step should always run on a free OAuth lane regardless of the global flag.
      * else escalate to cfg.llm.external_lane when cfg.llm.use_external_lane is set
        AND salience clears proactive.salience_threshold.
      * else governed DeepSeek Flash.
    Provider failure stays a failure. The returned dict always carries `_lane`
    and a best-effort `confidence`.
    """
    cfg = cfg or {}
    llm_cfg = cfg.get("llm", {}) or {}
    threshold = (cfg.get("proactive", {}) or {}).get("salience_threshold", 0.65)
    instruction = prompt
    keys = list(want_keys or ["answer", "confidence", "reasoning"])
    for req in ("evidence", "data_i_doubt"):
        if req not in keys:
            keys.append(req)
    instruction += ("\n\nReturn ONLY one JSON object with keys: "
                    + ", ".join(keys)
                    + ". Include numeric \"confidence\" 0.0-1.0, "
                      "\"reasoning\" array of short steps, "
                      "\"evidence\" array of {tag: fact|technical|risk, text}, "
                      "and \"data_i_doubt\" string. No prose outside JSON.")

    chosen = None
    if force_lane == "local":
        return {
            "confidence": 0.0,
            "_lane": "none",
            "_raw_len": 0,
            "error": "POLICY_LOCAL_GENERATIVE_FORBIDDEN",
        }
    if force_lane:
        chosen = force_lane
    elif llm_cfg.get("use_external_lane") and salience >= threshold:
        chosen = llm_cfg.get("external_lane", "grok")

    lane = chosen or "deepseek"
    model = llm_cfg.get("external_model", "grok-3-mini") if chosen else "deepseek-v4-flash"
    raw = _external(lane, model, instruction)

    parsed = extract_json_object(raw) or extract_json(raw) or {}
    parsed = merge_structured_into_result(parsed)
    parsed.setdefault("confidence", 0.5)
    parsed["_lane"] = lane
    parsed["_raw_len"] = len(raw)
    return parsed


# ── RAG context injection ─────────────────────────────────────────────────────
def rag_block(subject: str, limit: int = 6) -> str:
    try:
        from rag_retrieval import get_rag_context, format_rag_context_for_prompt
        hits = get_rag_context(subject, limit=limit)
        if hits:
            return format_rag_context_for_prompt(hits, subject)
    except Exception as e:
        log.debug("rag context unavailable for %s: %s", subject, e)
    return ""


# ── proactive querying ("mind of its own") ────────────────────────────────────
def proactive_query(ctx, subject: str, question: str, trigger: str,
                    salience: float, want_keys: Optional[list] = None,
                    force_lane: Optional[str] = None) -> dict:
    """The engine decides on its own to ask Hermes a follow-up.

    Persists the exchange to inference_proactive_queries and updates
    inference_memory so salient gaps accumulate across cycles. Respects the
    per-run proactive budget enforced by the caller. `force_lane` (e.g. "grok")
    runs the call on a specific governed cloud lane.
    """
    cfg = ctx.cfg
    # count against the per-cycle proactive budget shared by all layers
    ctx.scratch["proactive_used"] = ctx.scratch.get("proactive_used", 0) + 1
    rag = rag_block(subject)
    prompt = question
    if rag:
        prompt = f"{rag}\n\n{question}"

    answer = llm_json(prompt, caller="inference_proactive", salience=salience,
                      cfg=cfg, want_keys=want_keys or ["answer", "confidence", "reasoning"],
                      force_lane=force_lane)
    lane = answer.get("_lane", "none")
    conf = float(answer.get("confidence", 0.5) or 0.5)
    text = answer.get("answer") or answer.get("summary") or json.dumps(
        {k: v for k, v in answer.items() if not k.startswith("_")}, default=str)[:1500]

    # persist
    if not ctx.dry_run and ctx.run_id is not None:
        try:
            from db_adapter import _execute, USE_DB
            if USE_DB:
                _execute(
                    """INSERT INTO inference_proactive_queries
                       (run_id, subject, question, trigger, lane, salience, answer,
                        confidence, status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'answered')""",
                    (ctx.run_id, subject[:300], question[:2000], trigger, lane,
                     float(salience), str(text)[:6000], conf), fetch=None)
        except Exception as e:
            log.warning("proactive persist failed: %s", e)

    # accumulate salience in memory
    try:
        from inference_layer_engine import remember
        remember(f"gap:{subject}:{trigger}", "gap",
                 {"question": question, "answer": str(text)[:1500], "lane": lane},
                 salience=salience)
    except Exception:
        pass

    log.info("proactive[%s] %s (sal=%.2f conf=%.2f) :: %s",
             lane, subject, salience, conf, str(text)[:90])
    answer["answer"] = text
    return answer


# ── region classification (Layer 3 news tagging) ──────────────────────────────
_REGION_KEYWORDS = {
    "Asia": ["china", "chinese", "beijing", "pboc", "japan", "japanese", "boj",
             "tokyo", "nikkei", "yen", "korea", "korean", "samsung", "tsmc",
             "taiwan", "hong kong", "india", "rbi", "sensex", "asia", "yuan",
             "semiconductor", "chip", "hynix"],
    "Europe": ["ecb", "eurozone", "euro ", "germany", "german", "france", "uk ",
               "britain", "bank of england", "frankfurt", "european", "draghi",
               "lagarde", "brexit"],
    "EmergingMarkets": ["brazil", "mexico", "emerging market", "em currency",
                        "south africa", "turkey", "indonesia", "vietnam"],
}


def classify_region(title: str, summary: str = "") -> tuple[str, list]:
    """Cheap keyword region tag for a news item. Returns (region, matched_keywords)."""
    text = f"{title or ''} {summary or ''}".lower()
    best, best_hits = "US", []
    for region, kws in _REGION_KEYWORDS.items():
        hits = [k.strip() for k in kws if k in text]
        if len(hits) > len(best_hits):
            best, best_hits = region, hits
    return best, best_hits
