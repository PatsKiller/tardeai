#!/usr/bin/env python3
"""reports_portal.py — data layer for the v3 Reports portal.

Aggregates everything that goes out to the operator (Telegram / email / export) into ONE searchable,
paginated, categorized feed for the Reports hub. Two canonical stores:
  • notification_log  — structured briefs/digests/alerts (notification_type, subject, body_summary,
                        linked recommendation/escalation/observation ids, full payload)
  • alert_events      — individual SIEM alerts/advisories (alert_type, source_script, severity, symbol,
                        raw_text, parsed_payload, lifecycle_state/acknowledged/resolved)

Both are normalized to a common item shape and grouped into portal categories. Read + purge only.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ── Portal categories: friendly tab → (label, icon, member notification_types / alert filters) ──────
# Order here is the tab order in the UI.
CATEGORIES = [
    {"key": "morning_briefs", "label": "Morning Briefs", "icon": "🛡", "nl_types": ["aegis_morning_brief"], "ae": None,
     "ob_types": ["trade_ai_brief"]},
    {"key": "digests",        "label": "Digests",        "icon": "📰", "nl_types": ["daily_digest"], "ae": None,
     "ob_types": ["overnight_brief", "premarket_brief"]},
    {"key": "portfolio_briefs", "label": "Portfolio Briefs", "icon": "💼", "nl_types": [], "ae": None, "ob_types": ["portfolio_brief"]},
    {"key": "monthly",        "label": "Monthly Reports", "icon": "🗓", "nl_types": [], "ae": None,
     "ar_types": ["monthly", "monthly_retirement"], "ob_types": ["monthly_report", "commanders_summary"]},
    {"key": "weekly_reviews", "label": "Weekly Reviews",  "icon": "📆", "nl_types": [], "ae": None,
     "ar_types": ["weekly", "weekly_health"], "ob_types": ["strategy_weekly", "alex_review", "weekly_summary"]},
    {"key": "incubator",      "label": "Incubator Screen", "icon": "🧪", "nl_types": [], "ae": None, "ob_types": ["incubator_screen"]},
    {"key": "research",       "label": "Research & Intel", "icon": "🔬", "nl_types": [], "ae": None,
     "ob_types": ["auto_research", "daily_intel", "cio_summary"]},
    {"key": "eod_trades",     "label": "Trade Reports",   "icon": "📈", "nl_types": [], "ae": None,
     "ob_types": ["eod_open_trades", "closed_trade_digest"]},
    {"key": "critique",       "label": "Trade Critique",  "icon": "⚖️", "nl_types": [], "ae": None, "ob_types": ["trade_critique"]},
    {"key": "learning",       "label": "Learning Digest", "icon": "🧠", "nl_types": [], "ae": None, "ob_types": ["learning_digest"]},
    {"key": "alerts",         "label": "Alerts",         "icon": "🚨", "nl_types": ["urgent_alert", "info", "draft_alert", "alert_fatigue_meta", "stale_data_alert"],
     "ae": {"alert_type": ["strategic_alert", "analyst_alert"], "exclude_source": ["protective_stop", "protection_alerts", "stop_health", "portfolio_alerts"]}},
    {"key": "advisories",     "label": "Advisories",     "icon": "🧭", "nl_types": [], "ob_types": ["stop_brief"],
     "ae": {"source_script": ["protective_stop", "protection_alerts", "stop_health", "portfolio_alerts"]}},
    {"key": "recovery",       "label": "Recovery Watch", "icon": "♻️", "nl_types": ["recovery_escalation"], "ae": None,
     "ob_types": ["recovery_reminder"]},
    {"key": "dividends",      "label": "Dividends",      "icon": "💰", "nl_types": ["dividend_alert"], "ae": None},
    {"key": "regime",         "label": "Regime / Rebalance", "icon": "📊", "nl_types": ["regime_change", "rebalance_stale"], "ae": None},
    {"key": "paper",          "label": "Paper Trading",  "icon": "📝", "nl_types": ["paper_trade_monitor"], "ae": None},
    {"key": "system",         "label": "System Health",  "icon": "⚙️", "nl_types": ["api_credits_depleted", "backup_verification", "LLM_WARMUP_FAILED"],
     "ae": {"alert_type": ["system_health", "data_staleness", "data_integrity"]}},
]
_BY_KEY = {c["key"]: c for c in CATEGORIES}

# legacy/brief page slug → a REAL v3 route (label, route). Never a dead /v3/<x>.
_VALID_V3 = {"portfolio", "risk", "trading", "strategy", "agents", "intelligence", "hermes", "retirement",
             "journal", "watchlist", "watchpool", "sectors", "reports", "system", "manual-execution"}
_PAGE = {"risk": ("Risk", "/v3/risk"), "approvals": ("Approvals", "/v3/trading"),
         "recovery": ("Recovery", "/v3/risk"), "reco": ("Recovery", "/v3/risk"),   # Recovery Watch section lives in Risk hub
         "actions": ("Actions", "/v3/"), "trading": ("Trading", "/v3/trading"),    # Action Inbox is on Home
         "journal": ("Journal", "/v3/journal"), "system": ("System", "/v3/system"),
         "portfolio": ("Portfolio", "/v3/portfolio"), "research-topics": ("Research", "/v3/intelligence"),
         "research": ("Research", "/v3/intelligence"), "proposals": ("Proposals", "/v3/trading"),
         "paper-proposals": ("Proposals", "/v3/trading"), "paper-status": ("Trading", "/v3/trading"),
         "alerts": ("System", "/v3/system"), "siem": ("System", "/v3/system")}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


_DOCX_CACHE: dict = {"t": 0.0, "files": []}
_DOCX_TTL = 300.0


def _scan_docx_files() -> list[dict]:
    """Index downloadable .docx report files under project data/archive (bounded scan)."""
    import os, re, time
    now = time.time()
    if now - _DOCX_CACHE["t"] < _DOCX_TTL and _DOCX_CACHE["files"]:
        return _DOCX_CACHE["files"]
    root = PROJECT_ROOT
    patterns = [
        "data/portfolios/reports/weekly/weekly_*.docx",
        "data/portfolios/reports/monthly/monthly_*.docx",
        "data/portfolios/reports/portfolio_brief_*.docx",
        "reports/2026-*/*/*.docx",
        "archive/weekly/**/*.docx",
    ]
    out = []
    for pat in patterns:
        for fp in sorted(root.glob(pat), reverse=True)[:40]:
            try:
                if not fp.is_file():
                    continue
                rel = fp.relative_to(root)
                url = "/" + str(rel).replace("\\", "/")
                name = fp.name
                # date token from filename when present
                dm = re.search(r"(20\d{2}-\d{2}-\d{2})", name)
                out.append({
                    "filename": name,
                    "url": url,
                    "size_kb": round(fp.stat().st_size / 1024, 1),
                    "modified": fp.stat().st_mtime,
                    "date": dm.group(1) if dm else None,
                    "kind": "weekly" if "weekly" in str(rel) else "monthly" if "monthly" in str(rel)
                    else "portfolio" if "portfolio_brief" in name else "trade_ai" if "trade_ai" in name else "other",
                })
            except Exception:
                continue
    _DOCX_CACHE.update({"t": now, "files": out})
    return out


def _item_date_token(it: dict) -> str | None:
    ca = it.get("created_at")
    if not ca:
        return None
    if hasattr(ca, "strftime"):
        return ca.strftime("%Y-%m-%d")
    s = str(ca)[:10]
    return s if _re.match(r"20\d{2}-\d{2}-\d{2}", s) else None


def _resolve_docx(it: dict) -> dict | None:
    """Attach a same-day (or same-month) Word file when one exists on disk."""
    files = _scan_docx_files()
    if not files:
        return None
    cat = it.get("category") or ""
    rtype = (it.get("type") or "").lower()
    title = (it.get("title") or "").lower()
    day = _item_date_token(it)

    def pick(kind: str | None = None, date: str | None = None, name_rx: str | None = None):
        pool = [f for f in files if (not kind or f["kind"] == kind)]
        if date:
            exact = [f for f in pool if f.get("date") == date]
            if exact:
                return exact[0]
            # monthly: same YYYY-MM prefix
            if len(date) >= 7:
                pref = date[:7]
                month = [f for f in pool if (f.get("date") or "").startswith(pref)]
                if month:
                    return month[0]
        if name_rx:
            for f in pool:
                if _re.search(name_rx, f["filename"], _re.I):
                    return f
        return pool[0] if pool else None

    hit = None
    if cat in ("weekly_reviews",) or rtype in ("strategy_weekly", "alex_review", "weekly_summary", "weekly", "weekly_health"):
        hit = pick("weekly", day)
    elif cat in ("monthly",) or rtype in ("monthly", "monthly_retirement", "monthly_report", "commanders_summary"):
        hit = pick("monthly", day)
    elif cat in ("portfolio_briefs",) or rtype == "portfolio_brief":
        hit = pick("portfolio", day, r"portfolio_brief")
    elif "retirement" in title or rtype == "monthly_retirement":
        hit = pick("monthly", day)
    elif day and rtype in ("trade_ai_brief", "aegis_morning_brief", "daily_digest"):
        hit = pick("trade_ai", day)
    if not hit and day:
        hit = pick(None, day)
    if not hit:
        return None
    return {"filename": hit["filename"], "url": hit["url"], "size_kb": hit["size_kb"]}


def _full_body(payload, fallback: str) -> str:
    """The FULL report text. Briefs/digests store only a short body_summary in the DB; the complete
    readable markdown is written to payload.export — load it so the news reader shows the whole thing."""
    try:
        import os, json as _j
        p = payload if isinstance(payload, dict) else _j.loads(payload or "{}")
        exp = p.get("export") or p.get("export_path") or p.get("file")
        if exp and os.path.exists(exp):
            txt = open(exp, encoding="utf-8").read().strip()
            if txt:
                return txt
    except Exception:
        pass
    return fallback or ""


def _sev_from_nl(ntype: str) -> str:
    if ntype in ("urgent_alert", "recovery_escalation"):
        return "urgent"
    if ntype in ("aegis_morning_brief", "daily_digest", "info", "dividend_alert"):
        return "info"
    if ntype in ("stale_data_alert", "rebalance_stale", "draft_alert", "alert_fatigue_meta"):
        return "warning"
    return "info"


def _action_links(text: str) -> list[dict]:
    """Extract dashboard links from a report body, mapped to REAL v3 routes → dedup'd action buttons."""
    import re
    out, seen = [], set()
    for m in re.finditer(r"/v[23]/([a-z0-9-]+)", text or ""):
        seg = m.group(1).lower()
        if seg in _PAGE:
            label, route = _PAGE[seg]
        elif seg in _VALID_V3:
            label, route = seg.capitalize(), f"/v3/{seg}"
        else:
            continue   # unknown slug → don't emit a dead button
        if route not in seen:
            seen.add(route)
            out.append({"label": "Open " + label, "url": "https://ms01-openclaw.tail163d14.ts.net" + route})
    return out


