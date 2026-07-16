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
        r"asset\s+protection|spend.?down|look.?back\s+period|\bmedigap\b|"
        r"medicare(?:\s+part\s+[bd])?|\birmaa\b|"
        r"retirement\s+tax|retirement\s+income|tax.?efficient(?:\s+retirement)?|"
        r"income\s+drawdown|withdrawal\s+strateg|tax.?efficient\s+withdrawal|"
        r"social\s+security(?:\s+claim)?|tax\s+bracket\s+room|conversion\s+pacing|\bmapt\b|"
        r"drawdown\s+plan(?:ning)?|medicare\s+eligib|medicare\s+premium|"
        r"roth\s+conversion|monitoring.*(?:medicare|irmaa|ssdi|roth)",
        re.I,
    )),
    ("dividend_income", re.compile(
        r"\bdividend\b|covered.?call|\bcef\b|\bbdc\b|income sleeve|aristocrat|"
        r"monthly income|\bjepi\b|\bjepq\b|\bschd\b|\bpflt\b|\bcswc\b|distribution yield|"
        r"high.?yield income",
        re.I,
    )),
    ("macro_geo", re.compile(
        r"\bfed\b|fomc|inflation|cpi|pce|treasury|yield curve|geopolitic|"
        r"tariff|oil shock|\bvix\b|regime|liquidity|rates? hike|recession|gdp|\bfred\b|"
        r"bond ladder|\btips\b|fixed.?income|\btreasur",
        re.I,
    )),
    ("sector_thematic", re.compile(
        r"sector|rotation|defense|aerospace|semiconductor|ai\s*chip|data\s*center|datacenter|"
        r"staples|healthcare|utilities|energy sector|materials|consumer defensive|"
        r"build-?out|infrastructure|industry:\s*",
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
        r"wealth building|permanent portfolio|financial independence|\bfire\b strategy|"
        r"wealth compound|long.?horizon (invest|plan|wealth)|dca\b|dollar.?cost|"
        r"reinvest(ment|ing)? dividends|core (growth )?compounder sleeve|"
        r"long.?term (ownership|holder|holding) framework",
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
    "exit_intelligence": "risk_regime",
    "ticker_thesis_challenge": "company_ticker",
    "options_desk": "company_ticker",
    "youtube_discovery": "academic_pro",
    "research_backlog": "company_ticker",
}

# Hard title patterns that must stay company_ticker (not dividend/sector bleed)
_FORCE_COMPANY_TITLE = re.compile(
    r"autonomous thesis challenge|options desk|options:\s*|ticker thesis|"
    r"^auto-research:|news_momentum:\s*[A-Z]{1,5}\b",
    re.I,
)

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


# Stop-signal research types — real desk items even when the body is short
_STOP_NOISE_TYPES = {"stop_health", "stop_curation", "protection_advisory"}

# Lane tabs = primary-category groupings. Used both to FILTER the feed (lane= param)
# and to build the preview arrays; keep the two in sync via this single map.
LANE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "retirement": ("retirement_tax",),
    "dividends": ("dividend_income",),
    "macro_sector": ("macro_geo", "sector_thematic"),
}


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
    """Title drives primary when it has keywords; otherwise body may set primary.

    Prevents IRMAA notes on dividend monitors from overriding a clear title,
    while allowing weak titles ('Monitoring tools…') with strong retirement
    body text to land in retirement_tax — not company_ticker noise.
    """
    title_blob = title or ""
    title_cats = classify_text(title, research_type=research_type)
    body_cats = classify_text(*body_parts) if any(body_parts) else []
    title_had_keyword = any(rx.search(title_blob) for _, rx in _CATEGORY_RULES)
    mapped = _TYPE_TO_CAT.get(research_type or "")

    # Force company lane for options desk / thesis challenges (prevent dividend sleeve spam)
    if _FORCE_COMPANY_TITLE.search(title_blob) or mapped == "company_ticker" and (
        research_type in ("options_desk", "ticker_thesis_challenge")
    ):
        cats = ["company_ticker"] + [c for c in (title_cats + body_cats) if c != "company_ticker"]
        return cats[:4]

    # Hard type maps always win (stops, etc.)
    if mapped and mapped != "company_ticker":
        cats = [mapped] + [c for c in (title_cats + body_cats) if c != mapped]
        return cats[:4]

    if title_had_keyword:
        cats = list(title_cats)
        for c in body_cats:
            if c not in cats:
                cats.append(c)
        return cats[:4]

    # Weak title: prefer strong body primary (retirement/macro/sector/dividend)
    _strong = {
        "retirement_tax", "dividend_income", "macro_geo", "sector_thematic",
        "risk_regime", "catalyst_event", "compounding_wealth",
    }
    body_primary = next((c for c in body_cats if c in _strong), None)
    if body_primary:
        cats = [body_primary] + [c for c in body_cats + title_cats if c != body_primary]
        return cats[:4]

    if re.search(r"^industry:\s*", title_blob, re.I):
        return (["sector_thematic"] + [c for c in body_cats if c != "sector_thematic"])[:4]

    cats = list(title_cats) if title_cats else ["company_ticker"]
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
            SELECT item_id, starred, vote, note, hidden, updated_at
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
                "hidden": bool(r.get("hidden")),
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
    from lib.research_intelligence_portfolio import load_portfolio_context

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
    port = load_portfolio_context()
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
        portfolio=port,
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
        "hidden": bool(fb.get("hidden")),
        "feedback_updated_at": fb.get("feedback_updated_at"),
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
        "quality_tier": narrative.get("quality_tier") or "B",
        # Portfolio-aware advisory
        "investment_implications": narrative.get("investment_implications"),
        "ticker_recommendations": narrative.get("ticker_recommendations") or [],
        "sizing_guidance": narrative.get("sizing_guidance"),
        "sizing_reason": narrative.get("sizing_reason"),
        "risk_caveat": narrative.get("risk_caveat"),
        "portfolio_snapshot": narrative.get("portfolio_snapshot"),
        "card_template": narrative.get("card_template"),
        "actions": narrative.get("actions") or [],
        "quality_gate": narrative.get("quality_gate"),
        "related_themes": narrative.get("related_themes"),
        "stage_payload": narrative.get("stage_payload"),
        "funding_context": narrative.get("funding_context"),
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
    lane: str | None = None,
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

    def _norm_title(t: str | None) -> str:
        t = re.sub(r"\s+", " ", (t or "").lower()).strip()
        t = re.sub(r"[^a-z0-9 %$]+", "", t)
        return t[:96]

    # ── Stub partition (v3) ────────────────────────────────────────────
    # Registry echoes / un-run topics are QUEUED WORK, not research. They never
    # render as briefings, never reach featured/Tier A, and are counted separately.
    def _is_stub_item(it: dict) -> bool:
        rt = it.get("research_type") or ""
        if rt in _STOP_NOISE_TYPES:
            return False  # stop signals are real desk items, however short
        if rt == "topic_monitor" or it.get("source_system") == "topic_monitor":
            return True
        summ = re.sub(r"\s+", " ", (it.get("summary") or "")).strip()
        thes = it.get("thesis") or ""
        low = f"{summ} {thes}".lower()
        if "from the research topic registry" in low:
            return True
        body = f"{summ} {thes}".strip()
        if len(body) >= 200:
            return False
        # Thin body: stub when it is (near-)empty or just restates the title
        tn = _norm_title(it.get("title"))
        bn = _norm_title(body)
        if not bn:
            return True
        return bool(tn) and tn in bn and len(bn) <= max(2 * len(tn), 40)

    stub_items = [i for i in items if _is_stub_item(i)]
    items = [i for i in items if not _is_stub_item(i)]

    # Prefer real Hermes/LLM briefs over empty topic_monitor stubs; dedupe near-identical titles

    def _quality(it: dict) -> float:
        score = 0.0
        if it.get("narrative_source") == "stored_llm":
            score += 50
        rt = it.get("research_type") or ""
        ss = it.get("source_system") or ""
        if rt == "topic_monitor" or ss == "topic_monitor":
            score -= 45
        elif ss == "hermes":
            score += 25
        body = " ".join(it.get("executive_summary") or []) or (it.get("summary") or "")
        if len(body) > 280:
            score += 20
        elif len(body) > 120:
            score += 8
        # Boilerplate monitor stubs
        if "standing watch on the Research Intelligence desk" in body:
            score -= 60
        # Quality tier + portfolio-aware advisory surface mature briefs
        qt = (it.get("quality_tier") or "").upper()
        if qt == "A":
            score += 28
        elif qt == "B":
            score += 12
        elif qt == "C":
            score -= 8
        ticks = it.get("ticker_recommendations") or []
        if ticks:
            score += min(18, 4 * len(ticks))
        if it.get("sizing_guidance") and len(str(it.get("sizing_guidance") or "")) > 40:
            score += 10
        if it.get("bull_case") and it.get("bear_case"):
            score += 6
        sc = it.get("source_count") or len(it.get("sources") or [])
        score += min(12, float(sc) * 2)
        fh = it.get("freshness_hours")
        if fh is not None:
            score += max(0.0, 12.0 - float(fh) / 24.0)
        if it.get("starred"):
            score += 15
        return score

    deduped: list[dict[str, Any]] = []
    best_by_title: dict[str, dict[str, Any]] = {}
    for it in items:
        key = _norm_title(it.get("title"))
        if not key:
            deduped.append(it)
            continue
        prev = best_by_title.get(key)
        if prev is None or _quality(it) > _quality(prev):
            best_by_title[key] = it
    # preserve approximate recency order among winners
    seen = set()
    for it in items:
        key = _norm_title(it.get("title"))
        if not key:
            continue
        winner = best_by_title.get(key)
        if winner is None:
            continue
        wid = winner.get("id")
        if wid in seen:
            continue
        seen.add(wid)
        deduped.append(winner)
    items = deduped

    universe_n = len(items)

    # ONE corpus for every number on the page: counts are computed over the SAME
    # post-dedupe universe the desk renders (pre-chip-filter so chips never blank).
    # Counting pre-dedupe inflated sidebar/freshness counts vs the visible feed
    # (e.g. "248" vs 6 filtered — duplicate-titled stop_health rows).
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

    # Chip filters (lane / category / freshness / priority / star) applied AFTER counts.
    # Hidden items (v3.1 B2, operator curation) are excluded from every default
    # view; the footer count lets the UI reveal them on demand.
    hidden_items = [i for i in items if i.get("hidden")]
    filtered = [i for i in items if not i.get("hidden")]
    if lane and lane in LANE_CATEGORIES:
        _lane_cats = LANE_CATEGORIES[lane]
        filtered = [i for i in filtered if i.get("primary_category") in _lane_cats]
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

    _STOP_NOISE = _STOP_NOISE_TYPES

    def _sk(it: dict) -> tuple:
        # Demote stop noise + empty topic_monitor stubs so LLM/Hermes intel surfaces first.
        # Starring a monitor stub must NOT outrank real Hermes/LLM briefs.
        noise = 1 if (it.get("research_type") or "") in _STOP_NOISE else 0
        stub = 1 if (it.get("research_type") == "topic_monitor" or (
            "standing watch on the Research Intelligence desk" in (
                (it.get("summary") or "") + " ".join(it.get("executive_summary") or [])
            )
        )) else 0
        starred_boost = 0 if (it.get("starred") and not stub) else 1
        # v3.1 (B3): ▼ mirrors the star, opposite sign — demoted, never removed
        downvoted = 1 if (it.get("vote") or 0) < 0 else 0
        q = -_quality(it)
        return (
            stub,
            starred_boost,
            downvoted,
            noise,
            _focus_boost(it),
            q,
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
        name: _lane(lambda i, cs=cats: i.get("primary_category") in cs)
        for name, cats in LANE_CATEGORIES.items()
    }
    # Full-universe lane totals (preview arrays above are capped at 16)
    lane_counts_full = {
        name: sum(1 for i in items if i.get("primary_category") in cats)
        for name, cats in LANE_CATEGORIES.items()
    }

    # Queued-research rail: compact stub records, deduped by title, never
    # overlapping a title that already has a real brief on the desk.
    brief_titles = {_norm_title(i.get("title")) for i in items}
    queued: list[dict[str, Any]] = []
    seen_q: set[str] = set()
    for it in sorted(
        stub_items,
        key=lambda i: (
            0 if i.get("priority") == "high" else 1,
            0 if i.get("needs_refresh") else 1,
            -(i.get("freshness_hours") or 0),
        ),
    ):
        key = _norm_title(it.get("title"))
        if not key or key in seen_q or key in brief_titles:
            continue
        seen_q.add(key)
        queued.append({
            "id": it.get("id"),
            "title": it.get("title"),
            "primary_category": it.get("primary_category"),
            "source_system": it.get("source_system"),
            "source_table": it.get("source_table"),
            "source_id": it.get("source_id"),
            "symbol": it.get("symbol"),
            "priority": it.get("priority"),
            "freshness_hours": it.get("freshness_hours"),
            "freshness_label": it.get("freshness_label"),
            "needs_refresh": it.get("needs_refresh"),
            "stub": True,
        })
    queued_total = len(queued)
    queued = queued[:40]  # payload cap; stats carry the full count

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

    from lib.research_intelligence_portfolio import load_portfolio_context
    port_ctx = load_portfolio_context()

    # v3 Hermes joins — read-only, fail-open, page-scope only (≤50 items)
    _attach_hermes_context(page, db_query=db_query)
    wire = _hermes_wire(db_query=db_query) if not (lane or category or q or symbol) else []

    return {
        "ok": True,
        "version": "3.0",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "taxonomy": tax,
        "freshness_policy": {
            "tiers": policy.get("tiers"),
            "archive": policy.get("archive"),
            "slo": policy.get("slo"),
        },
        "filters": {
            "lane": lane,
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
            "lane_counts": lane_counts_full,
            "queued_research": queued_total,
            "queued_research_shown": len(queued),
            "hidden_count": len(hidden_items),
            "quality_tiers": {
                t: sum(1 for i in page if (i.get("quality_tier") or "") == t)
                for t in ("A", "B", "C")
            },
        },
        "items": page,
        "hidden_items": [
            {"id": i.get("id"), "title": i.get("title"), "symbol": i.get("symbol"),
             "primary_category": i.get("primary_category")}
            for i in hidden_items[:30]
        ],
        "queued_research": queued,
        "hermes_wire": wire,
        "priority_lanes": priority_lanes,
        "note": (
            "Research Intelligence v3.0 — Decision Desk: one-corpus counts, real lane filters, "
            "stub demotion to Queued research, brief-scoped tickers, Hermes score/wire/directive "
            "joins, run-research queue (after-close drain), staged-idea lifecycle + promotions."
        ),
        "portfolio_context": _portfolio_context_payload(port_ctx),
    }


