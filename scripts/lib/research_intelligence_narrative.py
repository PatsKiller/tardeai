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


def _bull_bear(
    text: str,
    cats: list[str],
    sentiment: str,
    portfolio: Any = None,
) -> tuple[str | None, str | None]:
    """Bull/bear framed from PRIMARY category, optionally portfolio-specific."""
    blob = text.lower()
    bull = bear = None
    primary = (cats[0] if cats else "") or ""
    port = portfolio if isinstance(portfolio, dict) else {}
    by_sym = port.get("by_symbol") or {}
    heat = port.get("heat") or {}
    conc = port.get("concentration") or {}
    sleeves = port.get("sleeves") or {}
    schg = (by_sym.get("SCHG") or {}).get("weight_pct")
    schd = (by_sym.get("SCHD") or {}).get("weight_pct")
    heat_pct = heat.get("portfolio_heat_pct")
    book_lvl = conc.get("book_level") or "normal"
    inc = sleeves.get("dividend_income")

    if primary == "retirement_tax":
        bull = (
            "Well-timed conversions during the Golden Window can fill lower brackets "
            "and reduce future RMDs and IRMAA exposure if MAGI is managed carefully"
            + (f" — while SCHD (~{schd:.1f}%) anchors quality income" if schd else "")
            + "."
        )
        bear = (
            "Aggressive conversion pacing can push MAGI into IRMAA tiers (two-year lookback) "
            "or create tax-bracket cliffs"
            + (f"; taxable income sleeve ~{inc:.0f}% already lifts MAGI" if inc and inc >= 25 else "")
            + (f". Avoid auto-liquidating SCHG (~{schg:.1f}%) to fund tax without a plan" if schg and schg >= 20 else "")
            + "."
        )
    elif primary == "dividend_income":
        bull = (
            "Sustainable yield can support retirement cash flow without forced sales"
            + (f"; quality anchor SCHD is ~{schd:.1f}% of book" if schd else "")
            + "."
        )
        bear = (
            "High-yield traps, NAV decay, and rate shocks can erode total return"
            + (f" — income sleeve already ~{inc:.0f}% of book" if inc and inc >= 25 else "")
            + "; more yield is not always more after-tax spending power under IRMAA."
        )
    elif primary in ("macro_geo", "sector_thematic"):
        bull = (
            "Clear regime or sector signals can improve allocation timing"
            + (f" if funded from concentrated growth (book {book_lvl})" if book_lvl != "normal" else "")
            + " rather than stacking unhedged beta."
        )
        bear = (
            "False regime breaks and headline-driven rotation can whipsaw"
            + (f" while heat is ~{heat_pct:.1f}%" if heat_pct is not None else "")
            + " — size only with stops and theme capacity room."
        )
    elif primary == "catalyst_event":
        bull = "A confirmed catalyst with source attribution can justify a watch or staged entry with a hard stop."
        bear = (
            "Crowded catalysts often price in optimism early; "
            f"book concentration is {book_lvl} so any add should be funded, not layered on top."
        )
    elif primary == "risk_regime":
        bull = (
            "Tight risk controls preserve capital when setups are noisy"
            + (f" (heat ~{heat_pct:.1f}%)" if heat_pct is not None else "")
            + "; fixing stops on top weights is high-ROI work."
        )
        bear = (
            "Ignoring stop health or portfolio heat can turn a small drawdown into a book-level problem"
            + (f" — especially with SCHG ~{schg:.1f}%" if schg and schg >= 20 else "")
            + "."
        )
    elif primary == "compounding_wealth":
        bull = (
            "Systematic compounding (DCA/reinvest) beats one-off growth adds when valuations are noisy"
            + (f"; SCHG ~{schg:.1f}% already delivers core growth beta" if schg else "")
            + "."
        )
        bear = (
            "Stacking megacap growth on an already concentrated book "
            f"({book_lvl}) raises drawdown risk without improving the long-term plan."
        )
    else:
        if sentiment == "bullish":
            bull = (
                "Tone and evidence lean constructive; size any expression against live weights "
                f"and heat{f' (~{heat_pct:.1f}%)' if heat_pct is not None else ''}."
            )
        else:
            bull = (
                "If the thesis holds after source checks, prefer held names or a small funded starter "
                f"given book concentration is {book_lvl}."
            )
        if sentiment == "bearish":
            bear = "Tone and evidence lean cautious; review stops, size, and whether the thesis still holds."
        else:
            bear = (
                "Acting without stop coverage or ignoring concentration "
                f"({book_lvl}) can convert a research idea into unintended book risk."
            )

    # Override from text if explicit
    m_b = re.search(r"(?:bull(?:ish)?\s*(?:case)?[:—-]\s*)(.+?)(?:\.|$)", text, re.I)
    m_r = re.search(r"(?:bear(?:ish)?\s*(?:case)?[:—-]\s*)(.+?)(?:\.|$)", text, re.I)
    if m_b:
        bull = m_b.group(1).strip()[:280]
    if m_r:
        bear = m_r.group(1).strip()[:280]
    if primary == "retirement_tax" and ("limited" in blob or "sparse" in blob or "zero details" in blob):
        bear = ((bear or "") + " Source coverage is thin—treat conclusions as provisional.").strip()[:320]
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