# ── Deterministic action extraction (NO LLMs) ───────────────────────────────────────────────────────
# Maps a report's text → operator action items, each routed to a REAL v3 page. Rules are ordered by
# priority (most urgent first); a report can emit several distinct classes.
import re as _re
import time as _time

# ── Synthesis enrichment (sector / trend / finance_score / retirement_relevance / ensemble) ─────────
# Honest, cheap, bounded: three small maps loaded ONCE per ~2-min window and attached to the ≤100 items
# a page actually returns (in _enrich_item). Every field traces to a real source — null when absent, never
# fabricated. sector←symbol_profiles, trend←watchlist_items, ensemble←inference_ensemble_results.
_SYN_CACHE: dict = {"t": 0.0, "sector": {}, "trend": {}, "ensemble": {}}
_SYN_TTL = 120.0

# finance-substance keywords (shared spirit with inference_ensemble._FIN_RX) → a 0-100 score by hit breadth
_FIN_TERMS = _re.compile(
    r"\b(nav|premium|discount|cef|closed.?end|distribution|yield|income|covered call|dividend|"
    r"return of capital|\broc\b|coverage|earnings|valuation|drawdown|carry|beta|rebalance|allocation|"
    r"concentration|hedge|tilt|position siz|sizing|trim|protection|stop[- ]?loss|exposure|risk|"
    r"premarket|catalyst|breakout|support|resistance|rsi|volume|gap|rotation|sector|macro|fed|cpi|"
    r"earnings|guidance|downgrade|upgrade|target)\b", _re.I)
# retirement-context keywords → high / medium relevance (John is on SSDI, Golden-Window Roth strategy)
_RETIRE_HI = _re.compile(r"\b(roth|ira|ssdi|medicare|irmaa|mapt|golden.?window|rmd|annuit|sequence of returns)\b", _re.I)
_RETIRE_MD = _re.compile(r"\b(retire|retirement|income|distribution|drawdown|preservation|tax|estate|nav)\b", _re.I)


def _load_synthesis_maps() -> dict:
    """Refresh the sector/trend/ensemble lookup maps if the cache is stale. One small query each."""
    now = _time.time()
    if now - _SYN_CACHE["t"] < _SYN_TTL and _SYN_CACHE["sector"]:
        return _SYN_CACHE
    sector, trend, ensemble = {}, {}, {}
    try:
        cur = _conn().cursor()
        try:
            cur.execute("SELECT UPPER(symbol), sector FROM symbol_profiles WHERE sector IS NOT NULL AND sector <> ''")
            sector = {s: v for s, v in cur.fetchall()}
        except Exception:
            _conn().rollback()
        try:
            cur.execute("SELECT UPPER(symbol), trend FROM watchlist_items WHERE trend IS NOT NULL AND trend <> ''")
            trend = {s: v for s, v in cur.fetchall()}
        except Exception:
            _conn().rollback()
        try:
            # latest ensemble verdict per symbol-like subject (skip portfolio/region/theme subjects)
            cur.execute(
                "SELECT DISTINCT ON (UPPER(subject)) UPPER(subject), final_decision, final_score, "
                "consensus_reached, lanes_used FROM inference_ensemble_results "
                "WHERE subject ~ '^[A-Za-z]{1,5}$' ORDER BY UPPER(subject), created_at DESC")
            for sub, dec, score, cons, lanes in cur.fetchall():
                ensemble[sub] = {"decision": dec, "score": round(float(score), 1) if score is not None else None,
                                 "consensus": bool(cons), "lanes": list(lanes or [])}
        except Exception:
            _conn().rollback()
    except Exception:
        pass
    _SYN_CACHE.update({"t": now, "sector": sector, "trend": trend, "ensemble": ensemble})
    return _SYN_CACHE


def _finance_score(blob: str) -> int:
    """0-100 finance-substance score from distinct keyword breadth (deterministic, no LLM)."""
    if not blob:
        return 0
    hits = {m.group(0).lower() for m in _FIN_TERMS.finditer(blob)}
    return min(100, len(hits) * 14)   # ~7 distinct finance terms → saturates


def _retirement_relevance(blob: str) -> str | None:
    if not blob:
        return None
    if _RETIRE_HI.search(blob):
        return "high"
    if _RETIRE_MD.search(blob):
        return "medium"
    return None