def _attach_hermes_context(page: list[dict[str, Any]], *, db_query) -> None:
    """v3 (C1/C2/C4): read-only Hermes joins onto the rendered page.

    Fail-open by design — a missing table/row never blocks the feed. Two scoring
    systems disagreeing is information: divergence is FLAGGED, never blended.
    """
    syms: set[str] = set()
    for it in page:
        if it.get("symbol"):
            syms.add(str(it["symbol"]).upper())
        for t in it.get("ticker_recommendations") or []:
            if t.get("symbol"):
                syms.add(str(t["symbol"]).upper())
    if not syms:
        return
    sym_list = sorted(syms)

    scores: dict[str, dict[str, Any]] = {}
    try:
        rows = db_query(
            """SELECT DISTINCT ON (symbol) symbol, hermes_composite_score,
                      hermes_rank, scope_tier
               FROM watchlist_items
               WHERE symbol = ANY(%s) AND hermes_composite_score IS NOT NULL
               ORDER BY symbol, hermes_scored_at DESC NULLS LAST""",
            (sym_list,),
        ) or []
        for r in rows:
            try:
                scores[str(r["symbol"]).upper()] = {
                    "composite": round(float(r["hermes_composite_score"]), 1),
                    "rank": r.get("hermes_rank"),
                    "scope_tier": r.get("scope_tier"),
                }
            except (TypeError, ValueError, KeyError):
                continue
    except Exception:
        scores = {}

    ext: dict[str, list[dict[str, Any]]] = {}
    try:
        rows = db_query(
            """SELECT symbol, lane, recommendation, confidence, dissent, created_at
               FROM hermes_external_research
               WHERE created_at > now() - interval '14 days'
                 AND symbol = ANY(%s) AND recommendation IS NOT NULL
               ORDER BY created_at DESC""",
            (sym_list,),
        ) or []
        seen_lane: set[tuple[str, str]] = set()
        for r in rows:
            s = str(r.get("symbol") or "").upper()
            lane = str(r.get("lane") or "")
            if not s or (s, lane) in seen_lane:
                continue
            seen_lane.add((s, lane))
            ext.setdefault(s, []).append({
                "lane": lane,
                "recommendation": (r.get("recommendation") or "")[:400],
                "confidence": r.get("confidence"),
                "dissent": (r.get("dissent") or "")[:300] or None,
                "created_at": str(r.get("created_at") or "")[:19],
            })
    except Exception:
        ext = {}

    directives: dict[str, dict[str, Any]] = {}
    try:
        rows = db_query(
            """SELECT id, label, UPPER(spec->>'symbol') AS symbol
               FROM watch_directives
               WHERE kind = 'ticker' AND status = 'active'
                 AND UPPER(spec->>'symbol') = ANY(%s)""",
            (sym_list,),
        ) or []
        for r in rows:
            if r.get("symbol"):
                directives[str(r["symbol"])] = {"id": r.get("id"), "label": r.get("label")}
    except Exception:
        directives = {}

    for it in page:
        s = str(it.get("symbol") or "").upper()
        if s and s in scores:
            it["hermes_score"] = scores[s]
            qt = (it.get("quality_tier") or "").upper()
            comp = scores[s]["composite"]
            # Material disagreement between the RI conviction tier and the Hermes
            # composite — render both numbers, do not silently pick one
            if (qt == "A" and comp < 40) or (qt == "C" and comp >= 70):
                it["score_divergence"] = {"ri_tier": qt, "hermes_composite": comp}
        if s and s in ext:
            it["external_intel"] = ext[s]
        if s and s in directives:
            it["watch_directive"] = directives[s]
        for t in it.get("ticker_recommendations") or []:
            ts = str(t.get("symbol") or "").upper()
            if ts and ts in scores:
                t["hermes"] = scores[ts]
                ct = (t.get("conviction_tier") or "").upper()
                comp = scores[ts]["composite"]
                if (ct == "A" and comp < 40) or (ct == "C" and comp >= 70):
                    t["score_divergence"] = {"ri_tier": ct, "hermes_composite": comp}
            if ts and ts in directives:
                t["watch_directive"] = True


