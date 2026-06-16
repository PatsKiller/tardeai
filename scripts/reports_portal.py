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


def list_items(category: str, q: str = "", page: int = 1, per_page: int = 25, days: int | None = None) -> dict:
    """Normalized, paginated, searchable items for one category (UNION of both stores)."""
    cat = _BY_KEY.get(category)
    if not cat:
        return {"items": [], "total": 0, "page": 1, "pages": 0, "error": "unknown category"}
    page = max(1, int(page)); per_page = min(100, max(5, int(per_page)))
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

    rows.sort(key=lambda x: x["created_at"] or "", reverse=True)
    total = len(rows)
    start = (page - 1) * per_page
    items = rows[start:start + per_page]
    for it in items:
        it["created_at"] = it["created_at"].isoformat() if it["created_at"] else None
    return {"items": items, "total": total, "page": page, "per_page": per_page,
            "pages": (total + per_page - 1) // per_page}


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


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    import json
    print(json.dumps(categories(), indent=2, default=str))