def _attach_synthesis(it: dict) -> None:
    """Attach sector / trend / finance_score / retirement_relevance / ensemble to one item (honest, null-safe)."""
    maps = _load_synthesis_maps()
    syms = it.get("symbols") or ([it["symbol"]] if it.get("symbol") else [])
    sym = (syms[0] if syms else "") or ""
    sym = sym.upper()
    blob = f"{it.get('title') or ''} {it.get('summary') or ''}"
    it["sector"] = maps["sector"].get(sym)
    it["trend"] = maps["trend"].get(sym)
    it["finance_score"] = _finance_score(blob)
    it["retirement_relevance"] = _retirement_relevance(blob)
    it["ensemble"] = maps["ensemble"].get(sym)   # only when a real verdict exists for this symbol


_ACT_TICKER = _re.compile(r"\b([A-Z]{2,5})\b")
_ACT_STOP = {"A", "I", "AM", "PM", "ET", "EST", "EDT", "US", "USD", "CEO", "CFO", "ETF", "IRA", "LLM",
             "AI", "API", "EOD", "RSI", "ATR", "PNL", "TODO", "FYI", "OK", "NEW", "ALL", "ANY", "TBD",
             "GO", "WAIT", "BUY", "SELL", "HOLD", "RISK", "STOP", "HIGH", "LOW", "DAY", "WEEK", "NOTE",
             "NA", "GROK", "CIO", "EPS", "YOY", "QOQ", "ROI", "VIX", "SPY", "QQQ", "THE", "AND", "FOR",
             "WITH", "FROM", "THIS", "THAT", "WILL", "HAS", "ADD", "TRIM", "SAME"}

# action_class → (v3 route, label)
_ACT_ROUTE = {
    "stop_triggered": ("/v3/risk", "Risk"),
    "unprotected_position": ("/v3/risk", "Risk"),
    "risk_review": ("/v3/risk", "Risk"),
    "approval_needed": ("/v3/trading", "Trading"),
    "broker_manual": ("/v3/trading", "Trading"),
    "portfolio_review": ("/v3/portfolio", "Portfolio"),
    "research_needed": ("/v3/intelligence", "Intelligence"),
    "hermes_review": ("/v3/hermes", "Hermes"),
    "system_health": ("/v3/system", "System"),
    "cron_or_backup": ("/v3/system", "System"),
    "llm_review": ("/v3/system", "System"),
    "recovery": ("/v3/risk", "Recovery"),
    "informational": ("/v3/reports", "Reports"),
}

# ordered (action_class, base_severity, regex) — earlier = higher priority
_ACT_RULES = [
    # stop_triggered: TRUE trigger language only. The bare "stop-out" clause was removed — it fired on
    # recovery rows like "Relisted — No Stop-Out" (a NON-event). A negation guard (_NEG_STOP) also drops
    # any matched occurrence inside a negated sentence ("no stop loss triggered").
    ("stop_triggered", "urgent", _re.compile(
        r"\bstop(?:\(s\)|s)?\s+(?:were\s+)?(?:triggered|hit|fired|executed|filled)\b"
        r"|\b\d+\s+stop(?:\(s\)|s)?\s+triggered\b"
        r"|\btriggered\s+(?:a\s+)?stop\b"
        r"|\bprotective\s+stop\s+filled\b"
        r"|\bstop\s+filled\b"
        r"|\bstop[\s-]?loss\s+(?:order\s+)?(?:was\s+)?triggered\b"
        r"|\bposition\s+may\s+be\s+flat\b", _re.I)),
    # unprotected_position: requires explicit "without stops" / "unprotected" / "no protective stop".
    # The old bare "no stop" clause matched "No Stop-Out" — removed.
    ("unprotected_position", "urgent", _re.compile(
        r"\bunprotected\b"
        r"|\bwithout\s+(?:a\s+|protective\s+)?stops?\b"
        r"|\bno\s+protective\s+stop\b"
        r"|\blarge\s+positions?\s+without\s+stops?\b"
        r"|\bnaked\s+(?:stop|position)\b", _re.I)),
    ("approval_needed", "warning", _re.compile(r"\bapprov(?:e|al|als|ed)\b|\breview\s+queue\b|\bawaiting\s+(?:your\s+)?(?:approval|review|sign-?off)\b|\bpending\s+approval\b|\bone[\s-]?tap\b|\bneeds?\s+(?:your\s+)?(?:approval|sign-?off)\b", _re.I)),
    ("risk_review", "warning", _re.compile(r"\bprotective\s+stop\b|\bstop[\s-]?loss\b|\brisk\s+review\b|\bdrawdown\b|\bbreach(?:ed|es)?\b|\bstop\s+health\b|\bat\s+risk\b", _re.I)),
    ("hermes_review", "info", _re.compile(r"\bhermes\b|\bbacklog\b|\blibrarian\b|\bembedding\s+promotion\b|\bchallenger\b", _re.I)),
    ("cron_or_backup", "warning", _re.compile(r"\bbackup\b|\bcron\b|\bsnapshot\b|\bretention\b", _re.I)),
    ("system_health", "warning", _re.compile(r"\bsystem\s+health\b|\bhealth\s+check\b|\b(?:failed|failure|blocked|degraded|unhealthy|depleted|warmup\s+failed|stale\s+data)\b", _re.I)),
    ("llm_review", "info", _re.compile(r"\bLLM\b|\bgemma\b|\bgrok\b|\barbitration\b|\bmodel\s+(?:failed|warmup|coverage|disagree)\b", _re.I)),
    ("broker_manual", "warning", _re.compile(r"\bmanual\s+(?:execution|order|ticket)\b|\bplace\s+(?:the\s+)?order\b|\bbroker\s+ticket\b|\bToS\s+desk\b|\bSchwab\s+ticket\b", _re.I)),
    ("recovery", "info", _re.compile(r"reentry[_\s]?candidate|market[_\s]?relist|relist[_\s]?monitor|recovery\s+watch|hold[_\s]?for[_\s]?reentry|stay[_\s]?cash|/v2/recovery", _re.I)),
    ("portfolio_review", "info", _re.compile(r"\brebalanc\w*\b|\bdividend\b|\ballocation\b|\bdrift\b|\bregime\s+change\b|\blook[\s-]?through\b", _re.I)),
    ("research_needed", "info", _re.compile(r"\bresearch\b|\bintel\b|\binvestigat\w*\b|\bdue\s+diligence\b|\bcatalyst\b|research\s+gap", _re.I)),
]
_RISK_CLASSES = {"stop_triggered", "unprotected_position", "risk_review"}
_SEV_RANK = {"urgent": 3, "critical": 3, "warning": 2, "info": 1}

# Destination page (from an inline link in the matched line) → the canonical action_class, so the PILL
# matches where the link goes. A "stop-loss triggered → /v2/approvals" Steph-review item is an APPROVAL
# action (pill + tab + route all Approvals), not a Risk item that happens to link elsewhere. risk/recovery/
# journal keep their matched class (they genuinely are risk/recovery).
_PAGE_CLASS = {
    "approvals": "approval_needed", "trading": "approval_needed", "proposals": "approval_needed",
    "paper-proposals": "approval_needed", "paper-status": "approval_needed",
    "research": "research_needed", "research-topics": "research_needed",
    "system": "system_health", "alerts": "system_health", "siem": "system_health",
    "portfolio": "portfolio_review",
}

# Negation guard: an occurrence inside a sentence with this language is NOT a stop trigger (recovery-watch
# "Relisted — No Stop-Out", "not a stop-out", "no stop loss triggered"). Applied per-class in extract.
_NEG_STOP = _re.compile(
    r"\bno\s+stop[\s-]?out\b|\bnot\s+a\s+stop[\s-]?out\b|\bno\s+stop\s+loss\s+triggered\b"
    r"|relisted\s*[—\-]\s*no\s+stop\b|\bno\s+stop\s+out\b", _re.I)
