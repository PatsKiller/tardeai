"""Research Intelligence aggregator — taxonomy + unified feed for CC v3.

Builds a first-class intelligence dashboard payload from existing Hermes,
topic_monitor, user_research_topics, news, and holdings — without reinventing
ingestion. Classification is rule-based + research_type mapping (cheap, stable).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = PROJECT_ROOT / "config" / "research_intelligence_taxonomy.json"
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"

# Patterns → category ids (order matters: first match wins for primary)
_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    # Note: never bare "roth" (matches "Roth Capital" sell-side); never roth.?ira
    # (matches account codes like schwab_roth_ira on stop health rows).
    ("retirement_tax", re.compile(
        r"roth\s+(?:ira|conversion|ladder|account|plans?)|conversion\s+ladder|"
        r"taxable\s+conversion|golden\s+window|"
        r"(?<![_\w])rmd(?![_\w])|required\s+minimum|\birmaa\b|\bmedicaid\b|"
        r"estate\s+plan|estate\s+tax|\bprobate\b|"
        r"\bssdi\b|backdoor\s+roth|qualified\s+charitable|\bqcd\b|life\s+estate|"
        r"asset\s+protection|spend.?down|look.?back\s+period|\bmedigap\b|medicare\s+part\s+[bd]\b|"
        r"retirement\s+tax|tax.?efficient\s+withdrawal|social\s+security\s+claim",
        re.I,
    )),
    ("dividend_income", re.compile(
        r"dividend|covered.?call|\bcef\b|\bbdc\b|income sleeve|aristocrat|"
        r"monthly income|jepi|jepq|schd|pflt|cswc|distribution yield",
        re.I,
    )),
    ("macro_geo", re.compile(
        r"\bfed\b|fomc|inflation|cpi|pce|treasury|yield curve|geopolitic|"
        r"tariff|oil shock|\bvix\b|regime|liquidity|rates? hike|recession|gdp",
        re.I,
    )),
    ("sector_thematic", re.compile(
        r"sector|rotation|defense|aerospace|semiconductor|ai chip|datacenter|"
        r"staples|healthcare|utilities|energy sector|materials|consumer defensive",
        re.I,
    )),
    ("risk_regime", re.compile(
        r"\bstop\b|protection|drawdown|volatility|heat|risk.?on|risk.?off|"
        r"stop.?health|stop.?curation|portfolio heat",
        re.I,
    )),
    ("catalyst_event", re.compile(
        r"catalyst|earnings|news_momentum|breakout|event.?driven|form.?4",
        re.I,
    )),
    ("compounding_wealth", re.compile(
        r"compound|long.?term wealth|asset allocation|bucket strateg|"
        r"drawdown plan|wealth framework|multi.?year",
        re.I,
    )),
    ("academic_pro", re.compile(
        r"academic|paper\b|journal|white.?paper|pro.?analyst|transcript|"
        r"ph\.?d|sven carlin|research summary",
        re.I,
    )),
]

_TYPE_TO_CAT = {
    "topic_research": None,  # classify by topic text
    "momentum_catalyst": "catalyst_event",
    "protection_advisory": "risk_regime",
    "stop_curation": "risk_regime",
    "stop_health": "risk_regime",
    "ticker_thesis_challenge": "company_ticker",
    "options_desk": "company_ticker",
    "youtube_discovery": "academic_pro",
    "research_backlog": "company_ticker",
    # operator_knowledge is multi-domain — classify by text, not type map
}


def load_taxonomy() -> dict[str, Any]:
    if TAXONOMY_PATH.exists():
        return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return {"categories": [], "version": "0"}


def classify_text(*parts: str | None, research_type: str | None = None) -> list[str]:
    """Return ordered list of category ids (primary first)."""
    blob = " ".join(p for p in parts if p)
    cats: list[str] = []
    mapped = _TYPE_TO_CAT.get(research_type or "")
    if mapped:
        cats.append(mapped)
    # Stop / protection advisories are risk_regime-primary; skip soft keyword bleed
    # (e.g. account name schwab_roth_ira) into retirement_tax.
    _risk_types = {"protection_advisory", "stop_curation", "stop_health"}
    for cid, rx in _CATEGORY_RULES:
        if cid == "retirement_tax" and (research_type or "") in _risk_types:
            continue
        if rx.search(blob) and cid not in cats:
            cats.append(cid)
    if not cats:
        cats.append("company_ticker" if (parts and parts[0]) else "sector_thematic")
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


def build_feed(
    *,
    db_query,
    category: str | None = None,
    q: str | None = None,
    priority: str | None = None,
    symbol: str | None = None,
    limit: int = 80,
    holdings_only: bool = False,
) -> dict[str, Any]:
    """Unified research intelligence feed for the dashboard."""
    tax = load_taxonomy()
    held = holdings_symbols()
    limit = max(10, min(int(limit or 80), 200))

    items: list[dict[str, Any]] = []

    # ── Hermes research ──────────────────────────────────────────────────
    rows = db_query("""
        SELECT id, topic, summary, thesis, symbol, research_type, confidence_score,
               quality_score, status, model_used, source, created_at, freshness_date,
               evidence_json, source_urls_json, tags, category_content, category_sector
        FROM hermes_research_intelligence
        WHERE status IS NULL OR status NOT IN ('rejected','discarded')
        ORDER BY created_at DESC
        LIMIT 500
    """) or []

    for r in rows:
        # Title/topic drives primary category; body may add secondary tags only.
        # Prevents long Hermes summaries that mention Roth Capital / IRMAA in
        # passing from re-labeling an Industry: or stop-health topic.
        topic_cats = classify_text(r.get("topic"), research_type=r.get("research_type"))
        body_cats = classify_text(r.get("summary"), r.get("thesis"))
        cats: list[str] = list(topic_cats)
        for c in body_cats:
            if c not in cats:
                cats.append(c)
        cats = cats[:4]
        sym = (r.get("symbol") or "").upper() or None
        # Infer symbol from topic "news_momentum: XYZ"
        if not sym and r.get("topic"):
            m = re.search(r":\s*([A-Z]{1,5})\b", str(r.get("topic") or ""))
            if m:
                sym = m.group(1)
        is_held = bool(sym and sym in held)
        if holdings_only and not is_held and "retirement_tax" not in cats and "macro_geo" not in cats:
            continue
        if category and category not in cats:
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
        age = _age_hours(r.get("created_at") or r.get("freshness_date"))
        pri = _priority_from(cats, conf, age, is_held)
        if priority and pri != priority:
            continue
        # sources
        sources = []
        ev = r.get("evidence_json")
        if isinstance(ev, str):
            try:
                ev = json.loads(ev)
            except Exception:
                ev = {}
        if isinstance(ev, dict):
            for g in (ev.get("grounded_on") or [])[:5]:
                if isinstance(g, dict):
                    sources.append({
                        "title": g.get("title"), "url": g.get("url"), "source": g.get("source"),
                    })
        su = r.get("source_urls_json")
        if isinstance(su, str):
            try:
                su = json.loads(su)
            except Exception:
                su = []
        if isinstance(su, list):
            for u in su[:3]:
                if isinstance(u, str):
                    sources.append({"url": u})
                elif isinstance(u, dict):
                    sources.append(u)

        items.append({
            "id": f"hermes:{r.get('id')}",
            "source_system": "hermes",
            "source_table": "hermes_research_intelligence",
            "source_id": r.get("id"),
            "title": r.get("topic") or "Research finding",
            "summary": (r.get("summary") or "")[:500],
            "thesis": (r.get("thesis") or "")[:400] or None,
            "symbol": sym,
            "categories": cats,
            "primary_category": cats[0],
            "priority": pri,
            "confidence": conf,
            "freshness_hours": round(age, 1) if age is not None else None,
            "created_at": r.get("created_at").isoformat() if hasattr(r.get("created_at"), "isoformat") else r.get("created_at"),
            "model": r.get("model_used"),
            "research_type": r.get("research_type"),
            "status": r.get("status"),
            "is_holdings": is_held,
            "sources": sources[:6],
            "actionability": (
                "Review Roth/tax plan impact" if "retirement_tax" in cats else
                "Check dividend/income exposure" if "dividend_income" in cats and is_held else
                "Map to sector allocation" if "sector_thematic" in cats else
                "Update thesis / stops" if is_held else
                "Advisory — watchlist or thematic"
            ),
        })

    # ── Auto-research / user topics ──────────────────────────────────────
    ut = db_query("""
        SELECT id, topic, symbol, latest_findings, priority, research_count,
               status, source, updated_at, created_at, original_message, trigger
        FROM user_research_topics
        WHERE status = 'active' OR status IS NULL
        ORDER BY updated_at DESC NULLS LAST
        LIMIT 80
    """) or []
    for r in ut:
        cats = classify_text(r.get("topic"), r.get("latest_findings"), r.get("original_message"), r.get("trigger"))
        if r.get("source") == "auto_research.py" and "company_ticker" not in cats:
            cats = ["company_ticker"] + [c for c in cats if c != "company_ticker"]
        sym = (r.get("symbol") or "").upper() or None
        if not sym and r.get("topic"):
            t = str(r.get("topic")).upper().strip()
            if re.fullmatch(r"[A-Z]{1,5}", t):
                sym = t
        is_held = bool(sym and sym in held)
        if category and category not in cats:
            continue
        if symbol and sym != symbol.upper():
            continue
        blob = f"{r.get('topic')} {r.get('latest_findings')} {r.get('original_message')}"
        if q and q.lower() not in blob.lower():
            continue
        age = _age_hours(r.get("updated_at") or r.get("created_at"))
        pri = "high" if (r.get("priority") or 0) >= 8 or is_held else _priority_from(cats, None, age, is_held)
        if priority and pri != priority:
            continue
        items.append({
            "id": f"urt:{r.get('id')}",
            "source_system": "auto_research" if r.get("source") == "auto_research.py" else "operator_topic",
            "source_table": "user_research_topics",
            "source_id": r.get("id"),
            "title": r.get("topic") or (sym or "Topic"),
            "summary": (r.get("latest_findings") or r.get("original_message") or "")[:500],
            "thesis": None,
            "symbol": sym,
            "categories": cats,
            "primary_category": cats[0],
            "priority": pri,
            "confidence": None,
            "freshness_hours": round(age, 1) if age is not None else None,
            "created_at": r.get("updated_at").isoformat() if hasattr(r.get("updated_at"), "isoformat") else r.get("updated_at"),
            "model": None,
            "research_type": "auto_research" if r.get("source") == "auto_research.py" else "user_topic",
            "status": r.get("status"),
            "is_holdings": is_held,
            "sources": [],
            "actionability": "Open full brief / manage topic",
            "research_count": r.get("research_count"),
        })

    # ── Topic monitor registry (taxonomy-tagged) ─────────────────────────
    mon = db_query("""
        SELECT topic_id, display_name, priority, enabled, last_searched, last_found_count,
               agent_owner, owner, strategy_tags
        FROM topic_monitor
        WHERE enabled IS TRUE OR enabled IS NULL
        ORDER BY priority DESC NULLS LAST, last_searched DESC NULLS LAST
        LIMIT 120
    """) or []
    for r in mon:
        cats = classify_text(r.get("display_name"), r.get("topic_id"), " ".join(r.get("strategy_tags") or []))
        if category and category not in cats:
            continue
        blob = f"{r.get('display_name')} {r.get('topic_id')}"
        if q and q.lower() not in blob.lower():
            continue
        if symbol:
            continue  # monitor rows are thematic, not ticker
        age = _age_hours(r.get("last_searched"))
        pri = "high" if (r.get("priority") or 0) >= 8 or "retirement_tax" in cats else "normal"
        if priority and pri != priority:
            continue
        items.append({
            "id": f"tm:{r.get('topic_id')}",
            "source_system": "topic_monitor",
            "source_table": "topic_monitor",
            "source_id": r.get("topic_id"),
            "title": r.get("display_name") or r.get("topic_id"),
            "summary": f"Topic monitor · last found {r.get('last_found_count') or 0} items · owner {r.get('agent_owner') or r.get('owner') or '—'}",
            "thesis": None,
            "symbol": None,
            "categories": cats,
            "primary_category": cats[0],
            "priority": pri,
            "confidence": None,
            "freshness_hours": round(age, 1) if age is not None else None,
            "created_at": r.get("last_searched").isoformat() if hasattr(r.get("last_searched"), "isoformat") else r.get("last_searched"),
            "model": None,
            "research_type": "topic_monitor",
            "status": "enabled" if r.get("enabled") else "paused",
            "is_holdings": False,
            "sources": [],
            "actionability": "Ingest via topic_ingestion · curate with topic_curator",
        })

    # Sort: operator-critical taxonomy first, then priority, holdings, freshness.
    # Retirement / dividends / macro must not drown under ticker stop-noise.
    pri_rank = {"high": 0, "normal": 1, "low": 2}
    _FOCUS = ("retirement_tax", "dividend_income", "macro_geo", "sector_thematic")

    def _focus_boost(it: dict) -> int:
        cats = it.get("categories") or []
        for i, c in enumerate(_FOCUS):
            if c in cats:
                return i  # lower = more important
        return 20

    def _sk(it: dict) -> tuple:
        return (
            _focus_boost(it),
            pri_rank.get(it.get("priority") or "normal", 1),
            0 if it.get("is_holdings") else 1,
            it.get("freshness_hours") if it.get("freshness_hours") is not None else 9999,
        )

    items.sort(key=_sk)

    # Category counts from full matched set (before hard limit)
    cat_counts: dict[str, int] = {}
    for it in items:
        for c in it.get("categories") or []:
            cat_counts[c] = cat_counts.get(c, 0) + 1

    # Priority lanes from FULL match set so top-3 categories never go empty
    # just because holdings stop-noise filled the first page.
    def _lane(pred, n: int = 16) -> list[dict[str, Any]]:
        return [i for i in items if pred(i)][:n]

    # Retirement lane: primary category only (body-text can bleed IRMAA/Roth into
    # unrelated industry notes as secondary tags). Dividends/macro allow multi-tag.
    priority_lanes = {
        "retirement": _lane(lambda i: (i.get("primary_category") == "retirement_tax")
                            or (i.get("categories") or [None])[0] == "retirement_tax"),
        "dividends": _lane(lambda i: "dividend_income" in (i.get("categories") or [])),
        "macro_sector": _lane(lambda i: (
            "macro_geo" in (i.get("categories") or [])
            or "sector_thematic" in (i.get("categories") or [])
        )),
    }

    page = items[:limit]
    high_n = sum(1 for i in page if i.get("priority") == "high")
    held_n = sum(1 for i in page if i.get("is_holdings"))

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "taxonomy": tax,
        "filters": {
            "category": category,
            "q": q,
            "priority": priority,
            "symbol": symbol,
            "holdings_only": holdings_only,
            "limit": limit,
        },
        "stats": {
            "returned": len(page),
            "matched": len(items),
            "high_priority": high_n,
            "holdings_linked": held_n,
            "by_category": cat_counts,
            "holdings_universe": sorted(held)[:40],
            "holdings_count": len(held),
            "lane_counts": {k: len(v) for k, v in priority_lanes.items()},
        },
        "items": page,
        "priority_lanes": priority_lanes,
        "note": (
            "Research Intelligence v1 aggregates Hermes, auto-research, operator topics, "
            "and topic_monitor under a shared taxonomy. Ingestion remains topic_ingestion + "
            "Hermes autonomous loop — this surface is the operator cockpit."
        ),
    }
