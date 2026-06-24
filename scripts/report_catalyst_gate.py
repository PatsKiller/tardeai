"""report_catalyst_gate.py — block policy-sensitive reports with empty news/catalysts.

Quantum / CHIPS / government-directive names must ship with at least one scored headline
before PDF/DOCX publication. Attempts a live enrichment refresh once before blocking.
"""
from __future__ import annotations

import os
import re
from typing import Any

# Commerce CHIPS LOI + common public quantum names (operator macro watch set).
POLICY_CATALYST_SYMBOLS = frozenset({
    "RGTI", "QBTS", "IONQ", "QUBT", "ARQQ", "BTQ", "QNTM",
    "GFS", "IBM",
})

_DIRECTIVE_KEYWORDS = re.compile(
    r"quantum|chips\s*act|executive\s+order|commerce|nist|government|federal|"
    r"defense|national\s+security|white\s+house|equity\s+stake",
    re.IGNORECASE,
)

_META_KEYWORDS = re.compile(
    r"quantum|chips|semiconductor\s+policy|national\s+security|defense\s+contract",
    re.IGNORECASE,
)

_EMPTY_NEWS_PHRASE = "no material scored catalysts"


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _news_section(report: dict) -> dict | None:
    for sec in report.get("sections") or []:
        if sec.get("id") == "news_catalysts":
            return sec
    return None


def news_catalysts_adequate(report: dict) -> bool:
    """True when the news section has at least one substantive headline."""
    sec = _news_section(report)
    if not sec:
        return False
    bullets = [str(b).strip() for b in (sec.get("bullets") or []) if str(b).strip()]
    if bullets:
        return True
    content = str(sec.get("content") or "").strip().lower()
    if not content:
        return False
    if _EMPTY_NEWS_PHRASE in content:
        return False
    return len(content) >= 24


def _directive_requires_catalysts(symbol: str) -> bool:
    sym = (symbol or "").upper().strip()
    if not sym:
        return False
    try:
        from db_adapter import _execute
        rows = _execute(
            """SELECT wd.label, wd.rationale
               FROM watchlist_items wi
               JOIN watch_directives wd ON wd.id = wi.directive_id
               WHERE UPPER(wi.symbol) = %s
                 AND wi.in_directive_watch = true
                 AND wi.status <> 'removed'
                 AND wd.status = 'active'
               LIMIT 8""",
            (sym,),
            fetch="all",
        ) or []
        for row in rows:
            blob = f"{row.get('label') or ''} {row.get('rationale') or ''}"
            if _DIRECTIVE_KEYWORDS.search(blob):
                return True
        rows2 = _execute(
            """SELECT label, rationale FROM watch_directives
               WHERE status = 'active' AND kind = 'ticker'
                 AND UPPER(spec->>'symbol') = %s
               LIMIT 4""",
            (sym,),
            fetch="all",
        ) or []
        for row in rows2:
            blob = f"{row.get('label') or ''} {row.get('rationale') or ''}"
            if _DIRECTIVE_KEYWORDS.search(blob):
                return True
    except Exception:
        pass
    return False


def catalyst_gate_required(report: dict) -> tuple[bool, str]:
    """Return (required, reason) for catalyst coverage on this report."""
    meta = report.get("meta") or {}
    sym = str(meta.get("symbol") or "").upper().strip()
    if not sym:
        return False, "no_symbol"

    if _env_bool("REPORT_CATALYST_GATE_ALL", False):
        return True, "env_all_symbols"

    if sym in POLICY_CATALYST_SYMBOLS:
        return True, "policy_symbol_list"

    if _directive_requires_catalysts(sym):
        return True, "directive_watch"

    company = str(meta.get("company") or "")
    sector = str(meta.get("sector") or "")
    if _META_KEYWORDS.search(f"{company} {sector}"):
        return True, "meta_policy_theme"

    return False, "not_required"


