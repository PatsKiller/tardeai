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
    {"key": "morning_briefs", "label": "Morning Briefs", "icon": "🛡", "nl_types": ["aegis_morning_brief"], "ae": None},
    {"key": "digests",        "label": "Digests",        "icon": "📰", "nl_types": ["daily_digest"], "ae": None},
    {"key": "alerts",         "label": "Alerts",         "icon": "🚨", "nl_types": ["urgent_alert", "info", "draft_alert", "alert_fatigue_meta", "stale_data_alert"],
     "ae": {"alert_type": ["strategic_alert", "analyst_alert"], "exclude_source": ["protective_stop", "protection_alerts", "stop_health", "portfolio_alerts"]}},
    {"key": "advisories",     "label": "Advisories",     "icon": "🧭", "nl_types": [], "ae": {"source_script": ["protective_stop", "protection_alerts", "stop_health", "portfolio_alerts"]}},
    {"key": "recovery",       "label": "Recovery Watch", "icon": "♻️", "nl_types": ["recovery_escalation"], "ae": None},
    {"key": "dividends",      "label": "Dividends",      "icon": "💰", "nl_types": ["dividend_alert"], "ae": None},
    {"key": "regime",         "label": "Regime / Rebalance", "icon": "📊", "nl_types": ["regime_change", "rebalance_stale"], "ae": None},
    {"key": "paper",          "label": "Paper Trading",  "icon": "📝", "nl_types": ["paper_trade_monitor"], "ae": None},
    {"key": "system",         "label": "System Health",  "icon": "⚙️", "nl_types": ["api_credits_depleted", "backup_verification", "LLM_WARMUP_FAILED"],
     "ae": {"alert_type": ["system_health", "data_staleness", "data_integrity"]}},
]
_BY_KEY = {c["key"]: c for c in CATEGORIES}

# v2/legacy path → v3 hub, so a report's action button always lands on a real page.
_V3 = {"risk": "/v3/risk", "approvals": "/v3/trading", "recovery": "/v3/retirement", "actions": "/v3/trading",
       "trading": "/v3/trading", "journal": "/v3/journal", "system": "/v3/system", "portfolio": "/v3/portfolio"}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _sev_from_nl(ntype: str) -> str:
    if ntype in ("urgent_alert", "recovery_escalation"):
        return "urgent"
    if ntype in ("aegis_morning_brief", "daily_digest", "info", "dividend_alert"):
        return "info"
    if ntype in ("stale_data_alert", "rebalance_stale", "draft_alert", "alert_fatigue_meta"):
        return "warning"
    return "info"


def _action_links(text: str) -> list[dict]:
    """Extract dashboard links from a report body, mapped to v3 routes → actionable buttons."""
    import re
    out, seen = [], set()
    for m in re.finditer(r"/v[23]/([a-z-]+)", text or ""):
        page = m.group(1)
        v3 = _V3.get(page, f"/v3/{page}")
        if v3 not in seen:
            seen.add(v3)
            out.append({"label": "Open " + page.replace("-", " ").title(), "url": "https://ms01-openclaw.tail163d14.ts.net" + v3})
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
                body = r[5] or ""
                rows.append({"source": "nl", "id": r[0], "created_at": r[1], "category": category,
                             "type": r[2], "channel": r[3], "title": r[4] or r[2], "summary": body,
                             "severity": _sev_from_nl(r[2]), "symbol": None, "status": r[6],
                             "actions": _action_links(str(r[7]) + " " + body), "acknowledged": (r[6] == "read")})
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
            return {"source": "nl", "id": r[0], "created_at": str(r[1]), "type": r[2], "channel": r[3],
                    "title": r[4], "summary": r[5], "status": r[6], "payload": r[7], "sent_at": str(r[8]),
                    "actions": _action_links(str(r[7]) + " " + (r[5] or ""))}
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
    deleted = {"notification_log": 0, "alert_events": 0}
    try:
        # notification_log
        nlw, nlp = _nl_where(cat) if cat else ("TRUE", [])
        if nlw != "FALSE":
            if apply:
                cur.execute(f"DELETE FROM notification_log WHERE {nlw} AND {cut}", nlp)
                deleted["notification_log"] = cur.rowcount
            else:
                cur.execute(f"SELECT count(*) FROM notification_log WHERE {nlw} AND {cut}", nlp)
                deleted["notification_log"] = cur.fetchone()[0]
        # alert_events
        aw = _ae_where(cat) if cat else ("TRUE", [])
        if aw:
            if apply:
                cur.execute(f"DELETE FROM alert_events WHERE {aw[0]} AND {cut}", aw[1])
                deleted["alert_events"] = cur.rowcount
            else:
                cur.execute(f"SELECT count(*) FROM alert_events WHERE {aw[0]} AND {cut}", aw[1])
                deleted["alert_events"] = cur.fetchone()[0]
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
