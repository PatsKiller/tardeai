"""LLM curation of a market-risk card — the model may rephrase ONE sentence, nothing else.

Design DSN-20261031-market-risk-engine §5.10 / P3-T3. Operator 2026-10-31: "you can have normalization and alerts
curated by LLM." The deterministic card (built by the engine, never by a model) is the product. This module may hand
the model the card and the assessment and ask for a plainer "Why:" sentence. The candidate sentence is rejected, and
the deterministic card returned unchanged, when:

* it contains a number that is in neither the card nor the assessment (``agent_number_grounding.check_grounding``
  with a zero-tolerance threshold — one invented figure is enough);
* it contains behaviour wording (buy, sell, trim, share counts, a stop level, an order type, a dollar amount) —
  ``MBI_BEHAVIOR = 0``; patterns live in ``config/market_risk_curation.yaml``;
* the lane chain fails, refuses, returns nothing, or exceeds the tier's time budget (a RED card is never held for prose).

The model call goes through ``scripts/lib/llm_fallback.generate_with_fallback`` with ``allow_paid=False`` and the
registered process ``market_risk_alert_curation`` (free OAuth grok -> chatgpt; the consumption gate and caps apply on
every attempt). Tests inject ``call_model(prompt, timeout_s) -> text | (text, lane)``; nothing here opens a socket of its own. The free lanes
are not subject to the off-peak deferral (that gate covers metered DeepSeek calls only, lib/llm_deferral.py).
"""

from __future__ import annotations

import concurrent.futures
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "market_risk_curation.yaml"
SCHEMA = "MarketRiskCurationResult@v1"


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("schema") != "MarketRiskCuration@v1":
        raise ValueError(f"{path}: expected schema MarketRiskCuration@v1, got {data.get('schema')!r}")
    return data


def _grounding():
    try:
        from scripts.lib import agent_number_grounding as g  # type: ignore
    except ImportError:  # pragma: no cover — cron path with scripts/ on sys.path
        from lib import agent_number_grounding as g  # type: ignore
    return g


def split_why(card_text: str, prefix: str) -> tuple[list[str], Optional[int]]:
    """Card lines and the index of the "Why:" line (None when the card has none)."""
    lines = card_text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith(prefix.strip()):
            return lines, i
    return lines, None


def behaviour_hits(text: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if re.search(p, text, flags=re.IGNORECASE)]


def ungrounded_numbers(sentence: str, card_text: str, assessment: dict[str, Any]) -> list[str]:
    """Numbers in ``sentence`` that neither the card nor the assessment supplies. Zero tolerance."""
    g = _grounding()
    supplied = card_text + "\n" + json.dumps(assessment, default=str, sort_keys=True)
    res = g.check_grounding([sentence], supplied, min_unsupported=1, max_share=0.0)
    return list(res.get("unsupported") or [])


def build_prompt(card_text: str, assessment: dict[str, Any], current_why: str, cfg: dict[str, Any]) -> str:
    facts = {
        "tier": assessment.get("tier"),
        "score": assessment.get("score"),
        "confirming": assessment.get("confirming"),
        "contributors": assessment.get("contributors"),
        "deescalates_if": assessment.get("deescalates_if"),
        "as_of": assessment.get("as_of"),
    }
    return (
        "You rewrite ONE sentence of a market-risk alert for a busy investor reading on a phone.\n"
        f"Return only the sentence, at most {int(cfg.get('max_why_chars') or 280)} characters, no prefix, no quotes.\n"
        "RULES: say why risk is at this level, using only the facts below. Do not add any number that is not in the "
        "facts. Do not recommend buying, selling, trimming, hedging, a stop level, an order or a position size. "
        "Do not reassure and do not exaggerate.\n\n"
        f"CURRENT SENTENCE: {current_why or '(none)'}\n\n"
        f"CARD:\n{card_text}\n\nFACTS:\n{json.dumps(facts, default=str, indent=1)}\n"
    )