# risk_review negation: "drawdown" / "stop-loss" inside a retirement-income-planning research phrase is NOT
# a portfolio risk event (e.g. "Tax-efficient retirement income drawdown" research gap).
_NEG_RISK = _re.compile(
    r"income\s+drawdown|retirement\s+(?:income\s+)?drawdown|drawdown\s+(?:strateg|sequenc|plan)"
    r"|withdrawal\s+sequenc|tax[\s-]?efficient|research\s+gap", _re.I)
_NEGATE = {"stop_triggered": _NEG_STOP, "risk_review": _NEG_RISK}


def _is_ticker(s) -> bool:
    return bool(s) and bool(_re.fullmatch(r"[A-Z]{1,5}", str(s).strip())) and str(s).strip() not in _ACT_STOP


def _symbol_near(line: str) -> str | None:
    """A ticker-like token on the matched line (for risk/stop lines lacking an explicit symbol)."""
    for m in _ACT_TICKER.finditer(line or ""):
        tok = m.group(1)
        if tok not in _ACT_STOP:
            return tok
    return None


import urllib.parse as _ulib


def _enc(s) -> str:
    return _ulib.quote((str(s) or "")[:90])


def _action_target(cls: str, line: str, sym: str | None, syms: list[str]) -> dict:
    """Resolve a CANONICAL target for an action — exact page + tab + drawer/modal when determinable, with a
    confidence + reason. Deterministic, no LLM. The UI deep-links to target.route and labels with route_label."""
    symq = f"symbol={sym}" if sym else ""
    if cls == "stop_triggered":
        if syms and len(syms) > 1:
            sl = ",".join(syms[:12])
            return {"target_type": "risk_stop", "target_id": sl, "symbol": sym,
                    "route": f"/v3/risk?symbols={sl}&drawer=stops", "route_label": f"Open {len(syms)} triggered stops",
                    "modal": "risk_stop_drawer", "endpoint": "/api/v2/risk", "target_confidence": "high",
                    "reason": f"stop-triggered line, {len(syms)} symbols"}
        return {"target_type": "risk_stop", "target_id": sym, "symbol": sym,
                "route": f"/v3/risk?{symq}&drawer=stop" if sym else "/v3/risk?drawer=stops",
                "route_label": f"Open {sym} stop detail" if sym else "Open triggered stops",
                "modal": "risk_stop_drawer", "endpoint": "/api/v2/risk",
                "target_confidence": "high" if sym else "medium", "reason": "stop-triggered line"}
    if cls == "unprotected_position":
        return {"target_type": "risk_stop", "target_id": sym, "symbol": sym,
                "route": f"/v3/risk?drawer=unprotected{('&' + symq) if sym else ''}",
                "route_label": f"Open {sym} (no stop)" if sym else "Open unprotected positions",
                "modal": "risk_unprotected_drawer", "endpoint": "/api/v2/risk", "target_confidence": "high",
                "reason": "unprotected / no-stop line"}
    if cls == "risk_review":
        return {"target_type": "risk_stop", "target_id": sym, "symbol": sym,
                "route": f"/v3/risk?{symq}&drawer=stop" if sym else "/v3/risk",
                "route_label": f"Open {sym} risk" if sym else "Open Risk", "modal": "risk_stop_drawer" if sym else None,
                "endpoint": "/api/v2/risk", "target_confidence": "high" if sym else "medium", "reason": "risk-review line"}
    if cls == "recovery":
        return {"target_type": "recovery", "target_id": sym, "symbol": sym,
                "route": f"/v3/risk?tab=Recovery{('&' + symq) if sym else ''}&drawer=recovery",
                "route_label": f"Open {sym} recovery detail" if sym else "Open Recovery", "modal": "recovery_drawer",
                "endpoint": "/api/v2/recovery", "target_confidence": "high" if sym else "medium", "reason": "recovery-watch line"}
    if cls == "approval_needed":
        return {"target_type": "approval", "target_id": sym, "symbol": sym,
                "route": f"/v3/trading?tab=Broker%20Proposals{('&' + symq) if sym else ''}&modal=approval",
                "route_label": f"Open {sym} approval" if sym else "Open Broker Proposals", "modal": "approval",
                "endpoint": "/api/v2/broker-proposals", "target_confidence": "medium" if sym else "low",
                "reason": "approval / Steph-review line (no exact approval id in source)"}
    if cls == "broker_manual":
        return {"target_type": "trading", "target_id": sym, "symbol": sym, "route": "/v3/trading?tab=Manual%20ToS",
                "route_label": "Open Manual ToS", "modal": None, "endpoint": None, "target_confidence": "medium",
                "reason": "broker-manual line"}
    if cls == "research_needed":
        topic = _re.sub(r"^.*?(?:gap|topic)\s*:?\s*", "", line, flags=_re.I).split("—")[0].strip()
        return {"target_type": "research", "target_id": None, "symbol": sym,
                "route": f"/v3/intelligence?tab=Research&query={_enc(topic)}&drawer=research", "route_label": "Open research focus",
                "modal": "research", "endpoint": "/api/v2/research-topics", "target_confidence": "medium",
                "reason": "research gap / topic line (Intelligence query focus)"}
    if cls == "hermes_review":
        flt = "backlog" if _re.search(r"backlog", line, _re.I) else "librarian" if _re.search(r"librarian", line, _re.I) else "embedding" if _re.search(r"embedding", line, _re.I) else ""
        tab = "Pipeline" if flt == "librarian" else "Provenance" if flt == "embedding" else "Research"
        return {"target_type": "hermes", "target_id": flt or None, "symbol": sym,
                "route": f"/v3/hermes?tab={tab}{('&filter=' + flt) if flt else ''}", "route_label": f"Open Hermes {tab}",
                "modal": None, "endpoint": None, "target_confidence": "medium", "reason": "hermes line"}
    if cls == "cron_or_backup":
        m = _re.search(r"\b([a-z0-9_]+\.(?:sh|py|service|timer))\b", line)
        return {"target_type": "system", "target_id": (m.group(1) if m else None), "symbol": None,
                "route": f"/v3/system?tab=Crons{('&query=' + _enc(m.group(1))) if m else ''}", "route_label": "Open Crons tab",
                "modal": None, "endpoint": None, "target_confidence": "high", "reason": "cron / backup line"}
    if cls == "llm_review":
        return {"target_type": "system", "target_id": None, "symbol": None, "route": "/v3/system?tab=LLM",
                "route_label": "Open LLM tab", "modal": None, "endpoint": None, "target_confidence": "high", "reason": "llm line"}
    if cls == "system_health":
        tab = "SIEM" if _re.search(r"siem|alert|breach|fatigue", line, _re.I) else "Brokers" if _re.search(r"broker|connector|schwab|alpaca|fidelity", line, _re.I) else "Data Sources" if _re.search(r"stale|source|feed|ingest", line, _re.I) else "Pipeline"
        return {"target_type": "system", "target_id": None, "symbol": None, "route": f"/v3/system?tab={_ulib.quote(tab)}",
                "route_label": f"Open {tab} tab", "modal": None, "endpoint": None, "target_confidence": "medium", "reason": "system-health line"}
    if cls == "portfolio_review":
        return {"target_type": "portfolio", "target_id": sym, "symbol": sym, "route": f"/v3/portfolio?{symq}" if sym else "/v3/portfolio",
                "route_label": f"Open {sym} in Portfolio" if sym else "Open Portfolio", "modal": None, "endpoint": "/api/v2/portfolio",
                "target_confidence": "medium", "reason": "portfolio line"}
    return {"target_type": "report", "target_id": None, "symbol": sym, "route": "/v3/reports",
            "route_label": "Open related page", "modal": None, "endpoint": None, "target_confidence": "low",
            "reason": "no explicit target resolved"}