def refresh_news_catalysts_section(report: dict) -> bool:
    """Live-fetch news and rewrite news_catalysts. Returns True if section now adequate."""
    meta = report.get("meta") or {}
    sym = str(meta.get("symbol") or "").upper().strip()
    if not sym:
        return False
    try:
        from analyst_report_builder import _news_for_symbol
        from report_synthesis import _pro_analyst, narrative_news
    except Exception:
        return False

    company = meta.get("company") or ""
    news = _news_for_symbol(sym, limit=8, company=company, use_live_enrichment=True)
    if not news:
        return False

    pro = _pro_analyst(sym)
    news_narr, news_bullets = narrative_news(news, pro)
    sec = _news_section(report)
    if sec is None:
        report.setdefault("sections", []).append({
            "id": "news_catalysts",
            "title": "Latest News & Catalysts",
            "content": news_narr,
            "bullets": news_bullets,
        })
    else:
        sec["content"] = news_narr
        sec["bullets"] = news_bullets
    return news_catalysts_adequate(report)


def evaluate_catalyst_gate(
    report: dict,
    *,
    attempt_refresh: bool = True,
) -> dict[str, Any]:
    """Evaluate policy catalyst gate. Mutates report when refresh succeeds."""
    required, reason = catalyst_gate_required(report)
    if not required:
        return {
            "required": False,
            "reason": reason,
            "adequate": True,
            "block": False,
            "refreshed": False,
            "issues": [],
        }

    adequate = news_catalysts_adequate(report)
    refreshed = False
    if not adequate and attempt_refresh:
        refreshed = refresh_news_catalysts_section(report)
        adequate = news_catalysts_adequate(report)

    issues: list[str] = []
    if not adequate:
        issues.append(
            "news_catalysts empty — policy-sensitive symbol requires executive-order / "
            "government-investment / company-specific headlines before publication"
        )

    return {
        "required": True,
        "reason": reason,
        "adequate": adequate,
        "block": not adequate,
        "refreshed": refreshed,
        "issues": issues,
    }


def publication_blocked(report: dict) -> bool:
    """True when oversight/catalyst gate forbids shipping PDF/DOCX."""
    meta = report.get("meta") or {}
    cg = meta.get("catalyst_gate") or {}
    if cg.get("required") and cg.get("adequate") is False:
        return True
    ov = meta.get("claude_oversight") or {}
    cg_stamp = ov.get("catalyst_gate") or {}
    if cg_stamp.get("block"):
        return True
    if ov.get("verdict") == "BLOCK" and cg_stamp.get("required") and not cg_stamp.get("adequate"):
        return True
    return False


def apply_catalyst_gate_block(report: dict, gate: dict[str, Any]) -> int:
    """Stamp BLOCK overlays when the catalyst gate fails. Returns fixes applied count."""
    if not gate.get("block"):
        return 0
    applied = 0
    secs = {s.get("id"): s for s in (report.get("sections") or [])}
    exec_sec = secs.get("executive_summary")
    detail = (
        "Publication blocked: Latest News & Catalysts is empty for a policy-sensitive name "
        f"({gate.get('reason')}). Re-run after portfolio-news ingestion or verify "
        "catalyst_enrichment providers."
    )
    if exec_sec is not None:
        exec_sec.setdefault("callouts", []).insert(
            0,
            {"label": "⚠ Catalyst Gate: HOLD FOR REVIEW", "text": detail},
        )
        applied += 1
    news_sec = secs.get("news_catalysts")
    if news_sec is not None:
        news_sec.setdefault("oversight_flags", []).append({
            "action": "block_publication",
            "detail": "; ".join(gate.get("issues") or [detail]),
        })
        applied += 1
    meta = report.setdefault("meta", {})
    meta["catalyst_gate"] = {
        "required": True,
        "reason": gate.get("reason"),
        "adequate": False,
        "refreshed": gate.get("refreshed"),
        "issues": gate.get("issues"),
    }
    return applied