def default_call_model(cfg: dict[str, Any]) -> Callable[[str, float], Any]:
    """Production model call: the governed free-lane fallback chain, never a provider client of our own."""

    def _call(prompt: str, timeout_s: float) -> str:
        try:
            from scripts.lib.llm_fallback import generate_with_fallback  # type: ignore
        except ImportError:  # pragma: no cover
            from lib.llm_fallback import generate_with_fallback  # type: ignore
        res = generate_with_fallback(
            prompt,
            lane=str(cfg.get("lane") or "grok"),
            allow_paid=bool(cfg.get("allow_paid", False)),
            process_id=str(cfg.get("process_id") or "market_risk_alert_curation"),
            timeout=float(timeout_s),
            max_tokens=int(cfg.get("max_tokens") or 200),
        )
        return str(getattr(res, "text", "") or ""), str(getattr(res, "lane", "") or "")

    return _call


def _result(text: str, *, curated: bool, lane: Optional[str], reason: str, **extra: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "text": text, "curated": curated, "lane": lane, "reason": reason, **extra}


def curate(
    card_text: str,
    assessment: dict[str, Any],
    *,
    call_model: Optional[Callable[[str, float], Any]] = None,
    cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return ``{text, curated, lane, reason}``. ``text`` is always sendable; on any doubt it is ``card_text``."""
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("enabled", False):
        return _result(card_text, curated=False, lane=None, reason="curation disabled")
    tier = str(assessment.get("tier") or "").upper()
    if tier in {str(t).upper() for t in (cfg.get("skip_tiers") or [])}:
        return _result(card_text, curated=False, lane=None, reason=f"tier {tier} is never curated")
    prefix = str(cfg.get("why_prefix") or "Why: ")
    lines, idx = split_why(card_text, prefix)
    current = lines[idx].strip()[len(prefix.strip()) :].strip() if idx is not None else ""
    budgets = cfg.get("timeout_s") or {}
    timeout_s = float(budgets.get(tier, budgets.get("default", 10)))
    call = call_model or default_call_model(cfg)
    prompt = build_prompt(card_text, assessment, current, cfg)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(call, prompt, timeout_s)
    try:
        answer = fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        pool.shutdown(wait=False, cancel_futures=True)
        return _result(card_text, curated=False, lane=None, reason=f"timeout after {timeout_s:g}s")
    except Exception as exc:  # noqa: BLE001 — every lane failure is a reason, and the deterministic card is sent
        pool.shutdown(wait=False, cancel_futures=True)
        return _result(card_text, curated=False, lane=None, reason=f"lane failure: {type(exc).__name__}: {exc}"[:240])
    pool.shutdown(wait=False)

    lane = str(cfg.get("lane") or "grok")
    if isinstance(answer, tuple):  # (text, lane that answered) from the fallback chain
        answer, lane = answer[0], (answer[1] or lane)
    sentence = " ".join(str(answer or "").split()).strip().strip('"').strip()
    if sentence.lower().startswith(prefix.strip().lower()):
        sentence = sentence[len(prefix.strip()) :].strip()
    if not sentence:
        return _result(card_text, curated=False, lane=lane, reason="empty answer")
    if len(sentence) > int(cfg.get("max_why_chars") or 280):
        return _result(card_text, curated=False, lane=lane, reason="answer longer than max_why_chars")
    hits = behaviour_hits(sentence, list(cfg.get("behaviour_patterns") or []))
    if hits:
        return _result(card_text, curated=False, lane=lane, reason="behaviour wording rejected", rejected=hits)
    bad = ungrounded_numbers(sentence, card_text, assessment)
    if bad:
        return _result(card_text, curated=False, lane=lane, reason="ungrounded numbers rejected", rejected=bad)

    new_line = f"{prefix}{sentence}"
    if idx is None:
        lines = lines[:1] + [new_line] + lines[1:]
    else:
        lines[idx] = new_line
    return _result("\n".join(lines), curated=True, lane=lane, reason="grounded", original_why=current)
