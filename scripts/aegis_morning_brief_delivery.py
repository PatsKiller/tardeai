"""
aegis_morning_brief_delivery.py — Aegis morning brief delivery layer.

Delivers the overnight intelligence brief via:
1. Telegram compact summary
2. Formal export (markdown)

Uses dedupe to prevent duplicate sends for the same run_id.
Entry point: deliver()
"""
from __future__ import annotations
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

DEDUPE_FILE = PROJECT_ROOT / "logs" / ".aegis_morning_brief_sent"


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


def _already_sent(run_id: str) -> bool:
    """Check if brief was already sent for this run_id."""
    try:
        if DEDUPE_FILE.exists():
            last = DEDUPE_FILE.read_text().strip()
            return last == run_id
    except Exception:
        pass
    return False


def _mark_sent(run_id: str):
    DEDUPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEDUPE_FILE.write_text(run_id)


def _get_morning_brief():
    """Fetch the latest morning brief from the API context builder."""
    import requests
    try:
        resp = requests.get("http://127.0.0.1:7777/api/v2/aegis/chat-context", timeout=10)
        data = resp.json().get("data", {})
        return data.get("morning_brief", {}), data.get("portfolio_summary", "")
    except Exception:
        return {}, ""


def _get_event_digest():
    """Get Level 3 event summary from the last 24h."""
    rows = _db_query(
        """SELECT event_type, status, array_agg(DISTINCT symbol) as symbols, count(*) as cnt
           FROM agent_event_queue
           WHERE created_at > NOW() - INTERVAL '24 hours'
           GROUP BY event_type, status
           ORDER BY cnt DESC"""
    ) or []
    digest = {}
    total = 0
    for r in rows:
        et = r["event_type"]
        if et not in digest:
            digest[et] = {"symbols": [], "count": 0, "done": 0, "pending": 0}
        syms = r.get("symbols") or []
        digest[et]["symbols"] = list(set(digest[et]["symbols"] + [s for s in syms if s]))
        digest[et]["count"] += r["cnt"]
        total += r["cnt"]
        if r["status"] == "done":
            digest[et]["done"] += r["cnt"]
        else:
            digest[et]["pending"] += r["cnt"]
    return digest, total


def _get_steph_queue():
    """Fetch Steph review queue summary."""
    rows = _db_query(
        "SELECT review_status, count(*) as cnt FROM aegis_steph_escalations GROUP BY review_status"
    ) or []
    return {r["review_status"]: r["cnt"] for r in rows}


