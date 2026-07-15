"""Narrative enrichment for Research Intelligence feed items.

Transforms raw Hermes/topic text into Seeking Alpha–style article structure
without requiring a live LLM call on every request (cost-safe, deterministic).

Optional: research_intelligence_narrative_enrich.py can pre-write richer copy
via local llm_lane for high-priority items into evidence_json.narrative.
"""
from __future__ import annotations

import re
from typing import Any


def _clean(s: str | None) -> str:
    if not s:
        return ""
    t = re.sub(r"\s+", " ", str(s)).strip()
    return t


def _sentences(text: str) -> list[str]:
    text = _clean(text)
    if not text:
        return []
    # Split on sentence boundaries; keep reasonable chunks
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    out = [p.strip() for p in parts if p and len(p.strip()) > 20]
    if not out and text:
        out = [text]
    return out


def _paras_from_text(text: str, max_paras: int = 3, max_chars: int = 1200) -> list[str]:
    sents = _sentences(text)
    if not sents:
        return []
    paras: list[str] = []
    buf: list[str] = []
    n = 0
    for s in sents:
        buf.append(s)
        n += len(s)
        if len(buf) >= 2 or n > 280:
            paras.append(" ".join(buf))
            buf, n = [], 0
            if len(paras) >= max_paras:
                break
    if buf and len(paras) < max_paras:
        paras.append(" ".join(buf))
    # cap total
    joined, out = 0, []
    for p in paras:
        if joined + len(p) > max_chars:
            remain = max_chars - joined
            if remain > 80:
                out.append(p[:remain].rstrip() + "…")
            break
        out.append(p)
        joined += len(p)
    return out