def extract_action_items(item: dict) -> list[dict]:
    """Deterministically extract operator action items from one normalized report item. NO LLMs.
    Returns a list of routed action dicts (one per detected class, capped). [] if nothing actionable.
    Each action carries a canonical `target` object (see _action_target); top-level route/route_label are
    derived from it for backward compatibility."""
    text = f"{item.get('title') or ''}\n{item.get('summary') or ''}"
    if not text.strip():
        return []
    base_sev = (item.get("severity") or "info").lower()
    item_sym = item.get("symbol") if _is_ticker(item.get("symbol")) else None
    # a v3 route the report itself links to (existing _action_links) → preferred route for its actions
    own_route = None
    for a in (item.get("actions") or []):
        url = a.get("url") or ""
        m = _re.search(r"/v3/[a-z0-9-]+", url)
        if m:
            own_route = m.group(0)
            break
    rid = f"{item.get('source')}-{item.get('id')}"
    out, emitted = [], set()   # dedup by FINAL (out) class so a reclassified item never keeps a stale pill
    for action_class, rule_sev, rx in _ACT_RULES:
        # Find the first NON-negated occurrence: for guarded classes (stop_triggered), an occurrence whose
        # surrounding line carries negation language ("No Stop-Out") is skipped — if every occurrence is
        # negated the class isn't emitted at all.
        neg = _NEGATE.get(action_class)
        m, line = None, ""
        for cand in rx.finditer(text):
            cl_s = text.rfind("\n", 0, cand.start()) + 1
            cl_e = text.find("\n", cand.end())
            cand_line = text[cl_s:(cl_e if cl_e != -1 else len(text))]
            if neg and neg.search(cand_line):
                continue
            # stop_triggered: prefer the occurrence whose line carries the most tickers (the
            # "8 stop(s) TRIGGERED: PFLT, LHX, …" list line, not the bare "8 stops triggered" summary) so the
            # grouped multi-symbol drawer target resolves. Other classes take the first non-negated match.
            if action_class == "stop_triggered":
                nt = sum(1 for t in _ACT_TICKER.findall(cand_line) if _is_ticker(t))
                cur_nt = sum(1 for t in _ACT_TICKER.findall(line) if _is_ticker(t)) if m else -1
                if m is None or nt > cur_nt:
                    m, line = cand, cand_line.strip()[:200]
                continue
            m, line = cand, cand_line.strip()[:200]
            break
        if not m:
            continue
        # severity = stronger of the item's own severity and the rule's base severity
        sev = rule_sev if _SEV_RANK.get(rule_sev, 1) >= _SEV_RANK.get(base_sev, 1) else base_sev
        if sev == "critical":
            sev = "urgent"
        out_class = action_class
        sym = item_sym or (_symbol_near(line) if action_class in _RISK_CLASSES else None)
        # All tickers on the line (for grouped multi-symbol stop targets, e.g. "8 stops TRIGGERED: A, B, C…").
        syms = [t for t in _ACT_TICKER.findall(line or "") if _is_ticker(t)]
        # The destination the matched LINE names (e.g. "→ /v2/approvals") drives the pill CLASS — so a
        # Steph-review item that merely mentions a stop is an Approval (pill + tab + Approvals), not Risk.
        _ml = _re.search(r"/v[23]/([a-z0-9-]+)", line)
        if _ml and _ml.group(1) in _PAGE_CLASS:
            out_class = _PAGE_CLASS[_ml.group(1)]
        elif _ml and _ml.group(1) in ("recovery", "reco"):
            out_class = "recovery"
        _key = (out_class, (sym or "").upper())   # dedup by class+SYMBOL → keep per-symbol actions distinct
        if _key in emitted:
            continue
        emitted.add(_key)
        # Canonical target — exact page+tab+drawer/modal + confidence. route/route_label derive from it.
        target = _action_target(out_class, line, sym if (sym and _is_ticker(sym)) else None, syms)
        out.append({
            "id": f"{rid}-{out_class}", "report_id": rid, "source": item.get("source"),
            "category": item.get("category"), "title": item.get("title"), "action_class": out_class,
            "severity": sev, "symbol": sym, "route": target["route"], "route_label": target["route_label"],
            "target": target, "text": line or (item.get("title") or "")[:200],
            "created_at": item.get("created_at"), "status": "open",
        })
        if len(out) >= 4:
            break
    return out


def _enrich_item(it: dict) -> dict:
    """Phase 3 — attach cheap action metadata to a list item (computed per-page only)."""
    acts = extract_action_items(it)
    classes, syms = [], []
    routes = set()
    for a in acts:
        if a["action_class"] not in classes:
            classes.append(a["action_class"])
        if a.get("symbol") and a["symbol"] not in syms:
            syms.append(a["symbol"])
        routes.add(a["route"])
    it["action_count"] = len(acts)
    it["action_classes"] = classes
    it["symbols"] = syms or ([it["symbol"]] if it.get("symbol") else [])
    it["has_actions"] = bool(acts)
    it["route_count"] = len(routes)
    _attach_synthesis(it)   # sector/trend/finance_score/retirement_relevance/ensemble (cheap, per-page)
    blob = it.get("summary") or ""
    m = _re.search(r"(?:#{1,2}\s*)?Executive\s+Summary\s*\n+([^\n#]+)", blob, _re.I)
    if m:
        it["synthesized_insight"] = _re.sub(r"\s+", " ", m.group(1).strip())[:280]
    elif blob.strip():
        flat = _re.sub(r"\s+", " ", blob.strip())
        sm = _re.match(r".{40,240}?[.!?](?:\s|$)", flat)
        it["synthesized_insight"] = (sm.group(0) if sm else flat[:200]).strip()
    docx = _resolve_docx(it)
    if docx:
        it["docx_file"] = docx
    return it


def _nl_where(cat) -> tuple[str, list]:
    types = cat.get("nl_types") or []
    if not types:
        return ("FALSE", [])
    return ("notification_type = ANY(%s)", [types])


def _ae_where(cat) -> tuple[str, list] | None:
    ae = cat.get("ae")
    if not ae:
        return None
    clauses, params = [], []
    if ae.get("alert_type"):
        clauses.append("alert_type = ANY(%s)"); params.append(ae["alert_type"])
    if ae.get("source_script"):
        clauses.append("source_script = ANY(%s)"); params.append(ae["source_script"])
    if ae.get("exclude_source"):
        clauses.append("(source_script IS NULL OR NOT (source_script = ANY(%s)))"); params.append(ae["exclude_source"])
    return ((" AND ".join(clauses) or "TRUE"), params)


def _ob_where(cat) -> tuple[str, list] | None:
    """telegram_outbox filter (recognized reports captured at the Telegram send chokepoint)."""
    types = cat.get("ob_types") or []
    if not types:
        return None
    return ("report_type = ANY(%s)", [types])


def _ar_where(cat) -> tuple[str, list] | None:
    """ai_reports filter (LLM-generated monthly/weekly reports)."""
    types = cat.get("ar_types") or []
    if not types:
        return None
    return ("report_type = ANY(%s)", [types])