_WIRE_SCORE_RE = re.compile(r"([+-]\d+)\s*→\s*(\d+)")
_WIRE_RANK_RE = re.compile(r"rank\s*#(\d+)\s*\(from\s*#(\d+)\)", re.I)


def _hermes_wire(*, db_query, hours: int = 48, cap: int = 10) -> list[dict[str, Any]]:
    """v3 (C3): compact Hermes alert wire for Top stories.

    alert_events carries thousands of hermes_rank_surge rows per 48h — threshold
    hard (score move ≥8, rank improvement ≥20) and cap the strip. Fail-open.
    """
    try:
        rows = db_query(
            """SELECT alert_type, symbol, raw_text, severity, created_at
               FROM alert_events
               WHERE created_at > now() - make_interval(hours => %s)
                 AND alert_type IN ('hermes_score_move', 'hermes_rank_surge',
                                    'hermes_factor_shift', 'analyst_alert')
               ORDER BY created_at DESC
               LIMIT 500""",
            (int(hours),),
        ) or []
    except Exception:
        return []
    wire: list[dict[str, Any]] = []
    seen_sym: set[str] = set()
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        txt = str(r.get("raw_text") or "")
        atype = r.get("alert_type")
        if not sym or sym in seen_sym:
            continue
        keep = False
        if atype == "hermes_score_move":
            m = _WIRE_SCORE_RE.search(txt)
            keep = bool(m and abs(int(m.group(1))) >= 8)
        elif atype == "hermes_rank_surge":
            m = _WIRE_RANK_RE.search(txt)
            keep = bool(m and (int(m.group(2)) - int(m.group(1))) >= 20)
        elif atype in ("hermes_factor_shift", "analyst_alert"):
            keep = True
        if not keep:
            continue
        seen_sym.add(sym)
        wire.append({
            "alert_type": atype,
            "symbol": sym,
            "text": txt[:160],
            "severity": r.get("severity"),
            "created_at": str(r.get("created_at") or "")[:19],
        })
        if len(wire) >= cap:
            break
    return wire


