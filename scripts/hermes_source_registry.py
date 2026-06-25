"""hermes_source_registry.py — enrich research_sources for Command Center Sources tab.

Splits registry rows into ingestion connectors vs news-maturity candidates vs web yield domains,
links paired news↔web entries, loads operator vetting queue, and supports operator approval.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
VETTING_ACTIONS = ROOT / "data" / "runtime" / "source_vetting_actions_latest.json"
AUTO_APPROVAL_AUDIT = ROOT / "data" / "runtime" / "source_auto_approval_latest.json"

CONNECTOR_TYPES = frozenset({
    "social", "youtube", "sec", "rss",
    "ai_openai", "ai_anthropic", "ai_xai", "seeking_alpha",
})

KNOWN_NEWS_WEB: dict[str, str] = {
    "CNBC": "cnbc.com",
    "CNN": "cnn.com",
    "edition.cnn.com": "edition.cnn.com",
    "Reuters": "reuters.com",
    "Zacks Investment Research": "zacks.com",
    "Investor's Business Daily": "investors.com",
    "Barchart.com": "barchart.com",
    "TipRanks": "tipranks.com",
    "ChartMill": "chartmill.com",
    "TradingView": "tradingview.com",
    "Yahoo Finance": "finance.yahoo.com",
    "Yahoo Finance UK": "uk.finance.yahoo.com",
    "Yahoo Finance Singapore": "sg.finance.yahoo.com",
    "Yahoo Finance Australia": "au.finance.yahoo.com",
    "Financial Times": "markets.ft.com",
    "Stocktwits": "stocktwits.com",
    "Quiver Quantitative": "quiverquant.com",
    "Stock Titan": "stocktitan.net",
    "barrons": "barrons.com",
    "marketwatch": "marketwatch.com",
    "morningstar": "morningstar.com",
    "seeking_alpha": "seekingalpha.com",
    "finviz_news": "finviz.com",
    "motley_fool": "fool.com",
    "hermes": "hermes",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def parse_maturity_notes(notes: str | None) -> dict | None:
    if not notes or not str(notes).strip().startswith("{"):
        return None
    try:
        return json.loads(notes)
    except Exception:
        return None


def news_label(name: str) -> str:
    if name.startswith("google_news:"):
        return name.split(":", 1)[1]
    return name.replace("_", " ")


def linked_web_domain(news_name: str, web_by_name: dict[str, dict]) -> str | None:
    """Best-effort link from a news maturity row to a preferred web domain."""
    if news_name in KNOWN_NEWS_WEB:
        dom = KNOWN_NEWS_WEB[news_name]
        if dom == "hermes":
            return None
        if dom in web_by_name:
            return dom
    label = news_label(news_name)
    if label in KNOWN_NEWS_WEB:
        dom = KNOWN_NEWS_WEB[label]
        if dom in web_by_name:
            return dom
    nlabel = _norm(label)
    for dom in web_by_name:
        if _norm(dom) == nlabel or _norm(dom).startswith(nlabel) or nlabel in _norm(dom):
            return dom
    # publisher slug → domain.com
    slug = re.sub(r"[^a-z0-9]", "", label.lower())
    for suffix in (".com", ".co.uk", ".io"):
        guess = f"{slug}{suffix}" if not slug.endswith(suffix.replace(".", "")) else slug
        if guess in web_by_name:
            return guess
    return None


def load_vetting_actions() -> list[dict]:
    if not VETTING_ACTIONS.exists():
        return []
    try:
        data = json.loads(VETTING_ACTIONS.read_text())
        return list(data.get("actions") or [])
    except Exception:
        return []


def load_auto_approval_audit() -> dict:
    if not AUTO_APPROVAL_AUDIT.exists():
        return {}
    try:
        return json.loads(AUTO_APPROVAL_AUDIT.read_text())
    except Exception:
        return {}


def cleanup_orphan_rss_rows(cur) -> int:
    """Remove stale duplicate RSS connector stub (hermes_rss_ingest vaporware row)."""
    cur.execute(
        """DELETE FROM research_sources
           WHERE source_type = 'rss'
             AND source_name = 'RSS feeds'
             AND (notes ILIKE '%hermes_rss_ingest%' OR active = false)
           RETURNING id"""
    )
    return len(cur.fetchall())


def enrich_source_rows(rows: list[dict]) -> dict:
    """Partition registry rows + attach links and vetting metadata."""
    web_by_name: dict[str, dict] = {}
    connectors: list[dict] = []
    news_maturity: list[dict] = []
    web: list[dict] = []

    for r in rows:
        item = dict(r)
        notes_raw = item.get("notes")
        mat = parse_maturity_notes(notes_raw)
        if mat:
            item["maturity"] = mat
            item["maturity_tier"] = mat.get("maturity_tier")
            item["maturity_score"] = mat.get("maturity_score")
            item["go_rate"] = mat.get("go_rate")
            item["outcome_proven"] = mat.get("outcome_proven")
            item["operator_core_approved"] = bool(mat.get("operator_core_approved"))
        st = str(item.get("type") or item.get("source_type") or "")
        if st == "web":
            web_by_name[str(item.get("name") or "")] = item
            web.append(item)
        elif st in CONNECTOR_TYPES:
            connectors.append(item)
        elif st == "news":
            news_maturity.append(item)
        else:
            connectors.append(item)

    actions = load_vetting_actions()
    auto_audit = load_auto_approval_audit()
    action_by_source = {a["source"]: a for a in actions}

    for n in news_maturity:
        name = str(n.get("name") or "")
        link = linked_web_domain(name, web_by_name)
        n["linked_web"] = link
        if link and link in web_by_name:
            n["web_preferred"] = bool(web_by_name[link].get("active"))
            n["web_yield"] = web_by_name[link].get("credibility")
        act = action_by_source.get(name)
        if act:
            n["vetting_action"] = act.get("action")
            n["vetting_score"] = act.get("score")
        try:
            import hermes_source_policy as hsp
            pol = hsp.resolve(name)
            n["policy"] = pol.as_dict()
            n["promotion_tier"] = pol.promotion_tier
            n["ingest_allowed"] = pol.ingest_allowed
        except Exception:
            pass
        # Content may still flow via RSS / SearXNG even when news row is dormant
        n["ingest_hint"] = (
            "Content may still arrive via active RSS or SearXNG web domains — "
            "this row is a maturity attribution label, not a separate ingest pipe."
            if not n.get("active") and (n.get("linked_web") or name.startswith("google_news:"))
            else None
        )

    news_maturity.sort(
        key=lambda x: (
            -(x.get("maturity_score") or 0),
            -(x.get("go_rate") or 0),
        ),
    )
    web.sort(key=lambda x: -(float(x.get("credibility") or 0)))

    return {
        "connectors": connectors,
        "news_maturity": news_maturity,
        "web": web,
        "vetting_actions": actions,
        "auto_approval": {
            "updated_at": auto_audit.get("updated_at"),
            "activated": auto_audit.get("activated") or [],
            "deactivated": auto_audit.get("deactivated") or [],
            "remaining_queue": auto_audit.get("remaining_actions", len(actions)),
        },
        "stats": {
            "connectors_active": sum(1 for c in connectors if c.get("active")),
            "connectors_total": len(connectors),
            "news_active": sum(1 for n in news_maturity if n.get("active")),
            "news_total": len(news_maturity),
            "web_preferred": sum(1 for w in web if w.get("active")),
            "web_total": len(web),
            "vetting_pending": len(actions),
            "auto_activated_total": sum(
                1 for n in news_maturity
                if (parse_maturity_notes(n.get("notes")) or {}).get("auto_approved")
            ),
            "news_linked_to_preferred_web": sum(
                1 for n in news_maturity if n.get("web_preferred")
            ),
        },
    }


def approve_news_source(cur, source_name: str, *, operator: str = "operator") -> dict:
    """Operator approves a news maturity source for core activation."""
    cur.execute(
        "SELECT id, source_type, active, notes FROM research_sources WHERE source_name=%s",
        (source_name,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": f"source {source_name!r} not found"}
    _id, stype, active, notes = row
    if stype != "news":
        return {"ok": False, "error": f"{source_name} is type {stype!r}, not news maturity"}
    mat = parse_maturity_notes(notes) or {}
    mat["operator_core_approved"] = True
    mat["operator_approved_at"] = datetime.now(timezone.utc).isoformat()
    mat["operator_approved_by"] = operator
    new_notes = json.dumps(mat)
    cur.execute(
        "UPDATE research_sources SET active=true, notes=%s WHERE id=%s",
        (new_notes, _id),
    )
    try:
        import hermes_source_policy as hsp
        hsp.invalidate_cache()
    except Exception:
        pass
    return {
        "ok": True,
        "source": source_name,
        "active": True,
        "maturity": mat,
        "was_active": bool(active),
    }