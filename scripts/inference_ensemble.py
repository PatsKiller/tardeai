#!/usr/bin/env python3
"""inference_ensemble.py — multi-LLM ensemble validator over the FREE lanes only.

A real hybrid ensemble (cloud reasoning + local speed) that aggregates votes from grok (xAI-OAuth proxy
:8645), chatgpt (codex-OAuth proxy :8646) and local gemma — via llm_lane.py. NO metered API keys, no
anthropic/xai/ollama SDKs (per the repo's iron LLM policy). Graceful: unavailable/failed lanes are skipped;
if every lane is down it returns a safe block verdict rather than guessing.

Use cases: topic_curator content rating (opt-in), inference-result quality checks, finance-specific scoring
(NAV/retirement). Config block `ensemble:` in config/inference_layers.yaml (baked defaults if missing).

  python3 scripts/inference_ensemble.py --demo
  python3 scripts/inference_ensemble.py --content "..." [--context "..."] [--task "..."]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

log = logging.getLogger("inference_ensemble")

_DEFAULTS = {
    "lanes": ["grok", "chatgpt", "local"],   # free lanes only (llm_lane)
    "consensus_threshold": 0.66,             # fraction of approve votes for consensus
    "min_score": 6.0,                        # avg score (0-10) that also grants consensus
    "timeout": 60,
}


def _load_cfg() -> dict:
    cfg = dict(_DEFAULTS)
    try:
        import yaml
        p = ROOT / "config" / "inference_layers.yaml"
        if p.exists():
            y = yaml.safe_load(p.read_text()) or {}
            blk = (y.get("inference_layers") or {}).get("ensemble") or y.get("ensemble") or {}
            for k in _DEFAULTS:
                if k in blk:
                    cfg[k] = blk[k]
    except Exception as e:
        log.debug("ensemble config fallback: %s", e)
    return cfg


_FIN_RX = re.compile(
    r"\b(nav|premium|discount|cef|closed.?end|distribution|yield|income|covered call|roth|ira|mapt|"
    r"medicare|irmaa|ssdi|annuit|dividend|return of capital|\broc\b|coverage|sustainab|retire|sequence)\b",
    re.I)


def _finance_rubric(blob: str) -> str:
    """Finance-specific scoring rubric, injected only when the item is finance-substantive so generic
    content keeps a light prompt. Tightens the ensemble on the things a retail/retirement reviewer must
    get right (NAV premium/discount direction, income durability, sizing, tax caveats)."""
    if not _FIN_RX.search(blob):
        return ""
    return (
        "\nFINANCE RUBRIC (apply strictly — score LOWER and lean 'block' if the content gets any wrong):\n"
        "• CEF/ETF vs NAV: a DISCOUNT to NAV is potential value but check for a value trap (distribution "
        "cut / chronic discount); a PREMIUM warrants caution. The premium/discount DIRECTION must be "
        "interpreted correctly — penalize hard if it's backwards.\n"
        "• Income durability: is the distribution covered by earnings, or return-of-capital / NAV erosion? "
        "High yield funded by NAV erosion is NOT sustainable income.\n"
        "• Retirement context (investor on SSDI, NY, Golden-Window Roth): weight income durability + capital "
        "preservation over total-return chasing; flag sequence-of-returns risk.\n"
        "• Sizing/risk: reject FOMO/chase framing and any implied oversizing beyond a sane risk budget.\n"
        "• Tax/Medicare/estate (Roth/MAPT/IRMAA): require a 'confirm with a professional' caveat; do not "
        "approve specific figures stated with false precision.\n"
    )


def _prompt(content: str, context: str, task: str) -> str:
    return (
        "You are one model in a multi-LLM ensemble validating research/inference for a retail investor "
        "(retirement/SSDI/Medicare + markets). Be a strict, finance-aware reviewer.\n"
        f"TASK: {task}\n"
        f"CONTEXT: {context or 'general research / safety relevance'}\n"
        f"CONTENT:\n{content[:4500]}\n"
        f"{_finance_rubric(f'{content} {context} {task}')}\n"
        "Reply ONLY with JSON, no prose:\n"
        '{"score": 0.0-10.0, "decision": "approve" | "block", "confidence": 0.0-1.0, '
        '"reasoning": "<=25 words"}'
    )


def _parse_vote(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group())
    except Exception:
        return None
    try:
        score = float(d.get("score"))
    except (TypeError, ValueError):
        score = None
    dec = str(d.get("decision", "")).lower().strip()
    dec = dec if dec in ("approve", "block") else None
    if score is None and dec is None:
        return None
    try:
        conf = float(d.get("confidence"))
        conf = conf if 0 <= conf <= 1 else 0.5
    except (TypeError, ValueError):
        conf = 0.5
    if score is None:
        score = 7.0 if dec == "approve" else 3.0
    if dec is None:
        dec = "approve" if score >= 6.0 else "block"
    return {"score": max(0.0, min(10.0, score)), "decision": dec, "confidence": round(conf, 2),
            "reasoning": str(d.get("reasoning", ""))[:160]}


def ensemble_validate(content: str, context: str = "", task: str = "content_quality_rating",
                      lanes: Optional[List[str]] = None, cfg: Optional[dict] = None) -> Dict[str, Any]:
    """Aggregate approve/block + score across the free lanes. Returns final verdict + per-lane votes."""
    cfg = cfg or _load_cfg()
    lanes = lanes or cfg["lanes"]
    try:
        import llm_lane
    except Exception as e:
        return {"final_decision": "block", "final_score": 0.0, "final_confidence": 0.3,
                "consensus_reached": False, "lanes_used": [], "votes": [],
                "reasoning_summary": f"llm_lane unavailable ({e}) — safe block"}
    prompt = _prompt(content, context, task)
    votes: List[Dict[str, Any]] = []
    for lane in lanes:
        try:
            if not llm_lane.available(lane):
                continue
            raw = llm_lane.generate(prompt, lane=lane, timeout=int(cfg["timeout"]))
            v = _parse_vote(raw)
            if v:
                v["lane"] = lane
                votes.append(v)
        except Exception as e:
            log.warning("ensemble lane %s failed: %s", lane, str(e)[:80])
            continue
    if not votes:
        return {"final_decision": "block", "final_score": 0.0, "final_confidence": 0.3,
                "consensus_reached": False, "lanes_used": [], "votes": [],
                "reasoning_summary": "no free lanes returned a vote — safe block (no guess)"}
    scores = [v["score"] for v in votes]
    approve = sum(1 for v in votes if v["decision"] == "approve")
    avg = sum(scores) / len(scores)
    approve_frac = approve / len(votes)
    consensus = approve_frac >= cfg["consensus_threshold"] or avg >= cfg["min_score"]
    majority = "approve" if approve_frac > 0.5 else "block"
    final = majority if consensus else "block"
    return {"final_decision": final, "final_score": round(avg, 2),
            "final_confidence": round(sum(v["confidence"] for v in votes) / len(votes), 2),
            "consensus_reached": bool(consensus), "lanes_used": [v["lane"] for v in votes],
            "votes": votes,
            "reasoning_summary": f"avg={avg:.1f}, {approve}/{len(votes)} approve, consensus={consensus}"}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [ensemble] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", default="")
    ap.add_argument("--context", default="")
    ap.add_argument("--task", default="content_quality_rating")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    content = a.content or (
        "Fed signals data-dependent path; semiconductor equipment names extend gains on AI capex. "
        "Analysts flag valuation dispersion vs 2021." if a.demo else "")
    if not content:
        print("provide --content or --demo"); return 1
    res = ensemble_validate(content, a.context, a.task)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