def _scrub_llm_filler(s: str) -> str:
    """Drop model throat-clearing that pollutes takeaways."""
    t = _clean(s)
    t = re.sub(
        r"^(okay[,.]?\s*)?(here'?s|here is)\s+(an?\s+)?(updated\s+)?(advisory|brief|summary|research)[^:]*:\s*",
        "", t, flags=re.I,
    )
    t = re.sub(r"^\*?\*?1\.\s*", "", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    return t.strip()


def _takeaways(summary: str, thesis: str | None, key_questions: list[str] | None) -> list[str]:
    out: list[str] = []
    if thesis and len(thesis.strip()) > 15:
        t = _scrub_llm_filler(thesis)
        if t:
            out.append(t[:220])
    sents = _sentences(summary)
    for s in sents:
        s = _scrub_llm_filler(s)
        if not s or len(s) < 25:
            continue
        if s.startswith("Topic monitor"):
            continue
        if s not in out and len(out) < 4:
            if re.search(
                r"\b(should|must|risk|opportunity|convert|IRMAA|Roth|dividend|hold|watch|impact|wash.?sale)\b",
                s, re.I,
            ) or len(out) < 2:
                out.append(s[:220])
    for q in (key_questions or [])[:2]:
        line = f"Open question: {_clean(q)[:180]}"
        if line not in out and len(out) < 5:
            out.append(line)
    return out[:5]


def _bull_bear(text: str, cats: list[str], sentiment: str) -> tuple[str | None, str | None]:
    """Bull/bear framed from PRIMARY category only (cats[0])."""
    blob = text.lower()
    bull = bear = None
    primary = (cats[0] if cats else "") or ""
    if primary == "retirement_tax":
        bull = (
            "Well-timed conversions during the Golden Window can fill lower brackets "
            "and reduce future RMDs and IRMAA exposure if MAGI is managed carefully."
        )
        bear = (
            "Aggressive conversion pacing can push MAGI into IRMAA tiers (two-year lookback) "
            "or create tax-bracket cliffs—verify brackets before batching conversions."
        )
    elif primary == "dividend_income":
        bull = "Sustainable yield and covered-call/ETF income can support retirement cash flow without forced sales."
        bear = "High-yield traps, NAV decay, and rate shocks can erode total return even when coupons look attractive."
    elif primary in ("macro_geo", "sector_thematic"):
        bull = "Clear regime or sector signals can improve allocation timing and reduce portfolio heat."
        bear = "False regime breaks and headline-driven rotation can whipsaw if position sizing ignores risk limits."
    elif primary == "catalyst_event":
        bull = "A confirmed catalyst with source attribution can justify a watch or staged entry plan."
        bear = "Crowded catalysts often price in optimism early; gaps in evidence raise false-positive risk."
    elif primary == "risk_regime":
        bull = "Tight risk controls preserve capital when heat is elevated and setups are noisy."
        bear = "Ignoring stop health or portfolio heat can turn a small drawdown into a book-level problem."
    else:
        if sentiment == "bullish":
            bull = "Tone and evidence lean constructive; confirmation from holdings exposure would strengthen the case."
        if sentiment == "bearish":
            bear = "Tone and evidence lean cautious; review stops, size, and whether the thesis still holds."

    # Override from text if explicit
    m_b = re.search(r"(?:bull(?:ish)?\s*(?:case)?[:—-]\s*)(.+?)(?:\.|$)", text, re.I)
    m_r = re.search(r"(?:bear(?:ish)?\s*(?:case)?[:—-]\s*)(.+?)(?:\.|$)", text, re.I)
    if m_b:
        bull = m_b.group(1).strip()[:240]
    if m_r:
        bear = m_r.group(1).strip()[:240]
    if primary == "retirement_tax" and ("limited" in blob or "sparse" in blob or "zero details" in blob):
        bear = ((bear or "") + " Source coverage is thin—treat conclusions as provisional.").strip()[:280]
    return bull, bear


def _why_it_matters(
    *,
    cats: list[str],
    is_held: bool,
    symbol: str | None,
    holdings_note: str | None = None,
) -> str:
    primary = (cats[0] if cats else "") or ""
    if primary == "retirement_tax":
        base = (
            "This sits on the retirement/tax path: conversion pacing, IRMAA lookback, "
            "and Golden Window timing directly affect multi-year after-tax outcomes."
        )
    elif is_held and symbol:
        base = f"{symbol} is in the live book—developments here can change income, risk, or rebalance priorities."
    elif is_held:
        base = "Linked to current holdings—portfolio impact is first-order, not theoretical."
    elif primary == "dividend_income":
        base = "Income-sleeve and yield quality affect retirement cash flow and concentration risk."
    elif primary in ("macro_geo", "sector_thematic"):
        base = "Macro/sector context shapes whether growth, defense, or income sleeves should lead."
    elif primary == "risk_regime":
        base = "Stop health and regime affect capital preservation more than alpha hunting right now."
    else:
        base = "Useful context for the watchlist and research desk; elevate if it intersects holdings or retirement plan."
    if holdings_note:
        base = f"{base} {holdings_note}"
    return base


def _next_action(
    *,
    cats: list[str],
    is_held: bool,
    symbol: str | None,
    actionability: str | None,
    needs_refresh: bool,
    research_type: str | None,
) -> dict[str, str]:
    """Structured next action for UI CTA."""
    primary = (cats[0] if cats else "") or ""
    # Topic monitors: always prioritize ingest/research over generic "refresh"
    if research_type == "topic_monitor":
        return {
            "label": "Run topic research",
            "detail": "Pull fresh sources via topic_ingestion, then open the synthesized Hermes brief.",
            "href_hint": "topic_monitor",
        }
    if needs_refresh:
        return {
            "label": "Refresh coverage",
            "detail": "This item is past its refresh cadence—re-run topic ingestion or Hermes research before acting.",
            "href_hint": "ingestion",
        }
    if primary == "retirement_tax":
        return {
            "label": "Review Roth / tax plan",
            "detail": actionability or "Map IRMAA, MAGI, and conversion room against the Golden Window plan.",
            "href_hint": "retirement",
        }
    if is_held and symbol:
        return {
            "label": f"Review {symbol} position",
            "detail": actionability or "Check thesis validity, stop health, and whether income/risk still fit the plan.",
            "href_hint": "portfolio",
        }
    if primary == "dividend_income":
        return {
            "label": "Check income sleeve",
            "detail": actionability or "Compare yield quality vs holdings (SCHD, JEPI/JEPQ, BDCs) and concentration.",
            "href_hint": "dividends",
        }
    if primary == "risk_regime":
        return {
            "label": "Inspect risk / stops",
            "detail": actionability or "Validate stop coverage and heat before adding risk.",
            "href_hint": "risk",
        }
    return {
        "label": "Read full analysis",
        "detail": actionability or "Open the full brief, verify sources, then decide watch / hold / act.",
        "href_hint": "detail",
    }


def _lede(title: str, summary: str, cats: list[str]) -> str:
    sents = _sentences(summary)
    if sents:
        return sents[0][:280]
    if "retirement_tax" in cats:
        return f"Retirement desk briefing on {title}: planning implications and what to verify next."
    return f"Intelligence brief: {title}."


def _from_stored_narrative(ev: Any) -> dict[str, Any] | None:
    if not isinstance(ev, dict):
        return None
    n = ev.get("narrative") or ev.get("article") or ev.get("ri_narrative")
    if not isinstance(n, dict):
        return None
    if not (n.get("executive_summary") or n.get("overview") or n.get("body")):
        return None
    return n


def _attach_advisory(
    base: dict[str, Any],
    *,
    title: str,
    summary: str,
    thesis: str | None,
    cats: list[str],
    symbol: str | None,
    is_held: bool,
    research_type: str | None,
    portfolio: Any = None,
) -> dict[str, Any]:
    """Merge portfolio-aware ticker/sizing recommendations into narrative dict."""
    try:
        from lib.research_intelligence_portfolio import build_advisory
        adv = build_advisory(
            title=title,
            summary=summary,
            thesis=thesis,
            cats=cats,
            primary=(cats[0] if cats else "") or "",
            symbol=symbol,
            is_held=is_held,
            research_type=research_type,
            portfolio=portfolio,
        )
    except Exception:
        return base
    base["investment_implications"] = adv.get("investment_implications")
    base["ticker_recommendations"] = adv.get("ticker_recommendations") or []
    base["sizing_guidance"] = adv.get("sizing_guidance")
    base["risk_caveat"] = adv.get("risk_caveat")
    base["portfolio_snapshot"] = adv.get("portfolio_snapshot")
    # Prefer portfolio-aware next_action unless topic_monitor needs ingest first
    if research_type == "topic_monitor":
        base["next_action"] = base.get("next_action") or adv.get("next_action")
    else:
        base["next_action"] = adv.get("next_action") or base.get("next_action")
    # Elevate takeaways with ticker line only when we have real recommendations
    ticks = [
        t for t in (base.get("ticker_recommendations") or [])
        if t.get("symbol") and t.get("role") in (
            "add_candidate", "trim_candidate", "protect", "hold_review"
        )
    ]
    if ticks and isinstance(base.get("key_takeaways"), list):
        line = "Tickers: " + ", ".join(
            f"{t.get('symbol')} ({t.get('role')})" for t in ticks[:4]
        )
        # Avoid duplicating the same sleeve line on every card
        base["key_takeaways"] = [x for x in base["key_takeaways"] if not str(x).startswith("Tickers:")]
        base["key_takeaways"] = [line] + list(base["key_takeaways"])[:4]
    return base


def enrich_narrative(
    *,
    title: str,
    summary: str,
    thesis: str | None = None,
    cats: list[str] | None = None,
    symbol: str | None = None,
    is_held: bool = False,
    sentiment: str = "neutral",
    key_questions: list[str] | None = None,
    data_gaps: list[str] | None = None,
    actionability: str | None = None,
    needs_refresh: bool = False,
    research_type: str | None = None,
    evidence_json: Any = None,
    source_system: str | None = None,
    portfolio: Any = None,
) -> dict[str, Any]:
    """Return article-style narrative fields for a feed item."""
    cats = cats or []
    stored = _from_stored_narrative(evidence_json)
    if stored:
        overview = stored.get("executive_summary") or stored.get("overview") or stored.get("body") or ""
        if isinstance(overview, list):
            paras = [str(p) for p in overview if p]
        else:
            paras = _paras_from_text(str(overview), max_paras=4, max_chars=1600)
        out = {
            "lede": stored.get("lede") or _lede(title, summary or str(overview), cats),
            "executive_summary": paras,
            "key_takeaways": stored.get("key_takeaways") or _takeaways(summary, thesis, key_questions),
            "bull_case": stored.get("bull_case"),
            "bear_case": stored.get("bear_case"),
            "why_it_matters": stored.get("why_it_matters") or _why_it_matters(
                cats=cats, is_held=is_held, symbol=symbol
            ),
            "next_action": stored.get("next_action") or _next_action(
                cats=cats, is_held=is_held, symbol=symbol,
                actionability=actionability, needs_refresh=needs_refresh,
                research_type=research_type,
            ),
            "narrative_source": "stored_llm",
            "reading_minutes": max(1, min(6, len(" ".join(paras)) // 500 or 1)),
        }
        return _attach_advisory(
            out, title=title, summary=summary, thesis=thesis, cats=cats,
            symbol=symbol, is_held=is_held, research_type=research_type, portfolio=portfolio,
        )

    body_src = " ".join(x for x in [summary, thesis] if x)
    # Topic monitors: always write a proper desk brief (metadata is not an article)
    if research_type == "topic_monitor":
        ctx = summary or ""
        # Strip mechanical "Topic monitor · …" prefix if present
        ctx = re.sub(r"^Topic monitor[^.]*\.\s*", "", ctx, flags=re.I).strip()
        body_src = (
            f"{title} is a standing watch on the Research Intelligence desk—kept on a short "
            f"refresh cycle so policy, tax, and market shifts do not go unnoticed. "
            f"{ctx + ' ' if ctx else ''}"
            f"When new sources land, topic ingestion and Hermes turn the monitor into a sourced brief "
            f"with thesis and citations. Until the next ingest cycle, use this card as the "
            f"operator checklist for what matters and what to verify next."
        )

    paras = _paras_from_text(body_src, max_paras=3, max_chars=1400)
    if not paras and thesis:
        paras = [_clean(thesis)]
    if not paras:
        paras = [
            f"{title} is queued on the Research Intelligence desk. "
            "Open the full record or trigger a refresh to pull narrative coverage and sources."
        ]

    # Ensure 2+ paragraphs when we have thesis distinct from summary
    if len(paras) == 1 and thesis and _clean(thesis) not in paras[0]:
        paras.append(_clean(thesis)[:400])

    bull, bear = _bull_bear(body_src, cats, sentiment)
    takeaways = _takeaways(summary, thesis, key_questions)
    if data_gaps:
        takeaways = takeaways[:4] + [f"Data gap: {_clean(data_gaps[0])[:160]}"]

    why = _why_it_matters(cats=cats, is_held=is_held, symbol=symbol)
    nxt = _next_action(
        cats=cats, is_held=is_held, symbol=symbol,
        actionability=actionability, needs_refresh=needs_refresh,
        research_type=research_type,
    )

    # Closing paragraph: what changed / verification
    if data_gaps and len(paras) < 4:
        paras.append(
            "Coverage still has gaps—confirm figures against primary sources (IRS, CMS, FRED, or filings) "
            "before any irreversible tax or portfolio move."
        )
    elif source_system == "hermes" and len(paras) < 3:
        paras.append(
            "This brief is grounded on Hermes research with source attribution where available. "
            "Use the action strip below to route the next operator step."
        )

    lede_src = body_src if research_type == "topic_monitor" else (summary or body_src)
    out = {
        "lede": _lede(title, lede_src, cats),
        "executive_summary": paras,
        "key_takeaways": takeaways,
        "bull_case": bull,
        "bear_case": bear,
        "why_it_matters": why,
        "next_action": nxt,
        "narrative_source": "synthesized",
        "reading_minutes": max(1, min(5, sum(len(p) for p in paras) // 450 or 1)),
    }
    return _attach_advisory(
        out, title=title, summary=summary, thesis=thesis, cats=cats,
        symbol=symbol, is_held=is_held, research_type=research_type, portfolio=portfolio,
    )