def categories() -> dict:
    """All portal categories with counts + last-activity date (cheap GROUP BY queries)."""
    cur = _conn().cursor()
    nl_counts, ae_counts = {}, {}
    try:
        cur.execute("SELECT notification_type, count(*), max(created_at) FROM notification_log GROUP BY 1")
        for t, n, last in cur.fetchall():
            nl_counts[t] = (n, last)
    except Exception:
        pass
    out = []
    for c in CATEGORIES:
        total, last = 0, None
        for t in (c.get("nl_types") or []):
            if t in nl_counts:
                total += nl_counts[t][0]
                last = max(last, nl_counts[t][1]) if last and nl_counts[t][1] else (last or nl_counts[t][1])
        aw = _ae_where(c)
        if aw:
            try:
                cur.execute(f"SELECT count(*), max(created_at) FROM alert_events WHERE {aw[0]}", aw[1])
                n, l = cur.fetchone()
                total += int(n or 0)
                last = max(last, l) if (last and l) else (last or l)
            except Exception:
                pass
        ow = _ob_where(c)
        if ow:
            try:
                cur.execute(f"SELECT count(*), max(sent_at) FROM telegram_outbox WHERE {ow[0]}", ow[1])
                n, l = cur.fetchone()
                total += int(n or 0)
                last = max(last, l) if (last and l) else (last or l)
            except Exception:
                pass
        rw = _ar_where(c)
        if rw:
            try:
                cur.execute(f"SELECT count(*), max(generated_at) FROM ai_reports WHERE {rw[0]}", rw[1])
                n, l = cur.fetchone()
                total += int(n or 0)
                last = max(last, l) if (last and l) else (last or l)
            except Exception:
                pass
        out.append({"key": c["key"], "label": c["label"], "icon": c["icon"], "count": total,
                    "last_at": last.isoformat() if last else None})
    return {"categories": out, "total": sum(c["count"] for c in out)}


def _category_rows(cat: dict, q: str = "", days: int | None = None) -> list:
    """Build normalized, UNANNOTATED rows for one category (UNION of all stores). Raw datetime
    created_at preserved (caller isoformats). Shared by list_items / portal_summary / action_items."""
    category = cat["key"]
    cur = _conn().cursor()
    rows = []
    daycut = f" AND created_at > NOW() - INTERVAL '{int(days)} days'" if days else ""
    like = f"%{q.strip()}%" if q and q.strip() else None

    # notification_log
    nlw, nlp = _nl_where(cat)
    if nlw != "FALSE":
        sql = (f"SELECT id, created_at, notification_type, channel, subject, body_summary, status, payload "
               f"FROM notification_log WHERE {nlw}{daycut}")
        if like:
            sql += " AND (subject ILIKE %s OR body_summary ILIKE %s)"; nlp = nlp + [like, like]
        sql += " ORDER BY created_at DESC LIMIT 500"
        try:
            cur.execute(sql, nlp)
            for r in cur.fetchall():
                full = _full_body(r[7], r[5] or "")   # load the complete brief/digest from payload.export
                rows.append({"source": "nl", "id": r[0], "created_at": r[1], "category": category,
                             "type": r[2], "channel": r[3], "title": r[4] or r[2], "summary": full,
                             "severity": _sev_from_nl(r[2]), "symbol": None, "status": r[6],
                             "actions": _action_links(full), "acknowledged": (r[6] == "read")})
        except Exception:
            pass

    # alert_events
    aw = _ae_where(cat)
    if aw:
        sql = (f"SELECT id, created_at, alert_type, source_script, symbol, severity, raw_text, parsed_payload, "
               f"lifecycle_state, acknowledged_at FROM alert_events WHERE {aw[0]}{daycut}")
        ap = list(aw[1])
        if like:
            sql += " AND (raw_text ILIKE %s OR symbol ILIKE %s)"; ap += [like, like]
        sql += " ORDER BY created_at DESC LIMIT 500"
        try:
            cur.execute(sql, ap)
            for r in cur.fetchall():
                txt = r[6] or ""
                title = (txt.split("\n")[0] or r[2])[:120]
                rows.append({"source": "ae", "id": r[0], "created_at": r[1], "category": category,
                             "type": r[3] or r[2], "channel": "siem", "title": title, "summary": txt,
                             "severity": (r[5] or "info"), "symbol": r[4], "status": r[8],
                             "actions": _action_links(txt), "acknowledged": bool(r[9])})
        except Exception:
            pass

    # telegram_outbox (reports captured at the send chokepoint)
    ow = _ob_where(cat)
    if ow:
        obcut = f" AND sent_at > NOW() - INTERVAL '{int(days)} days'" if days else ""
        sql = (f"SELECT id, sent_at, report_type, title, body, channel, ok FROM telegram_outbox "
               f"WHERE {ow[0]}{obcut}")
        op = list(ow[1])
        if like:
            sql += " AND (title ILIKE %s OR body ILIKE %s)"; op += [like, like]
        sql += " ORDER BY sent_at DESC LIMIT 500"
        try:
            cur.execute(sql, op)
            for r in cur.fetchall():
                body = r[4] or ""
                rows.append({"source": "ob", "id": r[0], "created_at": r[1], "category": category,
                             "type": r[2], "channel": r[5] or "telegram", "title": r[3] or r[2], "summary": body,
                             "severity": "info", "symbol": None, "status": ("sent" if r[6] else "failed"),
                             "actions": _action_links(body), "acknowledged": True})
        except Exception:
            pass

    # ai_reports (LLM-generated monthly/weekly reports)
    rw = _ar_where(cat)
    if rw:
        arcut = f" AND generated_at > NOW() - INTERVAL '{int(days)} days'" if days else ""
        sql = (f"SELECT id, generated_at, report_type, title, content, provider FROM ai_reports "
               f"WHERE {rw[0]}{arcut}")
        rp = list(rw[1])
        if like:
            sql += " AND (title ILIKE %s OR content ILIKE %s)"; rp += [like, like]
        sql += " ORDER BY generated_at DESC LIMIT 500"
        try:
            cur.execute(sql, rp)
            for r in cur.fetchall():
                content = r[4] or ""
                rows.append({"source": "ar", "id": r[0], "created_at": r[1], "category": category,
                             "type": r[2], "channel": r[5] or "local", "title": r[3] or r[2], "summary": content,
                             "severity": "info", "symbol": None, "status": "generated",
                             "actions": _action_links(content), "acknowledged": True})
        except Exception:
            pass

    return _dedup_rows(rows)