def _polish_narrative_depth(base: dict[str, Any], *, title: str, cats: list[str]) -> dict[str, Any]:
    """Ensure minimum advisory depth: implications paragraph, quality tier, no stub fluff."""
    primary = (cats[0] if cats else "") or "general"
    paras = list(base.get("executive_summary") or [])
    # Drop pure monitor boilerplate (replaced below if body becomes thin)
    paras = [
        p for p in paras
        if "standing watch on the Research Intelligence desk" not in (p or "")
        and "queued on the Research Intelligence desk" not in (p or "")
    ]
    impl = base.get("investment_implications") or ""
    size = base.get("sizing_guidance") or ""
    why = base.get("why_it_matters") or ""
    body_len = sum(len(p or "") for p in paras)

    # Thin body → inject advisory-grade paragraphs (not generic stubs)
    if body_len < 180:
        rebuilt: list[str] = []
        if why:
            rebuilt.append(why[:360])
        if impl:
            rebuilt.append(impl[:420])
        if size:
            rebuilt.append(f"Portfolio sizing context: {size[:380]}")
        if not rebuilt:
            rebuilt = [
                f"{title}: operator briefing in the {primary.replace('_', ' ')} lane. "
                f"Verify sources, then apply the action strip with current weights and stops."
            ]
        # Keep any non-boilerplate residual first
        paras = (paras + rebuilt)[:4]
        body_len = sum(len(p or "") for p in paras)
    else:
        if impl and not any(impl[:40] in (p or "") for p in paras) and body_len < 320:
            paras.append(impl[:420])
        if size and len(paras) < 3 and size not in " ".join(paras):
            paras.append(f"Portfolio context: {size[:380]}")

    if not paras:
        paras = [
            f"{title}: desk briefing with portfolio-aware next steps. "
            f"Category {primary} — verify sources before acting."
        ]
    base["executive_summary"] = paras[:4]
    body_len = sum(len(p or "") for p in paras)

    # Ensure bull/bear exist (advisory maturity) — portfolio-aware when possible
    port = base.get("portfolio_snapshot")
    # portfolio_snapshot is slim; full port may be absent — still improve generics
    if not base.get("bull_case") or not base.get("bear_case"):
        blob = " ".join(paras) + " " + (impl or "")
        # Reconstruct minimal port from snapshot for weight-aware bull/bear
        mini_port = None
        if isinstance(port, dict):
            mini_port = {
                "by_symbol": {
                    k: {"weight_pct": v}
                    for k, v in (port.get("related_weights") or {}).items()
                },
                "heat": port.get("heat") or {},
                "concentration": port.get("concentration") or {},
                "sleeves": port.get("sleeves") or {},
            }
            # Ensure SCHG/SCHD from top if present
            for row in port.get("top") or []:
                sym = row.get("symbol")
                if sym:
                    mini_port["by_symbol"][sym] = {"weight_pct": row.get("weight_pct")}
        bull, bear = _bull_bear(blob, cats, "neutral", portfolio=mini_port)
        if not base.get("bull_case") and bull:
            base["bull_case"] = bull
        if not base.get("bear_case") and bear:
            base["bear_case"] = bear

    if not base.get("why_it_matters") and why:
        base["why_it_matters"] = why
    elif not base.get("why_it_matters"):
        base["why_it_matters"] = _why_it_matters(
            cats=cats, is_held=False, symbol=None
        )

    # Quality tier for UI — systematic A/B/C (includes security conviction on tickers)
    ticks = base.get("ticker_recommendations") or []
    has_llm = base.get("narrative_source") == "stored_llm"
    has_size = bool(base.get("sizing_guidance") and len(str(base.get("sizing_guidance") or "")) > 40)
    has_reason = bool(base.get("sizing_reason"))
    has_bull_bear = bool(base.get("bull_case") and base.get("bear_case"))
    has_impl = bool(impl and len(impl) > 60)
    has_sec = any(
        t.get("conviction_tier") or (t.get("security") or {}).get("rsi") is not None
        for t in ticks
    )
    has_why = any(t.get("why_selected") for t in ticks)
    advisory_score = sum([
        1 if ticks else 0,
        1 if has_size else 0,
        1 if has_reason else 0,
        1 if has_bull_bear else 0,
        1 if has_impl else 0,
        1 if body_len > 280 else 0,
        1 if has_sec else 0,
        1 if has_why else 0,
    ])
    if (has_llm and body_len > 400 and advisory_score >= 5) or advisory_score >= 6:
        base["quality_tier"] = "A"
    elif advisory_score >= 4 or (body_len > 220 and ticks and has_size):
        base["quality_tier"] = "B"
    elif body_len > 160 and (base.get("next_action") or ticks or has_size):
        base["quality_tier"] = "B"
    else:
        base["quality_tier"] = "C"

    # Ensure takeaways exist and are actionable
    takes = list(base.get("key_takeaways") or [])
    takes = [t for t in takes if t and "standing watch" not in str(t).lower()]
    if base.get("next_action") and isinstance(base["next_action"], dict):
        lab = base["next_action"].get("label")
        if lab and not any(lab in str(t) for t in takes):
            takes = [f"Next: {lab}"] + takes
    if size and not any("sizing" in str(t).lower() or "%" in str(t) for t in takes):
        takes = takes[:4] + [f"Sizing: {str(size)[:180]}"]
    if not takes and impl:
        takes = [impl[:200]]
    base["key_takeaways"] = takes[:5]
    base["reading_minutes"] = max(1, min(6, body_len // 450 or 1))
    return base


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
    base["sizing_reason"] = adv.get("sizing_reason")
    base["risk_caveat"] = adv.get("risk_caveat")
    base["portfolio_snapshot"] = adv.get("portfolio_snapshot")
    base["card_template"] = adv.get("card_template")
    base["actions"] = adv.get("actions") or []
    base["quality_gate"] = adv.get("quality_gate")
    # Prefer portfolio-aware next_action unless topic_monitor needs ingest first
    if research_type == "topic_monitor":
        base["next_action"] = base.get("next_action") or adv.get("next_action")
    else:
        base["next_action"] = adv.get("next_action") or base.get("next_action")
    ticks = [
        t for t in (base.get("ticker_recommendations") or [])
        if t.get("symbol") and t.get("role") in (
            "add_candidate", "trim_candidate", "protect", "hold_review", "watchlist",
        )
    ]
    if ticks and isinstance(base.get("key_takeaways"), list):
        line = "Tickers: " + ", ".join(
            f"{t.get('symbol')} ({t.get('role')}"
            + (f"/conv {t.get('conviction_tier')}" if t.get("conviction_tier") else "")
            + ")"
            for t in ticks[:4]
        )
        base["key_takeaways"] = [x for x in base["key_takeaways"] if not str(x).startswith("Tickers:")]
        base["key_takeaways"] = [line] + list(base["key_takeaways"])[:4]
        # Surface best add's why_selected
        for t in ticks:
            if t.get("why_selected") and t.get("role") in ("add_candidate", "watchlist", "hold_review"):
                why_line = f"Why {t.get('symbol')}: {t.get('why_selected')}"
                if not any(str(x).startswith(f"Why {t.get('symbol')}") for x in base["key_takeaways"]):
                    base["key_takeaways"] = list(base["key_takeaways"])[:4] + [why_line]
                break
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
        out = _attach_advisory(
            out, title=title, summary=summary, thesis=thesis, cats=cats,
            symbol=symbol, is_held=is_held, research_type=research_type, portfolio=portfolio,
        )
        return _polish_narrative_depth(out, title=title, cats=cats)

    body_src = " ".join(x for x in [summary, thesis] if x)
    # Topic monitors: category-aware desk brief (avoid empty metadata stubs)
    if research_type == "topic_monitor":
        ctx = summary or ""
        ctx = re.sub(r"^Topic monitor[^.]*\.\s*", "", ctx, flags=re.I).strip()
        primary = (cats[0] if cats else "") or "general"
        lane = primary.replace("_", " ")
        if primary == "retirement_tax":
            body_src = (
                f"{title} is an active retirement/tax watch on the {lane} pillar. "
                f"Track IRMAA lookback, MAGI room, and conversion calendar against live portfolio weights. "
                f"{ctx + ' ' if ctx else ''}"
                f"When sources refresh, Hermes upgrades this monitor into a cited brief; until then, "
                f"use the action strip for the next operator step (not a new equity ticket)."
            )
        elif primary == "dividend_income":
            body_src = (
                f"{title} watches the income sleeve: yield quality, covered-call/NAV risk, and IRMAA impact of "
                f"taxable distributions. {ctx + ' ' if ctx else ''}"
                f"Prefer quality (SCHD) over stacking high-yield traps; size against current sleeve weight."
            )
        elif primary == "risk_regime":
            body_src = (
                f"{title} is a risk/protection watch — stop hygiene and portfolio heat outrank alpha until clean. "
                f"{ctx + ' ' if ctx else ''}"
                f"Review largest weights first via Stop Management (Replace mode)."
            )
        else:
            body_src = (
                f"{title} is an active {lane} watch on the Research Intelligence desk. "
                f"{ctx + ' ' if ctx else ''}"
                f"On the next ingest cycle, Hermes will attach sources and thesis; until then, "
                f"map implications to holdings using the portfolio-aware action strip below."
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

    bull, bear = _bull_bear(body_src, cats, sentiment, portfolio=portfolio)
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
    out = _attach_advisory(
        out, title=title, summary=summary, thesis=thesis, cats=cats,
        symbol=symbol, is_held=is_held, research_type=research_type, portfolio=portfolio,
    )
    return _polish_narrative_depth(out, title=title, cats=cats)
