"""Research Intelligence aggregator v2 — taxonomy, freshness, archive, feedback.

Builds a professional intelligence-dashboard payload from Hermes, topic_monitor,
user_research_topics, and holdings. Classification is rule-based (cheap, stable).
Freshness tiers + archive policy from config/research_intelligence_freshness.json.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = PROJECT_ROOT / "config" / "research_intelligence_taxonomy.json"
FRESHNESS_PATH = PROJECT_ROOT / "config" / "research_intelligence_freshness.json"
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"

# Patterns → category ids (order matters: first match wins for primary)
_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    # Note: never bare "roth" (matches "Roth Capital"); never roth.?ira (account codes).
    ("retirement_tax", re.compile(
        r"roth\s+(?:ira|conversion|ladder|account|plans?)|conversion\s+ladder|"
        r"taxable\s+conversion|golden\s+window|"
        r"(?<![_\w])rmd(?![_\w])|required\s+minimum|\birmaa\b|\bmedicaid\b|"
        r"estate\s+plan|estate\s+tax|\bprobate\b|"
        r"\bssdi\b|backdoor\s+roth|qualified\s+charitable|\bqcd\b|life\s+estate|"
        r"asset\s+protection|spend.?down|look.?back\s+period|\bmedigap\b|medicare\s+part\s+[bd]\b|"
        r"retirement\s+tax|retirement\s+income|tax.?efficient(?:\s+retirement)?|"
        r"income\s+drawdown|withdrawal\s+strateg|tax.?efficient\s+withdrawal|"
        r"social\s+security\s+claim|tax\s+bracket\s+room|conversion\s+pacing|\bmapt\b|"
        r"drawdown\s+plan(?:ning)?",
        re.I,
    )),
    ("dividend_income", re.compile(
        r"dividend|covered.?call|\bcef\b|\bbdc\b|income sleeve|aristocrat|"
        r"monthly income|jepi|jepq|schd|pflt|cswc|distribution yield",
        re.I,
    )),
    ("macro_geo", re.compile(
        r"\bfed\b|fomc|inflation|cpi|pce|treasury|yield curve|geopolitic|"
        r"tariff|oil shock|\bvix\b|regime|liquidity|rates? hike|recession|gdp|\bfred\b",
        re.I,
    )),
    ("sector_thematic", re.compile(
        r"sector|rotation|defense|aerospace|semiconductor|ai\s*chip|data\s*center|datacenter|"
        r"staples|healthcare|utilities|energy sector|materials|consumer defensive|"
        r"build-?out|infrastructure",
        re.I,
    )),
    # Do NOT bare-match "drawdown" — that tags "retirement income drawdown" as risk.
    # Do NOT bare-match "protection" — MAPT "asset protection" is retirement.
    ("risk_regime", re.compile(
        r"\bstop\b|stop.?health|stop.?curation|protection.?advisory|"
        r"portfolio heat|risk.?on|risk.?off|"
        r"(?:portfolio|max|peak|account)\s+drawdown|"
        r"drawdown\s+(?:risk|guard|limit|protection)|"
        r"\bvolatility\s+(?:tier|regime|spike)\b",
        re.I,
    )),
    ("catalyst_event", re.compile(
        r"catalyst|earnings|news_momentum|breakout|event.?driven|form.?4",
        re.I,
    )),
    # Avoid "growth compounder" / "core compounder" ticker jargon (no bare "compound")
    ("compounding_wealth", re.compile(
        r"\bcompounding\b|\bcompound interest\b|long.?term wealth|asset allocation|"
        r"bucket strateg|drawdown plan|wealth framework|multi.?year (wealth|plan|horizon)|"
        r"wealth building|permanent portfolio|financial independence|\bfire\b strategy",
        re.I,
    )),
    ("academic_pro", re.compile(
        r"academic|paper\b|journal|white.?paper|pro.?analyst|transcript|"
        r"ph\.?d|sven carlin|research summary",
        re.I,
    )),
]

_TYPE_TO_CAT = {
    "topic_research": None,
    "momentum_catalyst": "catalyst_event",
    "protection_advisory": "risk_regime",
    "stop_curation": "risk_regime",
    "stop_health": "risk_regime",
    "ticker_thesis_challenge": "company_ticker",
    "options_desk": "company_ticker",
    "youtube_discovery": "academic_pro",
    "research_backlog": "company_ticker",
}

_SENT_BULL = re.compile(
    r"\b(bullish|upgrade|outperform|beat|strong buy|accumulate|tailwind|accelerat)\b", re.I
)
_SENT_BEAR = re.compile(
    r"\b(bearish|downgrade|underperform|miss|cut target|headwind|weaken|risk.?off)\b", re.I
)
_Q_SPLIT = re.compile(r"(?:^|\n)\s*(?:\d+[\.\)]\s*|[-•]\s*)?(.+\?)\s*$", re.M)
_GAP_RX = re.compile(
    r"(?:data gap|unknown|unclear|need(?:s)? (?:more |to )?(?:data|confirm|verify)|"
    r"insufficient|limited (?:direct )?information|zero details|not (?:enough|available))",
    re.I,
)


def load_taxonomy() -> dict[str, Any]:
    if TAXONOMY_PATH.exists():
        return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return {"categories": [], "version": "0"}


def load_freshness_policy() -> dict[str, Any]:
    if FRESHNESS_PATH.exists():
        return json.loads(FRESHNESS_PATH.read_text(encoding="utf-8"))
    return {
        "tiers": {
            "live": {"max_hours": 2},
            "fresh": {"max_hours": 24},
            "aging": {"max_hours": 72},
            "stale": {"max_hours": 336},
            "archive": {"max_hours": None},
        },
        "refresh_cadence_hours": {"_default": 48},
        "archive": {"include_archived_default": False},
    }


def classify_text(*parts: str | None, research_type: str | None = None) -> list[str]:
    """Return ordered list of category ids (primary first)."""
    blob = " ".join(p for p in parts if p)
    cats: list[str] = []
    mapped = _TYPE_TO_CAT.get(research_type or "")
    if mapped:
        cats.append(mapped)
    _risk_types = {"protection_advisory", "stop_curation", "stop_health"}
    for cid, rx in _CATEGORY_RULES:
        if cid == "retirement_tax" and (research_type or "") in _risk_types:
            continue
        if rx.search(blob) and cid not in cats:
            cats.append(cid)
    if not cats:
        cats.append("company_ticker" if (parts and parts[0]) else "sector_thematic")
    return cats[:4]


def classify_primary_secondary(
    title: str | None,
    *body_parts: str | None,
    research_type: str | None = None,
) -> list[str]:
    """Title/topic drives primary category; body may only add secondary tags.

    Prevents personal_context (e.g. IRMAA note on a dividend monitor) from
    re-labeling 'Top Yield & Dividend Stocks' as retirement_tax.
    """
    title_cats = classify_text(title, research_type=research_type)
    body_cats = classify_text(*body_parts) if any(body_parts) else []
    # If title only got a weak fallback but body is clearly thematic, allow
    # body primary when title had no strong keyword hit beyond type-map.
    title_blob = title or ""
    title_had_keyword = any(
        rx.search(title_blob) for _, rx in _CATEGORY_RULES
    )
    mapped = _TYPE_TO_CAT.get(research_type or "")
    if mapped and not title_had_keyword and body_cats:
        # Keep type-map primary (e.g. stop_health → risk_regime)
        cats = [mapped] + [c for c in body_cats if c != mapped]
        return cats[:4]
    if not title_had_keyword and not mapped and body_cats:
        # Pure fallback title ("Industry: X") — prefer first body theme if any
        # but keep company_ticker if title looks like industry/ticker research
        if re.search(r"industry:|autonomous thesis|news_momentum:", title_blob, re.I):
            primary = title_cats[0] if title_cats else "company_ticker"
            cats = [primary] + [c for c in body_cats if c != primary]
            return cats[:4]
    cats = list(title_cats)
    for c in body_cats:
        if c not in cats:
            cats.append(c)
    return cats[:4]


def holdings_symbols() -> set[str]:
    if not HOLDINGS_PATH.exists():
        return set()
    try:
        doc = json.loads(HOLDINGS_PATH.read_text())
        return {
            str(h.get("symbol") or "").upper()
            for h in (doc.get("holdings") or [])
            if h.get("symbol") and not h.get("is_cash")
        }
    except Exception:
        return set()


def _age_hours(ts) -> float | None:
    if ts is None:
        return None
    try:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return None


def _priority_from(cats: list[str], conf: float | None, age_h: float | None, held: bool) -> str:
    if "retirement_tax" in cats:
        return "high"
    if held and ("dividend_income" in cats or "company_ticker" in cats):
        return "high"
    if conf is not None and conf >= 0.85 and (age_h is None or age_h < 72):
        return "high"
    if age_h is not None and age_h > 14 * 24:
        return "low"
    return "normal"


def freshness_tier(age_h: float | None, *, is_archived: bool = False, policy: dict | None = None) -> str:
    if is_archived:
        return "archive"
    pol = policy or load_freshness_policy()
    tiers = pol.get("tiers") or {}
    if age_h is None:
        return "aging"
    for name in ("live", "fresh", "aging", "stale"):
        t = tiers.get(name) or {}
        mx = t.get("max_hours")
        if mx is not None and age_h <= float(mx):
            return name
    return "archive"


def freshness_label(age_h: float | None, tier: str) -> str:
    if tier == "archive":
        if age_h is None:
            return "Archived — historical"
        if age_h < 24:
            return f"Archived — {int(age_h)}h ago"
        return f"Archived — {int(age_h // 24)}d ago"
    if age_h is None:
        return "Unknown age"
    if age_h < 1:
        return f"Updated {max(1, int(age_h * 60))}m ago"
    if age_h < 24:
        return f"Updated {int(round(age_h))}h ago"
    if age_h < 48:
        return "Last refreshed ~1d ago"
    return f"Last refreshed {int(age_h // 24)}d ago"


def refresh_cadence_hours(cats: list[str], *, held: bool = False, priority: str = "normal",
                          policy: dict | None = None) -> int:
    pol = policy or load_freshness_policy()
    cad = pol.get("refresh_cadence_hours") or {}
    if held:
        return int(cad.get("_holdings_linked") or cad.get("_default") or 12)
    if priority == "high":
        return int(cad.get("_high_priority") or 12)
    best = None
    for c in cats:
        if c in cad:
            v = int(cad[c])
            best = v if best is None else min(best, v)
    return int(best if best is not None else cad.get("_default") or 48)


def needs_refresh(age_h: float | None, cadence_h: int) -> bool:
    if age_h is None:
        return True
    return age_h > cadence_h


def _sentiment(text: str) -> str:
    if not text:
        return "neutral"
    b, r = len(_SENT_BULL.findall(text)), len(_SENT_BEAR.findall(text))
    if b > r and b > 0:
        return "bullish"
    if r > b and r > 0:
        return "bearish"
    return "neutral"


def _extract_questions(*parts: str | None) -> list[str]:
    blob = "\n".join(p for p in parts if p)
    found = [m.group(1).strip() for m in _Q_SPLIT.finditer(blob) if m.group(1)]
    # de-dupe preserve order
    out: list[str] = []
    for q in found:
        if q not in out and len(q) > 12:
            out.append(q[:200])
    return out[:5]


def _extract_gaps(*parts: str | None) -> list[str]:
    blob = "\n".join(p for p in parts if p) or ""
    gaps: list[str] = []
    for line in blob.splitlines():
        if _GAP_RX.search(line) and line.strip() not in gaps:
            gaps.append(line.strip()[:200])
    return gaps[:4]


def _parse_jsonish(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return None
    return val


def _sources_from_row(r: dict) -> list[dict]:
    sources: list[dict] = []
    ev = _parse_jsonish(r.get("evidence_json")) or {}
    if isinstance(ev, dict):
        for g in (ev.get("grounded_on") or [])[:6]:
            if isinstance(g, dict):
                sources.append({
                    "title": g.get("title"), "url": g.get("url"), "source": g.get("source"),
                })
        for k in ("key_questions", "questions", "open_questions"):
            # handled elsewhere
            pass
    su = _parse_jsonish(r.get("source_urls_json")) or []
    if isinstance(su, list):
        for u in su[:4]:
            if isinstance(u, str):
                sources.append({"url": u})
            elif isinstance(u, dict):
                sources.append(u)
    return sources[:8]


def _evidence_questions(ev: Any) -> list[str]:
    ev = _parse_jsonish(ev) or {}
    if not isinstance(ev, dict):
        return []
    out: list[str] = []
    for k in ("key_questions", "questions", "open_questions", "data_needed"):
        v = ev.get(k)
        if isinstance(v, list):
            for x in v:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip()[:200])
                elif isinstance(x, dict) and x.get("q"):
                    out.append(str(x["q"])[:200])
        elif isinstance(v, str) and v.strip():
            out.append(v.strip()[:200])
    return out[:5]


def _load_feedback_map(db_query) -> dict[str, dict]:
    try:
        rows = db_query("""
            SELECT item_id, starred, vote, note, updated_at
            FROM research_intelligence_feedback
        """) or []
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        iid = r.get("item_id")
        if iid:
            out[str(iid)] = {
                "starred": bool(r.get("starred")),
                "vote": r.get("vote"),
                "note": r.get("note"),
                "feedback_updated_at": (
                    r.get("updated_at").isoformat()
                    if hasattr(r.get("updated_at"), "isoformat") else r.get("updated_at")
                ),
            }
    return out


def _item_base(
    *,
    id_: str,
    source_system: str,
    source_table: str,
    source_id: Any,
    title: str,
    summary: str,
    thesis: str | None,
    symbol: str | None,
    cats: list[str],
    conf: float | None,
    age: float | None,
    created_at: Any,
    model: str | None,
    research_type: str | None,
    status: str | None,
    is_held: bool,
    sources: list[dict],
    actionability: str,
    policy: dict,
    feedback: dict | None = None,
    extra: dict | None = None,
    evidence_json: Any = None,
) -> dict[str, Any]:
    from lib.research_intelligence_narrative import enrich_narrative

    is_arch = (status or "").lower() == "archived"
    tier = freshness_tier(age, is_archived=is_arch, policy=policy)
    pri = _priority_from(cats, conf, age, is_held)
    cadence = refresh_cadence_hours(cats, held=is_held, priority=pri, policy=policy)
    blob = f"{title} {summary or ''} {thesis or ''}"
    key_q = _extract_questions(summary, thesis)
    gaps = _extract_gaps(summary, thesis)
    fb = feedback or {}
    sent = _sentiment(blob)
    need_r = needs_refresh(age, cadence) and not is_arch
    narrative = enrich_narrative(
        title=title,
        summary=summary or "",
        thesis=thesis,
        cats=cats,
        symbol=symbol,
        is_held=is_held,
        sentiment=sent,
        key_questions=key_q,
        data_gaps=gaps,
        actionability=actionability,
        needs_refresh=need_r,
        research_type=research_type,
        evidence_json=evidence_json,
        source_system=source_system,
    )
    nxt = narrative.get("next_action") or {}
    item: dict[str, Any] = {
        "id": id_,
        "source_system": source_system,
        "source_table": source_table,
        "source_id": source_id,
        "title": title,
        "summary": (summary or "")[:1200],
        "thesis": ((thesis or "")[:800] or None),
        "symbol": symbol,
        "categories": cats,
        "primary_category": cats[0] if cats else "company_ticker",
        "priority": pri,
        "confidence": conf,
        "freshness_hours": round(age, 1) if age is not None else None,
        "freshness_tier": tier,
        "freshness_label": freshness_label(age, tier),
        "refresh_cadence_hours": cadence,
        "needs_refresh": need_r,
        "is_archived": is_arch,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "model": model,
        "research_type": research_type,
        "status": status,
        "is_holdings": is_held,
        "sources": sources[:8],
        "source_count": len(sources),
        "actionability": actionability,
        "sentiment": sent,
        "key_questions": key_q,
        "data_gaps": gaps,
        "starred": bool(fb.get("starred")),
        "vote": fb.get("vote"),
        "operator_note": fb.get("note"),
        # Article-style narrative (Seeking Alpha / The Information tone)
        "lede": narrative.get("lede"),
        "executive_summary": narrative.get("executive_summary") or [],
        "key_takeaways": narrative.get("key_takeaways") or [],
        "bull_case": narrative.get("bull_case"),
        "bear_case": narrative.get("bear_case"),
        "why_it_matters": narrative.get("why_it_matters"),
        "next_action": nxt,
        "next_action_label": nxt.get("label"),
        "next_action_detail": nxt.get("detail"),
        "narrative_source": narrative.get("narrative_source"),
        "reading_minutes": narrative.get("reading_minutes") or 1,
    }
    if extra:
        # Merge key_questions carefully
        if extra.get("key_questions") and item.get("key_questions"):
            item["key_questions"] = list(dict.fromkeys(
                list(extra.get("key_questions") or []) + list(item["key_questions"])
            ))[:5]
            extra = {k: v for k, v in extra.items() if k != "key_questions"}
        item.update(extra)
    return item


def build_feed(
    *,
    db_query,
    category: str | None = None,
    q: str | None = None,
    priority: str | None = None,
    symbol: str | None = None,
    limit: int = 80,
    holdings_only: bool = False,
    include_archived: bool | None = None,
    freshness: str | None = None,
    starred_only: bool = False,
    sentiment: str | None = None,
    source_system: str | None = None,
    primary_only: bool = True,
) -> dict[str, Any]:
    """Unified research intelligence feed for the dashboard (v2).

    Taxonomy chips filter by primary_category when primary_only=True (default).
    """
    tax = load_taxonomy()
    policy = load_freshness_policy()
    held = holdings_symbols()
    limit = max(10, min(int(limit or 80), 200))
    if include_archived is None:
        include_archived = bool((policy.get("archive") or {}).get("include_archived_default"))

    fb_map = _load_feedback_map(db_query)
    items: list[dict[str, Any]] = []

    def _cat_ok(cats: list[str]) -> bool:
        if not category:
            return True
        if not cats:
            return False
        if primary_only:
            return cats[0] == category
        return category in cats

    # ── Hermes research (active + optional archive) ────────────────────
    status_clause = "WHERE status IS NULL OR status NOT IN ('rejected','discarded')"
    if not include_archived:
        status_clause += " AND (status IS NULL OR status <> 'archived')"
    rows = db_query(f"""
        SELECT id, topic, summary, thesis, symbol, research_type, confidence_score,
               quality_score, status, model_used, source, created_at, freshness_date,
               evidence_json, source_urls_json, tags, category_content, category_sector,
               updated_at
        FROM hermes_research_intelligence
        {status_clause}
        ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST
        LIMIT 600
    """) or []

    for r in rows:
        cats = classify_primary_secondary(
            r.get("topic"), r.get("summary"), r.get("thesis"),
            research_type=r.get("research_type"),
        )
        sym = (r.get("symbol") or "").upper() or None
        if not sym and r.get("topic"):
            m = re.search(r":\s*([A-Z]{1,5})\b", str(r.get("topic") or ""))
            if m:
                sym = m.group(1)
        is_held = bool(sym and sym in held)
        primary = cats[0] if cats else ""
        # Early filters that define the universe (not taxonomy chips / freshness chips)
        if holdings_only and not is_held and primary not in ("retirement_tax", "macro_geo"):
            continue
        if symbol and sym != symbol.upper():
            continue
        blob = f"{r.get('topic') or ''} {r.get('summary') or ''} {r.get('thesis') or ''}"
        if q and q.lower() not in blob.lower() and (not sym or q.upper() not in sym):
            continue
        conf = None
        try:
            conf = float(r.get("confidence_score")) if r.get("confidence_score") is not None else None
        except (TypeError, ValueError):
            pass
        age = _age_hours(r.get("updated_at") or r.get("created_at") or r.get("freshness_date"))
        sources = _sources_from_row(r)
        ev_q = _evidence_questions(r.get("evidence_json"))
        iid = f"hermes:{r.get('id')}"
        act = (
            "Review Roth/tax plan impact" if primary == "retirement_tax" else
            "Check dividend/income exposure" if primary == "dividend_income" and is_held else
            "Map to sector allocation" if primary in ("sector_thematic", "macro_geo") else
            "Update thesis / stops" if is_held else
            "Advisory — watchlist or thematic"
        )
        item = _item_base(
            id_=iid,
            source_system="hermes",
            source_table="hermes_research_intelligence",
            source_id=r.get("id"),
            title=r.get("topic") or "Research finding",
            summary=r.get("summary") or "",
            thesis=r.get("thesis"),
            symbol=sym,
            cats=cats,
            conf=conf,
            age=age,
            created_at=r.get("updated_at") or r.get("created_at"),
            model=r.get("model_used"),
            research_type=r.get("research_type"),
            status=r.get("status"),
            is_held=is_held,
            sources=sources,
            actionability=act,
            policy=policy,
            feedback=fb_map.get(iid),
            evidence_json=r.get("evidence_json"),
            extra={"key_questions": ev_q or []},
        )
        items.append(item)

    # ── Auto-research / user topics ────────────────────────────────────
    ut = db_query("""
        SELECT id, topic, latest_findings, priority, research_count,
               status, source, updated_at, created_at, original_message,
               strategy_type, last_researched_at
        FROM user_research_topics
        WHERE status = 'active' OR status IS NULL
        ORDER BY updated_at DESC NULLS LAST
        LIMIT 100
    """) or []
    for r in ut:
        # Title primary; findings/body secondary only
        cats = classify_primary_secondary(
            r.get("topic"),
            r.get("latest_findings"), r.get("original_message"), r.get("strategy_type"),
        )
        if (r.get("source") or "").startswith("auto_research") and cats and cats[0] != "company_ticker":
            # Ticker-style topics keep company primary when topic is a symbol brief
            t = str(r.get("topic") or "").upper().strip()
            if re.fullmatch(r"[A-Z]{1,5}", t) or re.search(r"\b[A-Z]{1,5}\b", t or ""):
                cats = ["company_ticker"] + [c for c in cats if c != "company_ticker"]
        # Infer ticker from topic text (no symbol column on user_research_topics)
        sym = None
        if r.get("topic"):
            t = str(r.get("topic")).upper().strip()
            if re.fullmatch(r"[A-Z]{1,5}", t):
                sym = t
            else:
                m = re.search(r"\b([A-Z]{1,5})\b", t)
                if m and m.group(1) in held:
                    sym = m.group(1)
        is_held = bool(sym and sym in held)
        if symbol and (not sym or sym != symbol.upper()):
            continue
        blob = f"{r.get('topic')} {r.get('latest_findings')} {r.get('original_message')}"
        if q and q.lower() not in blob.lower():
            continue
        age = _age_hours(r.get("last_researched_at") or r.get("updated_at") or r.get("created_at"))
        iid = f"urt:{r.get('id')}"
        primary = cats[0] if cats else ""
        act = (
            "Review Roth / tax plan" if primary == "retirement_tax" else
            "Check income sleeve" if primary == "dividend_income" else
            "Open full brief / manage topic"
        )
        items.append(_item_base(
            id_=iid,
            source_system="auto_research" if (r.get("source") or "").startswith("auto_research") else "operator_topic",
            source_table="user_research_topics",
            source_id=r.get("id"),
            title=r.get("topic") or (sym or "Topic"),
            summary=r.get("latest_findings") or r.get("original_message") or "",
            thesis=None,
            symbol=sym,
            cats=cats,
            conf=None,
            age=age,
            created_at=r.get("last_researched_at") or r.get("updated_at") or r.get("created_at"),
            model=None,
            research_type="auto_research" if (r.get("source") or "").startswith("auto_research") else "user_topic",
            status=r.get("status"),
            is_held=is_held,
            sources=[],
            actionability=act,
            policy=policy,
            feedback=fb_map.get(iid),
            extra={"research_count": r.get("research_count")},
        ))

    # ── Topic monitor registry ─────────────────────────────────────────
    mon = db_query("""
        SELECT topic_id, display_name, priority, enabled, last_searched, last_found_count,
               agent_owner, owner, strategy_tags, max_age_days, search_queries, personal_context
        FROM topic_monitor
        WHERE enabled IS TRUE OR enabled IS NULL
        ORDER BY priority ASC NULLS LAST, last_searched DESC NULLS LAST
        LIMIT 150
    """) or []
    for r in mon:
        # Title + topic_id + strategy_tags for primary; personal_context is SECONDARY only
        # (operator notes often mention IRMAA/SSDI even on dividend/sector monitors)
        cats = classify_primary_secondary(
            f"{r.get('display_name') or ''} {r.get('topic_id') or ''}",
            " ".join(r.get("strategy_tags") or []),
            r.get("personal_context"),
        )
        blob = f"{r.get('display_name')} {r.get('topic_id')} {r.get('personal_context') or ''}"
        if q and q.lower() not in blob.lower():
            continue
        if symbol:
            continue
        age = _age_hours(r.get("last_searched"))
        iid = f"tm:{r.get('topic_id')}"
        max_age = r.get("max_age_days") or 30
        cadence = int(max_age) * 24
        primary = cats[0] if cats else ""
        pri = "high" if (r.get("priority") or 9) <= 2 or primary == "retirement_tax" else "normal"
        item = _item_base(
            id_=iid,
            source_system="topic_monitor",
            source_table="topic_monitor",
            source_id=r.get("topic_id"),
            title=r.get("display_name") or r.get("topic_id"),
            summary=(
                f"Topic monitor · last found {r.get('last_found_count') or 0} items · "
                f"owner {r.get('agent_owner') or r.get('owner') or '—'} · "
                f"max age {max_age}d"
                + (f" · {(r.get('personal_context') or '')[:180]}" if r.get("personal_context") else "")
            ),
            thesis=None,
            symbol=None,
            cats=cats,
            conf=None,
            age=age,
            created_at=r.get("last_searched"),
            model=None,
            research_type="topic_monitor",
            status="enabled" if r.get("enabled") else "paused",
            is_held=False,
            sources=[],
            actionability="Ingest via topic_ingestion · curate with topic_curator · Hermes bridge",
            policy=policy,
            feedback=fb_map.get(iid),
            extra={
                "refresh_cadence_hours": cadence,
                "needs_refresh": needs_refresh(age, cadence),
                "monitor_priority": r.get("priority"),
                "search_queries": (r.get("search_queries") or [])[:6]
                    if isinstance(r.get("search_queries"), list) else [],
            },
        )
        # Override priority for monitor rows
        item["priority"] = pri
        items.append(item)

    # Universe stats FIRST (before chip filters) so taxonomy counts never go blank
    # when user selects an empty category like compounding_wealth.
    cat_counts: dict[str, int] = {}
    cat_counts_any: dict[str, int] = {}
    tier_counts_all: dict[str, int] = {}
    for it in items:
        pc = it.get("primary_category") or (it.get("categories") or [None])[0]
        if pc:
            cat_counts[pc] = cat_counts.get(pc, 0) + 1
        for c in it.get("categories") or []:
            cat_counts_any[c] = cat_counts_any.get(c, 0) + 1
        t = it.get("freshness_tier") or "aging"
        tier_counts_all[t] = tier_counts_all.get(t, 0) + 1

    universe_n = len(items)

    # Chip filters (category / freshness / priority / star) applied AFTER counts
    filtered = list(items)
    if category:
        if primary_only:
            filtered = [i for i in filtered if i.get("primary_category") == category]
        else:
            filtered = [i for i in filtered if category in (i.get("categories") or [])]
    if freshness:
        filtered = [i for i in filtered if i.get("freshness_tier") == freshness]
    if starred_only:
        filtered = [i for i in filtered if i.get("starred")]
    if sentiment:
        filtered = [i for i in filtered if i.get("sentiment") == sentiment]
    if source_system:
        filtered = [i for i in filtered if i.get("source_system") == source_system]
    if priority:
        filtered = [i for i in filtered if i.get("priority") == priority]

    # Sort: focus pillars → priority → holdings → freshness
    pri_rank = {"high": 0, "normal": 1, "low": 2}
    tier_rank = {"live": 0, "fresh": 1, "aging": 2, "stale": 3, "archive": 4}
    _FOCUS = ("retirement_tax", "dividend_income", "macro_geo", "sector_thematic")

    def _focus_boost(it: dict) -> int:
        pc = it.get("primary_category")
        if pc in _FOCUS:
            return _FOCUS.index(pc)
        cats = it.get("categories") or []
        for i, c in enumerate(_FOCUS):
            if c in cats:
                return 10 + i
        return 20

    _STOP_NOISE = {"stop_health", "stop_curation", "protection_advisory"}

    def _sk(it: dict) -> tuple:
        # Demote pure stop noise on the default desk so retirement/macro/intel surface first.
        # Still fully available under Risk category filter.
        noise = 1 if (it.get("research_type") or "") in _STOP_NOISE else 0
        return (
            0 if it.get("starred") else 1,
            noise,
            _focus_boost(it),
            pri_rank.get(it.get("priority") or "normal", 1),
            tier_rank.get(it.get("freshness_tier") or "aging", 2),
            0 if it.get("is_holdings") else 1,
            it.get("freshness_hours") if it.get("freshness_hours") is not None else 9999,
        )

    filtered.sort(key=_sk)

    def _lane(pred, n: int = 16) -> list[dict[str, Any]]:
        # Lanes from full universe (not chip-filtered) so Retirement desk still works
        return [i for i in items if pred(i)][:n]

    priority_lanes = {
        "retirement": _lane(lambda i: i.get("primary_category") == "retirement_tax"),
        "dividends": _lane(lambda i: i.get("primary_category") == "dividend_income"),
        "macro_sector": _lane(lambda i: i.get("primary_category") in (
            "macro_geo", "sector_thematic"
        )),
    }

    page = filtered[:limit]
    tier_counts_view: dict[str, int] = {}
    for it in filtered:
        t = it.get("freshness_tier") or "aging"
        tier_counts_view[t] = tier_counts_view.get(t, 0) + 1

    high_n = sum(1 for i in page if i.get("priority") == "high")
    held_n = sum(1 for i in page if i.get("is_holdings"))
    refresh_n = sum(1 for i in page if i.get("needs_refresh"))
    arch_n = sum(1 for i in page if i.get("is_archived"))
    star_n = sum(1 for i in page if i.get("starred"))

    return {
        "ok": True,
        "version": "2.1.3",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "taxonomy": tax,
        "freshness_policy": {
            "tiers": policy.get("tiers"),
            "archive": policy.get("archive"),
            "slo": policy.get("slo"),
        },
        "filters": {
            "category": category,
            "primary_only": primary_only,
            "q": q,
            "priority": priority,
            "symbol": symbol,
            "holdings_only": holdings_only,
            "include_archived": include_archived,
            "freshness": freshness,
            "starred_only": starred_only,
            "sentiment": sentiment,
            "source_system": source_system,
            "limit": limit,
        },
        "stats": {
            "returned": len(page),
            "matched": len(filtered),
            "universe": universe_n,
            "high_priority": high_n,
            "holdings_linked": held_n,
            "needs_refresh": refresh_n,
            "archived_in_view": arch_n,
            "starred_in_view": star_n,
            # Always full-universe primary counts (chips stay populated)
            "by_category": cat_counts,
            "by_category_any": cat_counts_any,
            # Masthead freshness = universe (not empty when chip has 0 matches)
            "by_freshness": tier_counts_all,
            "by_freshness_filtered": tier_counts_view,
            "holdings_universe": sorted(held)[:40],
            "holdings_count": len(held),
            "lane_counts": {k: len(v) for k, v in priority_lanes.items()},
        },
        "items": page,
        "priority_lanes": priority_lanes,
        "note": (
            "Research Intelligence v2.1.3 — income/retirement drawdown is retirement (not risk); "
            "stop noise demoted on default desk; chip counts = full universe. "
            "Filter Risk category to focus on stops/heat."
        ),
    }


def upsert_feedback(
    *,
    db_query,
    item_id: str,
    starred: bool | None = None,
    vote: int | None = None,
    note: str | None = None,
    source_system: str | None = None,
    source_table: str | None = None,
    source_id: str | None = None,
    categories: list[str] | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Insert or update operator feedback for an intelligence item."""
    if not item_id:
        return {"ok": False, "error": "item_id required"}
    # Load existing
    existing = db_query(
        "SELECT item_id, starred, vote, note FROM research_intelligence_feedback WHERE item_id=%s",
        (item_id,),
        fetch="one",
    )
    if existing is None and starred is None and vote is None and note is None:
        return {"ok": False, "error": "nothing to update"}

    cur_star = bool(existing.get("starred")) if existing else False
    cur_vote = existing.get("vote") if existing else None
    cur_note = existing.get("note") if existing else None
    if starred is not None:
        cur_star = bool(starred)
    if vote is not None:
        # allow 0 to clear
        cur_vote = None if vote == 0 else (1 if vote > 0 else -1)
    if note is not None:
        cur_note = note[:2000] if note else None

    cats = categories or []
    db_query(
        """
        INSERT INTO research_intelligence_feedback
            (item_id, source_system, source_table, source_id, starred, vote, note, categories, symbol, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (item_id) DO UPDATE SET
            starred = EXCLUDED.starred,
            vote = EXCLUDED.vote,
            note = EXCLUDED.note,
            source_system = COALESCE(EXCLUDED.source_system, research_intelligence_feedback.source_system),
            source_table = COALESCE(EXCLUDED.source_table, research_intelligence_feedback.source_table),
            source_id = COALESCE(EXCLUDED.source_id, research_intelligence_feedback.source_id),
            categories = CASE WHEN EXCLUDED.categories = '{}' THEN research_intelligence_feedback.categories
                              ELSE EXCLUDED.categories END,
            symbol = COALESCE(EXCLUDED.symbol, research_intelligence_feedback.symbol),
            updated_at = NOW()
        """,
        (item_id, source_system, source_table, str(source_id) if source_id is not None else None,
         cur_star, cur_vote, cur_note, cats, symbol),
        fetch=None,
    )
    return {
        "ok": True,
        "item_id": item_id,
        "starred": cur_star,
        "vote": cur_vote,
        "note": cur_note,
    }