def _dedup_rows(rows: list) -> list:
    """Collapse near-identical repeated rows — e.g. a stop-health alert re-emitted every poll for the SAME
    order (IRDM fired ~18×, flooding the list + Top-symbols). Key = symbol + source + normalized first
    ~120 chars of title/summary with volatile clock tokens stripped, so re-emits collapse but genuinely
    distinct items (different days/bodies) don't. Each source's rows arrive created_at DESC, so the first
    occurrence kept is the most recent; the rest just bump repeat_count for a 'x N' badge."""
    seen: dict = {}
    out: list = []
    for it in rows:
        base = (it.get("title") or it.get("summary") or "")[:120]
        base = _re.sub(r"\s+", " ", base).strip().lower()
        base = _re.sub(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\b", "", base)   # drop times so re-emits match
        key = f"{(it.get('symbol') or '').upper()}|{it.get('source')}|{base}"
        if key in seen:
            seen[key]["repeat_count"] = seen[key].get("repeat_count", 1) + 1
            continue
        it["repeat_count"] = 1
        seen[key] = it
        out.append(it)
    return out


def search_items(q: str = "", days: int | None = 30, limit: int = 25) -> dict:
    """Cross-category search across all portal stores (Telegram, notification_log, SIEM, ai_reports)."""
    q = (q or "").strip()
    if not q:
        return {"items": [], "total": 0, "q": q}
    limit = min(50, max(5, int(limit)))
    days = int(days) if days else 30
    rows = _gather_rows(category=None, q=q, days=days, per_cat_cap=80)
    rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    total = len(rows)
    items = rows[:limit]
    cat_label = {c["key"]: c["label"] for c in CATEGORIES}
    for it in items:
        it["created_at"] = it["created_at"].isoformat() if it.get("created_at") else None
        it["category_label"] = cat_label.get(it.get("category"), it.get("category"))
        _enrich_item(it)
    return {"items": items, "total": total, "q": q, "days": days}


def list_items(category: str, q: str = "", page: int = 1, per_page: int = 25, days: int | None = None) -> dict:
    """Normalized, paginated, searchable items for one category (UNION of all stores)."""
    cat = _BY_KEY.get(category)
    if not cat:
        return {"items": [], "total": 0, "page": 1, "pages": 0, "error": "unknown category"}
    page = max(1, int(page)); per_page = min(100, max(5, int(per_page)))
    rows = _category_rows(cat, q=q, days=days)
    rows.sort(key=lambda x: x["created_at"] or "", reverse=True)
    total = len(rows)
    start = (page - 1) * per_page
    items = rows[start:start + per_page]
    for it in items:
        it["created_at"] = it["created_at"].isoformat() if it["created_at"] else None
        _enrich_item(it)   # Phase 3: action_count/classes/symbols/has_actions/route_count (per-page only)
    return {"items": items, "total": total, "page": page, "per_page": per_page,
            "pages": (total + per_page - 1) // per_page}


def _gather_rows(category: str | None = None, q: str = "", days: int | None = 7, per_cat_cap: int = 200) -> list:
    """Normalized rows across one or all categories (for summary/action aggregation)."""
    cats = [_BY_KEY[category]] if (category and category in _BY_KEY) else CATEGORIES
    out = []
    for c in cats:
        try:
            out.extend(_category_rows(c, q=q, days=days)[:per_cat_cap])
        except Exception:
            continue
    return out


def portal_summary(days: int = 7) -> dict:
    """KPI roll-up for the portal header: totals + counts by category / severity / source / action_class,
    top mentioned symbols, headline counters, and a few most-recent items. Read-only, deterministic."""
    days = int(days) if days else 7
    rows = _gather_rows(category=None, q="", days=days, per_cat_cap=300)
    by_cat, by_sev, by_src, by_class = {}, {}, {}, {}
    sym_count = {}
    open_actions = risk_stop = approvals = system_hermes = crit_urgent = today = 0
    from datetime import datetime, timezone
    today_d = datetime.now(timezone.utc).date()
    recent = []
    for it in rows:
        cat = it.get("category"); by_cat[cat] = by_cat.get(cat, 0) + 1
        sev = (it.get("severity") or "info").lower(); by_sev[sev] = by_sev.get(sev, 0) + 1
        src = it.get("source"); by_src[src] = by_src.get(src, 0) + 1
        if sev in ("urgent", "critical"):
            crit_urgent += 1
        ca = it.get("created_at")
        if ca and hasattr(ca, "date") and ca.date() == today_d:
            today += 1
        acts = extract_action_items(it)
        for a in acts:
            open_actions += 1
            by_class[a["action_class"]] = by_class.get(a["action_class"], 0) + 1
            if a["action_class"] in _RISK_CLASSES:
                risk_stop += 1
            if a["action_class"] in ("approval_needed", "broker_manual"):
                approvals += 1
            if a["action_class"] in ("system_health", "cron_or_backup", "llm_review", "hermes_review"):
                system_hermes += 1
            if _is_ticker(a.get("symbol")):
                sym_count[a["symbol"]] = sym_count.get(a["symbol"], 0) + 1
        if _is_ticker(it.get("symbol")):
            sym_count[it["symbol"]] = sym_count.get(it["symbol"], 0) + 1
    rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    for it in rows[:8]:
        recent.append({"source": it.get("source"), "id": it.get("id"), "title": it.get("title"),
                       "category": it.get("category"), "severity": it.get("severity"),
                       "created_at": it["created_at"].isoformat() if it.get("created_at") else None})
    cat_label = {c["key"]: c["label"] for c in CATEGORIES}
    top_symbols = sorted(({"symbol": s, "count": n} for s, n in sym_count.items()),
                         key=lambda x: x["count"], reverse=True)[:12]
    return {
        "days": days, "total": len(rows),
        "kpis": {"total": len(rows), "critical_urgent": crit_urgent, "open_actions": open_actions,
                 "risk_stop": risk_stop, "approvals": approvals, "system_hermes": system_hermes,
                 "today": today},
        "by_category": [{"key": k, "label": cat_label.get(k, k), "count": v}
                        for k, v in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)],
        "by_severity": by_sev, "by_source": by_src,
        "by_action_class": [{"action_class": k, "count": v}
                            for k, v in sorted(by_class.items(), key=lambda x: x[1], reverse=True)],
        "top_symbols": top_symbols, "recent": recent,
    }


def action_items(category: str | None = None, q: str = "", days: int | None = 7, limit: int = 100,
                 classes: str | None = None, severity: str | None = None) -> dict:
    """Flattened, deterministically extracted action items across categories, each routed to a v3 page.
    Optional server-side filters (so quick views stay exact regardless of limit / day range):
      classes  — comma-separated action_class names (e.g. 'stop_triggered,risk_review')
      severity — comma-separated severities (e.g. 'urgent,critical')."""
    days = int(days) if days else None
    want_cls = {c.strip() for c in (classes or "").split(",") if c.strip()} or None
    want_sev = {s.strip().lower() for s in (severity or "").split(",") if s.strip()} or None
    rows = _gather_rows(category=category, q=q, days=days, per_cat_cap=300)
    actions, by_class = [], {}
    for it in rows:
        ca = it.get("created_at")
        it["created_at"] = ca.isoformat() if (ca and hasattr(ca, "isoformat")) else ca
        for a in extract_action_items(it):
            if want_cls and a["action_class"] not in want_cls:
                continue
            if want_sev and (a.get("severity") or "info").lower() not in want_sev:
                continue
            actions.append(a)
            by_class[a["action_class"]] = by_class.get(a["action_class"], 0) + 1
    actions.sort(key=lambda a: (_SEV_RANK.get((a.get("severity") or "info").lower(), 1),
                                a.get("created_at") or ""), reverse=True)
    return {"actions": actions[:int(limit)], "total": len(actions), "by_class": by_class,
            "category": category or "all", "days": days,
            "classes": sorted(want_cls) if want_cls else None,
            "severity": sorted(want_sev) if want_sev else None}


def get_item(source: str, item_id) -> dict:
    cur = _conn().cursor()
    try:
        if source == "nl":
            cur.execute("SELECT id, created_at, notification_type, channel, subject, body_summary, status, "
                        "payload, sent_at, dedupe_key FROM notification_log WHERE id=%s", (int(item_id),))
            r = cur.fetchone()
            if not r:
                return {"error": "not found"}
            full = _full_body(r[7], r[5] or "")
            return {"source": "nl", "id": r[0], "created_at": str(r[1]), "type": r[2], "channel": r[3],
                    "title": r[4], "summary": full, "status": r[6], "payload": r[7], "sent_at": str(r[8]),
                    "actions": _action_links(full)}
        elif source == "ob":
            cur.execute("SELECT id, sent_at, report_type, title, body, channel, ok FROM telegram_outbox WHERE id=%s",
                        (int(item_id),))
            r = cur.fetchone()
            if not r:
                return {"error": "not found"}
            body = r[4] or ""
            return {"source": "ob", "id": r[0], "created_at": str(r[1]), "type": r[2], "channel": r[5] or "telegram",
                    "title": r[3], "summary": body, "status": ("sent" if r[6] else "failed"),
                    "actions": _action_links(body)}
        elif source == "ar":
            cur.execute("SELECT id, generated_at, report_type, title, content, provider FROM ai_reports WHERE id=%s",
                        (int(item_id),))
            r = cur.fetchone()
            if not r:
                return {"error": "not found"}
            content = r[4] or ""
            return {"source": "ar", "id": r[0], "created_at": str(r[1]), "type": r[2], "channel": r[5] or "local",
                    "title": r[3], "summary": content, "status": "generated", "actions": _action_links(content)}
        else:
            cur.execute("SELECT id, created_at, alert_type, source_script, symbol, severity, raw_text, "
                        "parsed_payload, lifecycle_state, acknowledged_at FROM alert_events WHERE id=%s", (int(item_id),))
            r = cur.fetchone()
            if not r:
                return {"error": "not found"}
            return {"source": "ae", "id": r[0], "created_at": str(r[1]), "type": r[3] or r[2], "symbol": r[4],
                    "severity": r[5], "title": (r[6] or "").split("\n")[0][:120], "summary": r[6],
                    "payload": r[7], "status": r[8], "acknowledged": bool(r[9]), "actions": _action_links(r[6] or "")}
    except Exception as e:
        return {"error": str(e)[:120]}


def purge(category: str | None = None, older_than_days: int = 90, apply: bool = False) -> dict:
    """Delete reports older than N days (optionally one category). Dry-run counts unless apply=True."""
    cat = _BY_KEY.get(category) if category else None
    conn = _conn(); cur = conn.cursor()
    cut = f"created_at < NOW() - INTERVAL '{int(older_than_days)} days'"
    deleted = {"notification_log": 0, "alert_events": 0, "telegram_outbox": 0, "ai_reports": 0}

    def _do(table, where, params, ts_col):
        tcut = f"{ts_col} < NOW() - INTERVAL '{int(older_than_days)} days'"
        if apply:
            cur.execute(f"DELETE FROM {table} WHERE {where} AND {tcut}", params)
            return cur.rowcount
        cur.execute(f"SELECT count(*) FROM {table} WHERE {where} AND {tcut}", params)
        return cur.fetchone()[0]

    try:
        # notification_log
        nlw, nlp = _nl_where(cat) if cat else ("TRUE", [])
        if nlw != "FALSE":
            deleted["notification_log"] = _do("notification_log", nlw, nlp, "created_at")
        # alert_events
        aw = _ae_where(cat) if cat else ("TRUE", [])
        if aw:
            deleted["alert_events"] = _do("alert_events", aw[0], aw[1], "created_at")
        # telegram_outbox (only if category targets it, or purging all)
        ow = _ob_where(cat) if cat else ("TRUE", [])
        if ow:
            try:
                deleted["telegram_outbox"] = _do("telegram_outbox", ow[0], ow[1], "sent_at")
            except Exception:
                pass  # table may not exist yet (no captures)
        # ai_reports
        rw = _ar_where(cat) if cat else ("TRUE", [])
        if rw:
            deleted["ai_reports"] = _do("ai_reports", rw[0], rw[1], "generated_at")
        if apply:
            conn.commit()
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)[:150]}
    return {"ok": True, "mode": "applied" if apply else "preview", "older_than_days": older_than_days,
            "category": category or "all", "deleted": deleted, "total": sum(deleted.values())}


