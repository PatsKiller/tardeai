"""research_quality_escalate.py — Phase-2 desk wire: score_lap → one free SearXNG climb.

Measured (docs/architecture/RESEARCH_ESCALATION_2026-09-14.md): no production path
escalates because an answer was thin. ``research_circle.score_lap`` already decides
sufficiency; Phase 1 recorded ``climb`` and did not take it. This module is the
minimal wire:

  * behind ``RESEARCH_QUALITY_ESCALATE=1`` (off by default);
  * reuses ``score_lap`` / ``SUFFICIENT_SCORE`` / ``deterministic_decision`` —
    no second rubric;
  * on thin evidence, makes **one** governed free SearXNG call
    (``free_search.search``) with ``reason=thin_answer``;
  * does **not** put ``CALLER_DAILY_CAP`` into Brave ``spill_on`` (operator 2026-09-13).

Authority: READ_ONLY_ADVISORY. Never sizes, orders, stops, or writes broker state.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

SCHEMA = "ResearchQualityEscalate@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
FLAG = "RESEARCH_QUALITY_ESCALATE"
REASON = "thin_answer"
CALLER = "research_quality_escalate"

SearchFn = Callable[..., Any]


def enabled(env: Mapping[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def evidence_from_hits(hits: list[dict[str, Any]], *, symbol: Optional[str] = None) -> list[Any]:
    """Map Brave/SearXNG hit dicts onto ``research_circle.Evidence``."""
    from scripts.lib import research_circle as rc

    out: list[Any] = []
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        url = str(h.get("url") or "").strip()
        title = str(h.get("title") or "")
        body = str(h.get("snippet") or h.get("description") or h.get("content") or "")
        text = f"{title} — {body}".strip(" —")[:400]
        if not text and not url:
            continue
        domain = str(h.get("domain") or "")
        engine = str(h.get("engine") or h.get("provider") or "web")
        channel = "web_free" if engine in {"searxng", "free", ""} else "web_paid"
        source = f"{engine}:{domain or 'web'}" if domain or engine else "web"
        as_of = h.get("published") or h.get("publishedDate") or rc.stated_date(text)
        out.append(
            rc.Evidence(
                "web",
                source,
                text or url[:200],
                as_of=as_of,
                symbol=symbol,
                url=url or None,
                channel=channel,
            )
        )
    return out


def evidence_from_answer(answer: Any, *, symbol: Optional[str] = None) -> list[Any]:
    """Turn a Hermes/curation answer blob into a single research Evidence item."""
    from scripts.lib import research_circle as rc

    if answer is None:
        return []
    if isinstance(answer, dict):
        text = str(
            answer.get("summary")
            or answer.get("answer")
            or answer.get("text")
            or answer.get("content")
            or ""
        ).strip()
        as_of = answer.get("as_of")
    else:
        text = str(answer).strip()
        as_of = None
    if not text:
        return []
    return [
        rc.Evidence(
            "research",
            "house:answer",
            text[:800],
            as_of=as_of or rc.stated_date(text),
            symbol=symbol,
            channel="house",
        )
    ]


def score_bundle(
    question: str,
    evidence: list[Any],
    *,
    lap: int = 1,
    max_laps: int = 2,
) -> dict[str, Any]:
    """Pure: needs + score_lap + deterministic_decision."""
    from scripts.lib import research_circle as rc

    needs = rc.detect_needs(question)
    score = rc.score_lap(needs, evidence)
    decision = rc.deterministic_decision(score, lap=lap, max_laps=max_laps)
    return {
        "needs": needs,
        "score": score,
        "decision": decision,
        "thin": bool(
            score.get("overall", 0) < rc.SUFFICIENT_SCORE
            or decision.get("decision") in {"climb", "targeted_lap"}
        ),
        "sufficient_score": rc.SUFFICIENT_SCORE,
    }


def maybe_escalate(
    *,
    question: str,
    symbol: Optional[str] = None,
    search_hits: Optional[list[dict[str, Any]]] = None,
    answer: Any = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = True,
    search_fn: Optional[SearchFn] = None,
    root: Any = None,
) -> dict[str, Any]:
    """Score gathered evidence; if thin and flag on, take one free SearXNG climb.

    Returns a receipt dict. Never raises into the desk path — failures become
    ``escalated=False`` with a detail string.
    """
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": _now_iso(),
        "flag": FLAG,
        "reason": REASON,
        "escalated": False,
        "dry_run": bool(dry_run),
        "enabled": enabled(env),
        "question": str(question or "")[:300],
        "symbol": symbol,
    }
    if not enabled(env):
        receipt["detail"] = f"{FLAG} unset; no climb"
        return receipt

    try:
        evidence = list(evidence_from_hits(list(search_hits or []), symbol=symbol))
        evidence.extend(evidence_from_answer(answer, symbol=symbol))
        bundle = score_bundle(question, evidence)
        receipt["score"] = {
            "overall": bundle["score"].get("overall"),
            "maturity": bundle["score"].get("maturity"),
            "weakest_need": bundle["score"].get("weakest_need"),
            "needs": bundle["needs"],
        }
        receipt["decision"] = bundle["decision"]
        receipt["thin"] = bundle["thin"]
        if not bundle["thin"]:
            receipt["detail"] = "sufficient; no climb"
            return receipt

        if dry_run:
            receipt["detail"] = (
                f"dry_run: would climb via searxng ({REASON}); "
                f"overall={bundle['score'].get('overall')}"
            )
            receipt["would_escalate"] = True
            return receipt

        fn = search_fn
        if fn is None:
            from scripts.lib import free_search as fs

            def fn(q: str, **kwargs: Any) -> Any:
                return fs.search(q, caller=CALLER, kind="web", count=5, root=root, **kwargs)

        resp = fn(str(question).strip() or str(symbol or "research"))
        ok = bool(getattr(resp, "ok", False) if not isinstance(resp, dict) else resp.get("ok"))
        hits = list(
            getattr(resp, "results", None)
            if not isinstance(resp, dict)
            else (resp.get("results") or [])
        )
        reason = str(
            getattr(resp, "reason", "")
            if not isinstance(resp, dict)
            else (resp.get("reason") or "")
        )
        receipt["provider"] = "searxng"
        receipt["search_ok"] = ok
        receipt["search_reason"] = reason
        receipt["hit_count"] = len(hits)
        if not ok or not hits:
            receipt["detail"] = f"climb attempted; searxng empty/refused ({reason or 'no_hits'})"
            return receipt

        receipt["escalated"] = True
        receipt["hits"] = hits
        receipt["detail"] = f"climbed via searxng ({REASON}); +{len(hits)} hits"
        # Re-score with the new evidence so the receipt shows the delta.
        evidence2 = evidence + evidence_from_hits(hits, symbol=symbol)
        after = score_bundle(question, evidence2, lap=2)
        receipt["score_after"] = {
            "overall": after["score"].get("overall"),
            "maturity": after["score"].get("maturity"),
            "thin": after["thin"],
        }
        return receipt
    except Exception as exc:  # noqa: BLE001 — never break the desk
        receipt["detail"] = f"{type(exc).__name__}:{exc}"
        receipt["escalated"] = False
        return receipt


__all__ = [
    "AUTHORITY",
    "CALLER",
    "FLAG",
    "REASON",
    "SCHEMA",
    "enabled",
    "evidence_from_answer",
    "evidence_from_hits",
    "maybe_escalate",
    "score_bundle",
]