def _portfolio_context_payload(port_ctx: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total_mv": port_ctx.get("total_mv"),
        "cash_mv": port_ctx.get("cash_mv"),
        "invested_mv": port_ctx.get("invested_mv"),
        "top": port_ctx.get("top") or [],
        "sleeves": port_ctx.get("sleeves") or {},
        "flags": port_ctx.get("flags") or [],
        "concentration": port_ctx.get("concentration") or {},
        "theme_capacity": port_ctx.get("theme_capacity") or {},
        "heat": port_ctx.get("heat") or {},
    }
    try:
        from lib.research_intelligence_themes import build_cross_theme_context
        ctx = build_cross_theme_context(port_ctx)
        out["concentration_banner"] = ctx.get("concentration_banner")
        out["cross_theme"] = {
            "current_weights": ctx.get("current_weights"),
            "soft_max": ctx.get("soft_max"),
            "constrained_names": ctx.get("constrained_names"),
            "income_over_capacity": ctx.get("income_over_capacity"),
        }
    except Exception:
        pass
    return out



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
    hidden: bool | None = None,
) -> dict[str, Any]:
    """Insert or update operator feedback for an intelligence item.

    hidden (v3.1 B2) is operator curation only — the Hermes row is untouched;
    the default feed simply excludes hidden items."""
    if not item_id:
        return {"ok": False, "error": "item_id required"}
    # Load existing
    existing = db_query(
        "SELECT item_id, starred, vote, note, hidden FROM research_intelligence_feedback WHERE item_id=%s",
        (item_id,),
        fetch="one",
    )
    if existing is None and starred is None and vote is None and note is None and hidden is None:
        return {"ok": False, "error": "nothing to update"}

    cur_star = bool(existing.get("starred")) if existing else False
    cur_vote = existing.get("vote") if existing else None
    cur_note = existing.get("note") if existing else None
    cur_hidden = bool(existing.get("hidden")) if existing else False
    if hidden is not None:
        cur_hidden = bool(hidden)
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
            (item_id, source_system, source_table, source_id, starred, vote, note, categories, symbol, hidden, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (item_id) DO UPDATE SET
            starred = EXCLUDED.starred,
            vote = EXCLUDED.vote,
            note = EXCLUDED.note,
            hidden = EXCLUDED.hidden,
            source_system = COALESCE(EXCLUDED.source_system, research_intelligence_feedback.source_system),
            source_table = COALESCE(EXCLUDED.source_table, research_intelligence_feedback.source_table),
            source_id = COALESCE(EXCLUDED.source_id, research_intelligence_feedback.source_id),
            categories = CASE WHEN EXCLUDED.categories = '{}' THEN research_intelligence_feedback.categories
                              ELSE EXCLUDED.categories END,
            symbol = COALESCE(EXCLUDED.symbol, research_intelligence_feedback.symbol),
            updated_at = NOW()
        """,
        (item_id, source_system, source_table, str(source_id) if source_id is not None else None,
         cur_star, cur_vote, cur_note, cats, symbol, cur_hidden),
        fetch=None,
    )
    return {
        "ok": True,
        "item_id": item_id,
        "hidden": cur_hidden,
        "starred": cur_star,
        "vote": cur_vote,
        "note": cur_note,
    }


def _qa_flag_counts_from_snapshots() -> dict[str, int]:
    """v3.1 (WS-D): the desk's tracked garbage rate — read from the 'top'
    snapshot (lint runs at materialization). Empty dict when no snapshot yet."""
    import json as _j
    try:
        p = PROJECT_ROOT / "data" / "runtime" / "ri_snapshots" / "top.json"
        snap = _j.loads(p.read_text(encoding="utf-8"))
        return (snap.get("feed") or {}).get("stats", {}).get("qa_flag_counts") or {}
    except Exception:
        return {}


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

    # Next-action label distribution (B4 self-check): a CTA stamped on >20% of
    # briefs is a default, not guidance — surface it so the desk stays honest.
    action_labels: dict[str, int] = {}
    briefs_n = 0
    for it in feed.get("items") or []:
        briefs_n += 1
        na = it.get("next_action")
        lab = (na.get("label") if isinstance(na, dict) else None) or "(none)"
        action_labels[lab] = action_labels.get(lab, 0) + 1
    label_dist = [
        {"label": k, "count": v, "pct": round(100.0 * v / briefs_n, 1) if briefs_n else 0.0}
        for k, v in sorted(action_labels.items(), key=lambda x: -x[1])
    ]
    over_cap = [
        d for d in label_dist
        if d["label"] != "(none)" and d["pct"] > 20.0
    ]

    # Coverage gaps (v3 D4): categories whose live+fresh brief count sits under
    # the configured floor — rendered in the rail with a Queue action.
    floors = {
        k: v for k, v in (policy.get("coverage_floors") or {}).items()
        if not k.startswith("_") and isinstance(v, (int, float))
    }
    coverage_gaps = []
    for cat, floor in floors.items():
        d = by_cat.get(cat) or {}
        fresh_n = int(d.get("live") or 0) + int(d.get("fresh") or 0)
        if fresh_n < floor:
            coverage_gaps.append({
                "category": cat,
                "fresh_briefs": fresh_n,
                "floor": floor,
                "total_briefs": int(d.get("count") or 0),
            })
    coverage_gaps.sort(key=lambda g: g["fresh_briefs"] - g["floor"])

    # v3.1 (B3): operator-feedback tallies per category (7d) — "12 hidden this
    # week" is a research-engine quality signal, not UI trivia
    feedback_tallies: dict[str, dict] = {}
    try:
        rows = db_query("""
            SELECT unnest(CASE WHEN categories = '{}' OR categories IS NULL
                               THEN ARRAY['(uncategorized)'] ELSE categories END) AS cat,
                   count(*) FILTER (WHERE starred)  AS starred,
                   count(*) FILTER (WHERE hidden)   AS hidden,
                   count(*) FILTER (WHERE vote < 0) AS downvoted
            FROM research_intelligence_feedback
            WHERE updated_at > now() - interval '7 days'
            GROUP BY 1 ORDER BY 3 DESC, 4 DESC
        """) or []
        feedback_tallies = {
            r["cat"]: {"starred": r["starred"], "hidden": r["hidden"], "downvoted": r["downvoted"]}
            for r in rows
        }
    except Exception:
        feedback_tallies = {}

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "by_category": by_cat,
        "stale_topics": stale_topics[:30],
        "stale_topic_count": len(stale_topics),
        "coverage_gaps": coverage_gaps,
        "feedback_tallies_7d": feedback_tallies,
        "qa_flag_counts": _qa_flag_counts_from_snapshots(),
        "queued_research_count": (feed.get("stats") or {}).get("queued_research"),
        "action_label_distribution": label_dist[:15],
        "action_labels_over_20pct": over_cap,
        "feed_stats": feed.get("stats"),
        "slo": slo,
    }