def _verify_actions() -> int:
    """Deterministic verification of the action classifier (Phase 1 false-positive fixes). No DB/LLM.
    Run: python3 scripts/reports_portal.py --verify"""
    def classes(title, summary=""):
        item = {"source": "t", "id": 0, "title": title, "summary": summary,
                "severity": "info", "symbol": None, "actions": []}
        return {a["action_class"] for a in extract_action_items(item)}
    cases = [
        # (text, must_NOT_contain, must_contain)
        ("RTX recovery watch. Verdict: Reentry Candidate. Analyst: Relisted — No Stop-Out. "
         "Market reconnection event (relist #0).", {"stop_triggered", "unprotected_position"}, set()),
        ("8 stops triggered: PFLT, LHX, LMT.", set(), {"stop_triggered"}),
        ("6 large positions without stops ($222,160 total).", set(), {"unprotected_position"}),
        ("stop FILLED — position may be flat", set(), {"stop_triggered"}),
        ("cron failed during nightly backup", set(), {"system_health"}),
        ("no stop loss triggered overnight", {"stop_triggered"}, set()),
        # retirement-income-drawdown research is NOT a risk event
        ("Research gap: Tax-efficient retirement income drawdown — zero_articles", {"risk_review"}, set()),
    ]
    ok = True
    for text, must_not, must in cases:
        got = classes(text)
        bad = must_not & got
        miss = must - got
        status = "PASS" if (not bad and not miss) else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"  [{status}] {text[:52]!r:54} -> {sorted(got)}"
              + (f"  UNEXPECTED:{sorted(bad)}" if bad else "")
              + (f"  MISSING:{sorted(miss)}" if miss else ""))
    # ── Canonical target-contract checks (Phase 5) ──────────────────────────────────────────────────────
    def acts_of(title):
        return extract_action_items({"source": "t", "id": 0, "title": title, "summary": "",
                                     "severity": "info", "symbol": None, "actions": []})

    def check(name, cond, detail=""):
        nonlocal ok
        if not cond:
            ok = False
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")

    # 3) approval line -> /v3/trading ...modal=approval, NOT risk
    a = next((x for x in acts_of("CACI: The stop-loss order was triggered → /v2/approvals") if x["action_class"] == "approval_needed"), None)
    check("approval line -> trading modal", bool(a) and a["route"].startswith("/v3/trading?tab=Broker") and "modal=approval" in a["route"] and a["target"]["target_type"] == "approval", a["route"] if a else "none")
    check("approval line carries no risk pill", not any(x["action_class"] in _RISK_CLASSES for x in acts_of("CACI: The stop-loss order was triggered → /v2/approvals")))

    # 4) stop line -> /v3/risk ...drawer=stop(s)
    a = next((x for x in acts_of("8 stop(s) TRIGGERED: PFLT, LHX, LMT. Check /v2/risk immediately.") if x["action_class"] == "stop_triggered"), None)
    check("stop line -> risk drawer=stops + symbols", bool(a) and a["route"].startswith("/v3/risk?symbols=") and "drawer=stops" in a["route"] and a["target"]["target_type"] == "risk_stop", a["route"] if a else "none")

    # 5) recovery line -> /v3/risk?tab=Recovery
    a = next((x for x in acts_of("RTX: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery") if x["action_class"] == "recovery"), None)
    check("recovery line -> risk tab=Recovery", bool(a) and "tab=Recovery" in a["route"] and "drawer=recovery" in a["route"] and a["target"]["target_type"] == "recovery", a["route"] if a else "none")

    # 6) research-topics -> /v3/intelligence
    a = next((x for x in acts_of("Research gap: Defense sector rotation → /v2/research-topics") if x["action_class"] == "research_needed"), None)
    check("research line -> intelligence", bool(a) and a["route"].startswith("/v3/intelligence") and a["target"]["target_type"] == "research", a["route"] if a else "none")

    # 7) cron line -> /v3/system?tab=Crons
    a = next((x for x in acts_of("backup_secrets_state.sh cron failed during nightly backup") if x["action_class"] == "cron_or_backup"), None)
    check("cron line -> system tab=Crons", bool(a) and "tab=Crons" in a["route"] and a["target"]["target_type"] == "system", a["route"] if a else "none")

    # 8 & 9) every action has a target; every high-confidence target has a non-empty route+label
    allacts = (acts_of("8 stop(s) TRIGGERED: PFLT, LHX. Check /v2/risk") + acts_of("CACI → /v2/approvals")
               + acts_of("RTX: reentry_candidate → /v2/recovery") + acts_of("cron.sh failed"))
    check("every action has a target object", all("target" in x and isinstance(x["target"], dict) for x in allacts))
    check("high-confidence targets have route+label", all(x["target"]["route"] and x["target"]["route_label"]
          for x in allacts if x["target"]["target_confidence"] == "high"))

    # 10) no action defaults to /v3/risk unless the line is genuinely risk/stop/unprotected
    nonrisk = acts_of("Defense sector rotation research → /v2/research-topics") + acts_of("backup.sh cron failed")
    check("no spurious /v3/risk default", all(not x["route"].startswith("/v3/risk") for x in nonrisk))

    print("✓ all action-classifier + target checks passed" if ok else "✗ checks FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _sys
    if "--verify" in _sys.argv:
        raise SystemExit(_verify_actions())
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    import json
    print(json.dumps(categories(), indent=2, default=str))