def _get_pipeline_health_for_brief() -> str:
    """One-line pipeline status for the morning brief."""
    try:
        rows = _db_query("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status='success' THEN 1 END) as ok,
                COUNT(CASE WHEN status='failed' THEN 1 END) as failed,
                COUNT(CASE WHEN run_type='retry' THEN 1 END) as retries
            FROM pipeline_runs
            WHERE started_at > NOW() - INTERVAL '12 hours'
        """, fetch="one")
        if not rows or not rows.get("total"):
            return ''

        total = rows["total"]
        ok = rows["ok"]
        failed = rows["failed"]
        retries = rows["retries"]

        if failed == 0 and retries == 0:
            return f"\u2705 *Pipeline:* {ok}/{total} steps OK overnight"
        elif failed > 0:
            failed_rows = _db_query("""
                SELECT DISTINCT script_name FROM pipeline_runs
                WHERE status='failed'
                AND started_at > NOW() - INTERVAL '12 hours'
            """) or []
            failed_names = [r["script_name"] for r in failed_rows[:2]]
            extra = f", {retries} retries" if retries else ""
            return (f"\u26a0\ufe0f *Pipeline:* {ok}/{total} OK, {failed} FAILED "
                    f"({', '.join(failed_names)}){extra}")
        elif retries > 0:
            return f"\u21ba *Pipeline:* {ok}/{total} OK ({retries} needed retry)"
        return ''
    except Exception:
        return ''


# ── D1: Telegram delivery ────────────────────────────────────────────────

def _get_watch_directives_brief() -> list:
    """Watch Directives lines for the morning brief: active/paused counts, new hits (24h) with
    tier+divergence, staged-awaiting-tap, and any auto-paused-cold mandates. Advisory."""
    out = []
    try:
        counts = _db_query("SELECT status, count(*) n FROM watch_directives GROUP BY status") or []
        by = {r["status"]: r["n"] for r in counts}
        active, paused = by.get("active", 0), by.get("paused", 0)
        if active == 0 and paused == 0:
            return []
        out.append(f"*Watch Directives:* {active} active" + (f", {paused} paused" if paused else ""))
        hits = _db_query("""SELECT symbol, surfaced_by, source_tier, divergence, promotion_status
                            FROM watch_directive_hits WHERE surfaced_at > NOW() - INTERVAL '24 hours'
                            ORDER BY surfaced_at DESC LIMIT 6""") or []
        for h in hits[:5]:
            tag = [t for t in (h.get("source_tier"),
                               (h.get("divergence") if h.get("divergence") not in (None, "unavailable") else None)) if t]
            out.append(f"  • {h['symbol']} ({h.get('surfaced_by')}) "
                       f"{(h.get('promotion_status') or '').replace('_', ' ').lower()}"
                       + (f" [{', '.join(tag)}]" if tag else ""))
        staged = _db_query("""SELECT count(*) n FROM watch_directive_hits
                              WHERE promotion_status='STAGED_FOR_REVIEW' AND promoted=false""", fetch="one") or {}
        if staged.get("n", 0) > 0:
            out.append(f"  ⏳ {staged['n']} staged hits awaiting one-tap promote")
        cold = _db_query("""SELECT label FROM watch_directives WHERE status='paused' AND cold_since IS NOT NULL
                            ORDER BY updated_at DESC LIMIT 3""") or []
        for c in cold:
            out.append(f"  ⏸ auto-paused (cold): {c['label']}")
    except Exception:
        pass
    return out


def _get_gain_guardian_brief() -> list:
    """GAIN GUARDIAN section — active CLIMAX_RISK / GIVEBACK states from the
    latest holding_exit_metrics run only. Advisory; empty list when quiet or
    when the table doesn't exist yet (fail-open)."""
    try:
        rows = _db_query(
            """SELECT symbol, extension_state, giveback_state, advisory, severity,
                      parabolic_score, open_gain_pct, giveback_frac
               FROM holding_exit_metrics
               WHERE run_at = (SELECT max(run_at) FROM holding_exit_metrics)
                 AND (extension_state = 'CLIMAX_RISK' OR giveback_state IS NOT NULL)
               ORDER BY (severity = 'urgent') DESC, parabolic_score DESC
               LIMIT 6""",
        ) or []
    except Exception:
        return []
    if not rows:
        return []
    lines = ["*GAIN GUARDIAN* (advisory)"]
    for r in rows:
        state = r.get("extension_state") or ""
        if r.get("giveback_state"):
            state = f"{state}/{r['giveback_state']}" if state != "NORMAL" else r["giveback_state"]
        lines.append(
            f"  • {r['symbol']}: {state} score={r.get('parabolic_score')} "
            f"gain={r.get('open_gain_pct')}% → {r.get('advisory') or 'review'}"
            + (" !!!" if r.get("severity") == "urgent" else "")
        )
    lines.append("")
    return lines


def send_telegram_brief(brief: dict, summary: str) -> bool:
    """Send compact morning brief to Telegram."""
    sections = brief.get("sections", [])
    next_actions = brief.get("next_actions", [])

    lines = ["*\U0001f6e1 Aegis Morning Brief*", ""]

    # Summary line
    if summary:
        lines.append(f"_{summary[:120]}_")
        lines.append("")

    # Top sections (keep compact)
    for s in sections[:3]:
        title = s.get("title", "")
        items = s.get("items", [])
        if items:
            lines.append(f"*{title}*")
            for item in items[:2]:
                lines.append(f"  \u2022 {item[:80]}")
            lines.append("")

    # Steph queue
    steph = _get_steph_queue()
    pending = steph.get("pending_review", 0)
    needs_john = steph.get("needs_john", 0)
    if pending > 0 or needs_john > 0:
        lines.append(f"*Steph Queue:* {pending} pending" + (f", {needs_john} need John" if needs_john else ""))
        lines.append("")

    # Overnight risk synthesis (from deep LLM window)
    try:
        _risk = _db_query(
            """SELECT LEFT(narrative, 200) as preview,
                      top_risks->0->>'action' as priority_action
               FROM risk_synthesis_results
               WHERE generated_at > NOW() - INTERVAL '18 hours'
                 AND morning_brief_ready = TRUE
               ORDER BY generated_at DESC LIMIT 1""",
            fetch="one"
        )
        if _risk and _risk.get("priority_action"):
            lines.append(f"*Overnight Risk Analysis:*")
            lines.append(f"  {_risk['priority_action']}")
            lines.append("")
    except Exception:
        pass

    # Event intelligence digest (Level 3)
    event_digest, event_total = _get_event_digest()
    if event_total > 0:
        lines.append(f"*Event Intelligence (24h): {event_total} events*")
        for et, d in sorted(event_digest.items()):
            syms = ", ".join(d["symbols"][:6])
            status = "done" if d["pending"] == 0 else f'{d["done"]} done, {d["pending"]} pending'
            priority = "urgent" if et in ("STOP_TRIGGERED", "SEC_INSIDER_BUY", "FRED_RATE_CHANGE", "IRMAA_THRESHOLD") else ""
            lines.append(f"  {et}: {syms} ({status}){' !!!' if priority else ''}")
        lines.append("")

    # Watch Directives section (advisory) — counts, new hits, staged-awaiting-tap, paused-cold
    wd_lines = _get_watch_directives_brief()
    if wd_lines:
        lines.extend(wd_lines)
        lines.append("")

    # Gain Guardian exit-intelligence states (latest run only, advisory)
    gg_lines = _get_gain_guardian_brief()
    if gg_lines:
        lines.extend(gg_lines)

    # Iris taxonomy section — only if pending proposals or low coverage
    try:
        from iris_taxonomy_agent import iris_status_summary
        iris_conn = None
        try:
            from db_adapter import _execute
            pending_rows = _execute("SELECT count(*) as n FROM iris_taxonomy_proposals WHERE status='pending'", fetch="one")
            iris_pending = pending_rows["n"] if pending_rows else 0
        except Exception:
            iris_pending = 0

        if iris_pending > 0:
            lines.append(f"*Iris (Taxonomy):* {iris_status_summary()}")
            lines.append("")
    except Exception:
        pass  # Iris is optional — never break the brief

    # Pipeline health (overnight status)
    try:
        pipeline_line = _get_pipeline_health_for_brief()
        if pipeline_line:
            lines.append(pipeline_line)
            lines.append("")
    except Exception:
        pass

    # ── Dividends due this month ──
    try:
        div_cal = json.loads((STATE_DIR / "dividend_calendar.json").read_text()) if (STATE_DIR / "dividend_calendar.json").exists() else {}
        monthly = div_cal.get("monthly_summary", [])
        cur_month = datetime.now().month
        this_month = next((m for m in monthly if m.get("month") == cur_month), None)
        if this_month and this_month.get("symbols"):
            syms = ", ".join(this_month["symbols"][:8])
            lines.append(f"*\U0001f4b0 Dividends ({this_month['month_name']}):* ${this_month['total']:,.0f} from {syms}")
            lines.append("")
    except Exception:
        pass

    # ── Proposals needing action ──
    try:
        pending_proposals = _db_query(
            "SELECT symbol, strategy_id FROM paper_trade_proposals WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 5"
        ) or []
        if pending_proposals:
            syms = ", ".join(p["symbol"] for p in pending_proposals)
            lines.append(f"*\U0001f4cb Proposals Pending:* {len(pending_proposals)} — {syms}")
            lines.append("")
    except Exception:
        pass

    # ── Recovery watch summary ──
    try:
        recovery = _db_query(
            """SELECT analyst_verdict, COUNT(*) as cnt
               FROM stopped_out_watch WHERE is_active = true
               GROUP BY analyst_verdict"""
        ) or []
        if recovery:
            parts = [f"{r['analyst_verdict'].replace('_',' ')}: {r['cnt']}" for r in recovery]
            lines.append(f"*Recovery Watch:* {', '.join(parts)}")
            lines.append("")
    except Exception:
        pass

    # ── Portfolio risk snapshot ──
    try:
        rm = json.loads((STATE_DIR / "risk_management.json").read_text()) if (STATE_DIR / "risk_management.json").exists() else {}
        heat = rm.get("portfolio_heat_pct", 0)
        no_stop = sum(1 for p in rm.get("positions", []) if p.get("status") == "NO STOP")
        if heat > 5 or no_stop > 5:
            parts = []
            if heat > 5:
                parts.append(f"Heat {heat:.1f}% (>5% threshold)")
            if no_stop > 5:
                parts.append(f"{no_stop} positions without stops")
            lines.append(f"*\u26a0\ufe0f Risk:* {' | '.join(parts)}")
            lines.append("")
    except Exception:
        pass

    # Next actions
    if next_actions:
        lines.append("*Next Actions:*")
        for na in next_actions[:3]:
            lines.append(f"  {na[:80]}")
        lines.append("")

    lines.append(f"_Run: {brief.get('run_id', 'latest')} | {datetime.now().strftime('%H:%M ET')}_")
    lines.append("Reply: ask Aegis for detail")

    msg = "\n".join(lines)

    try:
        from telegram_alert import send_telegram
        return send_telegram(msg)
    except Exception as e:
        print(f"  [brief] Telegram send failed: {e}")
        return False


# ── D3: Formal export ─────────────────────────────────────────────────────

def write_formal_export(brief: dict, summary: str) -> str:
    """Write a formal markdown morning brief for archive/export."""
    sections = brief.get("sections", [])
    next_actions = brief.get("next_actions", [])
    steph = _get_steph_queue()
    today = date.today().isoformat()

    lines = [
        f"# Aegis Morning Brief — {today}",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M ET')}*",
        "",
        "---",
        "",
        "## Executive Summary",
        summary or "No portfolio summary available.",
        "",
    ]

    # Ranked sections
    for s in sections:
        title = s.get("title", "")
        items = s.get("items", [])
        lines.append(f"## {s.get('priority', '?')}. {title}")
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("- No items in this category.")
        lines.append("")

    # Steph review status
    lines.append("## Steph Review Queue")
    for status, count in sorted(steph.items()):
        lines.append(f"- {status.replace('_', ' ')}: **{count}**")
    if not steph:
        lines.append("- No Steph review items.")
    lines.append("")

    # Event intelligence digest
    event_digest, event_total = _get_event_digest()
    lines.append("## Event Intelligence (Last 24h)")
    if event_total > 0:
        lines.append(f"**{event_total} events fired**")
        lines.append("")
        for et, d in sorted(event_digest.items()):
            syms = ", ".join(d["symbols"][:8])
            status = "all done" if d["pending"] == 0 else f'{d["done"]} done, {d["pending"]} pending'
            lines.append(f"- **{et}**: {syms} ({d['count']} events, {status})")
    else:
        lines.append("- No events in the last 24 hours.")
    lines.append("")

    # Iris taxonomy section (formal export)
    try:
        from iris_taxonomy_agent import iris_status_summary
        lines.append("## Iris — Taxonomy Intelligence")
        lines.append(iris_status_summary())
        lines.append("")
    except Exception:
        pass

    # Next actions
    lines.append("## Ranked Next Actions")
    if next_actions:
        for i, na in enumerate(next_actions, 1):
            lines.append(f"{i}. {na}")
    else:
        lines.append("- No specific actions identified.")
    lines.append("")

    # Evidence quality
    ev_rows = _db_query(
        "SELECT evidence_sufficiency, count(*) as cnt FROM aegis_evidence_ledger WHERE run_id=(SELECT run_id FROM aegis_evidence_ledger ORDER BY observed_at DESC LIMIT 1) GROUP BY evidence_sufficiency"
    ) or []
    if ev_rows:
        lines.append("## Evidence Quality")
        for r in ev_rows:
            lines.append(f"- {r['evidence_sufficiency']}: {r['cnt']} symbols")
        lines.append("")

    # Footer
    lines.extend([
        "---",
        f"*Aegis Portfolio Intelligence | {today} | Provenance: model=aegis*",
        "*Advisory only — no auto-trading — review chain: Aegis → Steph → John*",
    ])

    # Write to reports directory
    export_dir = PROJECT_ROOT / "data" / "portfolios" / "reports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"aegis_morning_brief_{today}.md"
    export_path.write_text("\n".join(lines))

    # Also write to docs for archival
    docs_path = PROJECT_ROOT / "docs" / f"openclaw_aegis_morning_brief_{today}.md"
    docs_path.write_text("\n".join(lines))

    # Reports Desk v1 (WS-B, additive): persist the STRUCTURED brief beside the .md so
    # the Reports page renders sections as data instead of re-parsing flattened text.
    # Telegram send path and the .md export above are untouched (sacred contract).
    try:
        json_path = export_dir / f"aegis_morning_brief_{today}.json"
        json_path.write_text(json.dumps({
            "run_id": brief.get("run_id"),
            "generated_at": datetime.now().isoformat(),
            "summary": summary,
            "has_findings": brief.get("has_findings"),
            "sections": brief.get("sections", []),
        }, default=str, indent=1))
    except Exception as _je:
        print(f"  [aegis-brief] json sidecar failed (non-fatal): {_je}")

    return str(export_path)


# ── Main delivery ─────────────────────────────────────────────────────────

def deliver(force: bool = False) -> dict:
    """Deliver the morning brief via all channels."""
    print(f"[aegis-brief] Morning brief delivery starting — {datetime.now().isoformat()}")

    brief, summary = _get_morning_brief()
    if not brief.get("has_findings") and not force:
        print("  [aegis-brief] No findings in brief — skipping delivery")
        return {"delivered": False, "reason": "no_findings"}

    # Check dedupe
    run_id = brief.get("run_id", f"manual-{date.today()}")
    if _already_sent(run_id) and not force:
        print(f"  [aegis-brief] Already sent for {run_id} — skipping")
        return {"delivered": False, "reason": "already_sent", "run_id": run_id}

    results = {}

    # Telegram
    tg_ok = send_telegram_brief(brief, summary)
    results["telegram"] = "sent" if tg_ok else "failed"
    print(f"  Telegram: {'sent' if tg_ok else 'failed'}")

    # Formal export
    export_path = write_formal_export(brief, summary)
    results["export"] = export_path
    print(f"  Export: {export_path}")

    # Log intelligence event
    try:
        import psycopg2 as _pg
        _pw = ""
        for _line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if _line.startswith("DB_PASSWORD="): _pw = _line.split("=", 1)[1].strip()
        _conn = _pg.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=_pw)
        _cur = _conn.cursor()
        _cur.execute("""INSERT INTO portfolio_intelligence_events
            (event_type, severity, source, payload)
            VALUES ('aegis_morning_brief', 'info', 'aegis_morning_brief_delivery.py', %s)""",
            (json.dumps({"run_id": run_id, "sections": len(brief.get("sections", [])),
                         "telegram": results.get("telegram")}, default=str),))
        _conn.commit()
        _conn.close()
        print(f"  Intel event: logged")
    except Exception as _e:
        print(f"  Intel event: failed ({_e})")

    # Audit trail
    try:
        from db_adapter import save_notification_log_entry
        save_notification_log_entry({
            "notification_date": date.today(),
            "notification_type": "aegis_morning_brief",
            "channel": "telegram+export",
            "subject": f"[Morning Brief] {date.today()} — {run_id}",
            "body_summary": (summary or "No summary")[:300],
            "recommendation_ids": None, "escalation_ids": None, "observation_ids": None,
            "payload": json.dumps({"run_id": run_id, "telegram": results.get("telegram"), "export": export_path}),
            "status": "sent", "dedupe_key": f"morning_brief_{date.today()}",
            "sent_at": datetime.now(), "error": None,
        })
    except Exception:
        pass

    # Mark sent
    _mark_sent(run_id)
    results["delivered"] = True
    results["run_id"] = run_id

    print(f"[aegis-brief] Delivery complete")
    return results


if __name__ == "__main__":
    deliver(force="--force" in sys.argv)
