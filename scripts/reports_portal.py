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
    "informational": ("/v3/reports", "Reports"),
}

# ordered (action_class, base_severity, regex) — earlier = higher priority
_ACT_RULES = [
    # stop_triggered: TRUE trigger language only. The bare "stop-out" clause was removed — it fired on
    # recovery rows like "Relisted — No Stop-Out" (a NON-event). A negation guard (_NEG_STOP) also drops
    # any matched occurrence inside a negated sentence ("no stop loss triggered").
    ("stop_triggered", "urgent", _re.compile(
        r"\bstops?\s+(?:were\s+)?(?:triggered|hit|fired|executed|filled)\b"
        r"|\b\d+\s+stops?\s+triggered\b"
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
    ("portfolio_review", "info", _re.compile(r"\brebalanc\w*\b|\bdividend\b|\ballocation\b|\bdrift\b|\bregime\s+change\b|\blook[\s-]?through\b", _re.I)),
    ("research_needed", "info", _re.compile(r"\bresearch\b|\bintel\b|\binvestigat\w*\b|\bdue\s+diligence\b|\bcatalyst\b", _re.I)),
]
_RISK_CLASSES = {"stop_triggered", "unprotected_position", "risk_review"}
_SEV_RANK = {"urgent": 3, "critical": 3, "warning": 2, "info": 1}

# Negation guard: an occurrence inside a sentence with this language is NOT a stop trigger (recovery-watch
# "Relisted — No Stop-Out", "not a stop-out", "no stop loss triggered"). Applied per-class in extract.
_NEG_STOP = _re.compile(
    r"\bno\s+stop[\s-]?out\b|\bnot\s+a\s+stop[\s-]?out\b|\bno\s+stop\s+loss\s+triggered\b"
    r"|relisted\s*[—\-]\s*no\s+stop\b|\bno\s+stop\s+out\b", _re.I)
_NEGATE = {"stop_triggered": _NEG_STOP}


def _is_ticker(s) -> bool:
    return bool(s) and bool(_re.fullmatch(r"[A-Z]{1,5}", str(s).strip())) and str(s).strip() not in _ACT_STOP


def _symbol_near(line: str) -> str | None:
    """A ticker-like token on the matched line (for risk/stop lines lacking an explicit symbol)."""
    for m in _ACT_TICKER.finditer(line or ""):
        tok = m.group(1)
        if tok not in _ACT_STOP:
            return tok
    return None


def extract_action_items(item: dict) -> list[dict]:
    """Deterministically extract operator action items from one normalized report item. NO LLMs.
    Returns a list of routed action dicts (one per detected class, capped). [] if nothing actionable."""
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
    out, used = [], set()
    for action_class, rule_sev, rx in _ACT_RULES:
        if action_class in used:
            continue
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
            m, line = cand, cand_line.strip()[:200]
            break
        if not m:
            continue
        used.add(action_class)
        # severity = stronger of the item's own severity and the rule's base severity
        sev = rule_sev if _SEV_RANK.get(rule_sev, 1) >= _SEV_RANK.get(base_sev, 1) else base_sev
        if sev == "critical":
            sev = "urgent"
        sym = item_sym or (_symbol_near(line) if action_class in _RISK_CLASSES else None)
        route, route_label = _ACT_ROUTE.get(action_class, ("/v3/reports", "Reports"))
        if action_class == "informational" and own_route:
            route = own_route
        out.append({
            "id": f"{rid}-{action_class}", "report_id": rid, "source": item.get("source"),
            "category": item.get("category"), "title": item.get("title"), "action_class": action_class,
            "severity": sev, "symbol": sym, "route": route, "route_label": route_label,
            "text": line or (item.get("title") or "")[:200],
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
    print("✓ all action-classifier checks passed" if ok else "✗ action-classifier checks FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _sys
    if "--verify" in _sys.argv:
        raise SystemExit(_verify_actions())
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    import json
    print(json.dumps(categories(), indent=2, default=str))