def freshness_report(*, db_query) -> dict[str, Any]:
    """Category-level freshness SLO report for ops / dashboard strip."""
    policy = load_freshness_policy()
    slo = policy.get("slo") or {}
    feed = build_feed(db_query=db_query, limit=200, include_archived=False)
    by_cat: dict[str, dict] = {}
    for it in feed.get("items") or []:
        pc = it.get("primary_category") or "unknown"
        d = by_cat.setdefault(pc, {
            "count": 0, "needs_refresh": 0, "live": 0, "fresh": 0, "stale": 0,
            "avg_age_h": 0.0, "_ages": [],
        })
        d["count"] += 1
        if it.get("needs_refresh"):
            d["needs_refresh"] += 1
        t = it.get("freshness_tier") or "aging"
        if t in d:
            d[t] = d.get(t, 0) + 1
        if it.get("freshness_hours") is not None:
            d["_ages"].append(float(it["freshness_hours"]))
    for pc, d in by_cat.items():
        ages = d.pop("_ages", [])
        d["avg_age_h"] = round(sum(ages) / len(ages), 1) if ages else None
        d["freshest_h"] = round(min(ages), 1) if ages else None
        key = f"{pc}_max_stale_hours"
        limit_h = slo.get(key)
        d["slo_hours"] = limit_h
        d["slo_ok"] = True if limit_h is None or not ages else (min(ages) <= float(limit_h))

    mon = db_query("""
        SELECT topic_id, display_name, last_searched, max_age_days, priority, enabled
        FROM topic_monitor
        WHERE enabled IS TRUE OR enabled IS NULL
        ORDER BY priority ASC NULLS LAST
        LIMIT 80
    """) or []
    stale_topics = []
    for r in mon:
        age = _age_hours(r.get("last_searched"))
        max_h = (r.get("max_age_days") or 30) * 24
        if age is None or age > max_h:
            stale_topics.append({
                "topic_id": r.get("topic_id"),
                "display_name": r.get("display_name"),
                "age_hours": round(age, 1) if age is not None else None,
                "max_age_hours": max_h,
                "priority": r.get("priority"),
            })

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "by_category": by_cat,
        "stale_topics": stale_topics[:30],
        "stale_topic_count": len(stale_topics),
        "feed_stats": feed.get("stats"),
        "slo": slo,
    }
