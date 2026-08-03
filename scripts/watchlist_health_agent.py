#!/usr/bin/env python3
"""watchlist_health_agent.py — Autonomous Watchlist Remediation Agent.

Continuously scans every active watchlist item for degradation (stale CIO synthesis,
missing critic reviews, quality not assessed, stale street data, missing plans).
Uses DeepSeek Flash to diagnose each stuck item and recommend the right fix.

Auto-queues LOW/MEDIUM severity fixes. Requests Telegram approval for HIGH.
Integrates with system_health_agent DB tables for dashboard display.

=== HARD BOUNDARIES (design contract — enforced in code) ===
1. NO 2FA — never calls broker approval service, never triggers bkap/bkrej
2. NO TRADING — never places, modifies, or cancels trades
3. NO BROKER ACCOUNT MANAGEMENT — never reads/writes holdings.json,
   never syncs broker positions, never calls broker balance endpoints
4. ALL broker/trading/account issues ESCALATE TO OPERATOR via Telegram
5. Only SAFE_ACTIONS are callable by this agent (see _execute_action guard)
6. All AGENTS.md rules validated — see docs/WATCHLIST_HEALTH_AGENT.md

Schedule: */30 9-16 * * 1-5 (weekdays), 0 */1 * * 0,6 (weekends)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [wl-health] %(message)s")
log = logging.getLogger("watchlist_health_agent")

# ═══════════════════════════════════════════════════════════════════════════
# HARD BOUNDARIES — Do NOT add to these lists without updating the docs.
# ═══════════════════════════════════════════════════════════════════════════

# These 6 actions are the ONLY ones this agent is permitted to execute.
# Adding any broker/trade/2FA action here violates the design contract.
SAFE_ACTIONS = frozenset({
    "refresh_data",         # POST /api/v2/watch/decision/refresh (packet rebuild)
    "cio_synthesis",        # POST /api/v2/watchlist/<SYM>/cio-synthesis (LLM synthesis)
    "build_plan",           # POST /api/v2/watchlist/<SYM>/plan (entry planner)
    "run_critics",          # POST /api/v2/watch/ticket-review/run (critic reviews)
    "run_critics_stale",    # alias for run_critics (deterministic diagnosis output)
    "run_critics_active",   # alias for run_critics (deterministic diagnosis output)
    "queue_agent_reviews",  # DB INSERT watchlist_agent_jobs (agent review queue)
    "refresh_street",       # POST /api/v2/watchlist/refresh-batch (street data)
})

# These prefixes are NEVER allowed in action IDs. Blocked at guard.
BANNED_PREFIXES = ("bk", "bkr", "broker", "trade", "order", "exec", "alpaca",
                    "schwab", "snap", "fidelity", "moomoo", "2fa", "approve_order",
                    "cancel", "modify", "atm", "position_close", "sell", "buy")

# ═══════════════════════════════════════════════════════════════════════════


# ── Degradation thresholds ─────────────────────────────────────────────────
CIO_SYNTHESIS_STALE_HOURS = 24       # CIO synthesis older than this = DEGRADED
STREET_DATA_STALE_DAYS = 7           # Analyst consensus older than this = warning
CRITICS_STALE_HOURS = 6              # No critic reviews in this window = missing
QUALITY_UNASSESSED_MINUTES = 120     # Quality not assessed after packet built = issue
PLAN_MISSING_HOURS = 12              # No entry plan built = issue
AGENT_REVIEW_STALE_HOURS = 48        # Agent reviews older than this = stale

# ── Remediation tiers ──────────────────────────────────────────────────────
# LOW: auto-fix, no notification needed (data refresh, plan build)
# MEDIUM: auto-fix with informative notification (CIO synthesis, agent reviews)
# HIGH: requires Telegram approval (critics on proposed trades, broker actions)
AUTO_APPROVE_LOW = {"refresh_data", "build_plan", "refresh_street"}
AUTO_APPROVE_MEDIUM = {"cio_synthesis", "queue_agent_reviews", "run_critics_stale"}
REQUIRES_APPROVAL = {"run_critics_active", "revalidate_proposal"}

# ── DB helpers ─────────────────────────────────────────────────────────────
def _get_conn():
    try:
        from db_adapter import _get_conn as _gc
        return _gc()
    except Exception:
        return None


def _db_query(sql, params=None, fetch="all"):
    conn = _get_conn()
    if not conn:
        return [] if fetch == "all" else {}
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if fetch == "one":
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else {}
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return rows
    except Exception as e:
        log.warning(f"DB query failed: {e}")
        return [] if fetch == "all" else {}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _log_health_event(component: str, event_type: str, severity: str,
                       message: str, action: str = None, success: bool = None,
                       symbol: str = None):
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        # Prefix symbol into message for event tracking
        full_message = (f"[{symbol}] {message}" if symbol else message)[:500]
        # Dedup: same (component, event_type, severity, message prefix) in 30 min → skip
        cur.execute("""SELECT event_type, severity FROM system_health_events
                       WHERE component = %s AND created_at > NOW() - INTERVAL '30 minutes'
                       AND message LIKE %s
                       ORDER BY created_at DESC LIMIT 1""",
                    [component, f"[{symbol}]%" if symbol else "%"])
        last = cur.fetchone()
        if last and last[0] == event_type and last[1] == severity:
            conn.commit()
            return
        cur.execute("""INSERT INTO system_health_events
            (component, event_type, severity, message, action_taken, success)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            [component, event_type, severity, full_message,
             action[:200] if action else None, success])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to log health event: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Telegram approval ──────────────────────────────────────────────────────
def _send_telegram_approval(symbol: str, diagnosis: dict, actions: list[dict]) -> dict:
    """Send Telegram msg with approval buttons for HIGH-severity actions.
    Only actions passing _guard_action() are included in the buttons.
    Escalated actions (outside SAFE_ACTIONS) get a manual-instruction note instead."""
    try:
        from telegram_alert import chokepoint_send

        # Split into automatable vs escalated
        automatable = [a for a in actions if _guard_action(a.get("id", ""))]
        escalated = [a for a in actions if not _guard_action(a.get("id", ""))]

        severity_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
        sev = severity_emoji.get(diagnosis.get("severity", "MEDIUM"), "⚪")

        lines = [
            f"{sev} **Watchlist Health: {symbol}**",
            f"*Diagnosis:* {diagnosis.get('summary', 'Unknown')}",
            f"*Root cause:* {diagnosis.get('root_cause', 'unknown')}",
            f"*Cost:* {diagnosis.get('estimated_cost', 'free')}",
        ]

        if automatable:
            lines.append("\n*Auto-fixable (approve to run):*")
            for a in automatable:
                lines.append(f"  • {a['label']}")

        if escalated:
            lines.append("\n*Requires operator action (outside agent authority):*")
            for a in escalated:
                lines.append(f"  ❗ {a['label']} — manual intervention needed")
            lines.append("\n⚠ Broker/trading/2FA actions are permanently outside agent scope.")

        msg = "\n".join(lines)

        # Build keyboard only for automatable actions
        keyboard = None
        if automatable:
            action_ids = "+".join(a["id"] for a in automatable)
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ Approve All", "callback_data": f"wl_health_approve:{symbol}:{action_ids}"}],
                    [{"text": "❌ Deny", "callback_data": f"wl_health_deny:{symbol}"}],
                    [{"text": "🔍 Open Card", "callback_data": f"wl_health_view:{symbol}"}],
                ]
            }

        result = chokepoint_send(msg, reply_markup=keyboard, parse_mode="Markdown")
        message_id = result.get("message_id") if isinstance(result, dict) else None

        # Store pending approval record
        conn = _get_conn()
        if conn:
            try:
                cur = conn.cursor()
                now = datetime.now(timezone.utc)
                cur.execute("""INSERT INTO watchlist_health_approvals
                    (symbol, diagnosis, actions, status, message_id, created_at)
                    VALUES (%s, %s, %s, 'pending', %s, %s)
                    ON CONFLICT ON CONSTRAINT watchlist_health_approvals_pkey DO NOTHING""",
                    [symbol, json.dumps(diagnosis, default=str),
                     json.dumps(actions, default=str),
                     str(message_id) if message_id else None, now])
                conn.commit()
            except Exception as e:
                log.warning(f"Failed to store approval: {e}")
            finally:
                try: conn.close()
                except Exception: pass

        return {"ok": True, "message_id": message_id, "state": "pending_approval",
                "automatable": len(automatable), "escalated": len(escalated)}

    except Exception as e:
        log.error(f"Telegram approval send failed: {e}")
        return {"ok": False, "error": str(e)[:200]}


# ── DeepSeek diagnosis ─────────────────────────────────────────────────────
def _diagnose_with_deepseek(symbol: str, issues: list[str],
                             packet_info: dict) -> dict:
    """Use DeepSeek Flash to diagnose what's wrong and recommend fixes.

    Calls the DeepSeek API directly with a short 8s timeout — no fallback chain.
    On any failure (unreachable, timeout, parse error), returns deterministic
    diagnosis immediately so the cron job never hangs.
    """
    import os
    api_key = os.environ.get("deepseek_tradeai", "").strip()
    if not api_key:
        return _deterministic_diagnosis(symbol, issues, packet_info)

    prompt = f"""You are a systematic trading desk health monitor. A watchlist item is DEGRADED.

Symbol: {symbol}
Issues detected:
{chr(10).join(f"- {i}" for i in issues)}

Packet context:
{json.dumps(packet_info, default=str, indent=2)}

Diagnose what the root cause is and recommend the MINIMAL set of corrective actions.
Prioritize: refresh data first, then CIO synthesis, then agent reviews, then critics last.
Estimate if any action costs money (paid API calls vs free lanes).

Reply ONLY valid JSON:
{{"severity": "LOW|MEDIUM|HIGH",
 "summary": "one-line diagnosis",
 "recommended_actions": [{{"id": "action_key", "label": "human-readable", "risk": "LOW|MEDIUM|HIGH", "auto_approve": true|false}}],
 "root_cause": "why this degraded",
 "estimated_cost": "free|paid:<$0.01|paid:<$0.05",
 "needs_approval_reason": "why it needs human approval, or null if auto-approve ok"}}"""

    try:
        import requests
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={"model": "deepseek-v4-flash",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": 512},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8  # short: diagnose must be fast or not at all
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        log.warning(f"DeepSeek diagnosis skipped for {symbol}: {e}")

    return _deterministic_diagnosis(symbol, issues, packet_info)


def _deterministic_diagnosis(symbol: str, issues: list[str],
                              packet_info: dict) -> dict:
    """Rule-based fallback when DeepSeek is unavailable."""
    severity = "MEDIUM"
    actions = []
    cost = "free"

    has_stale_synthesis = any("synthesis stale" in i.lower() for i in issues)
    has_no_critics = any("no critic" in i.lower() for i in issues)
    has_no_quality = any("quality not assessed" in i.lower() for i in issues)
    has_stale_street = any("street data stale" in i.lower() for i in issues)
    has_no_plan = any("no plan" in i.lower() for i in issues)

    if has_no_quality or has_stale_synthesis:
        severity = "HIGH" if has_stale_synthesis else "MEDIUM"

    if has_stale_synthesis:
        actions.append({"id": "cio_synthesis", "label": f"Run CIO synthesis for {symbol}",
                        "risk": "MEDIUM", "auto_approve": True})
        cost = "paid:<$0.01"

    if has_no_quality or has_stale_street:
        actions.append({"id": "refresh_data", "label": f"Refresh data + build packet for {symbol}",
                        "risk": "LOW", "auto_approve": True})

    if has_no_critics:
        actions.append({"id": "run_critics_stale", "label": f"Run critic reviews for {symbol}",
                        "risk": "MEDIUM", "auto_approve": True})

    if has_no_plan:
        actions.append({"id": "build_plan", "label": f"Build entry plan for {symbol}",
                        "risk": "LOW", "auto_approve": True})

    return {
        "severity": severity,
        "summary": f"{symbol} has {len(issues)} degradation issues",
        "recommended_actions": actions,
        "root_cause": "deterministic diagnosis",
        "estimated_cost": cost,
        "needs_approval_reason": None,
    }


# ── Remediation executors ──────────────────────────────────────────────────
def _guard_action(action_id: str) -> bool:
    """Return True only if the action is in the SAFE_ACTIONS allowlist and does
    not match any BANNED_PREFIX. This is the single chokepoint that enforces all
    hard boundaries (no 2FA, no trading, no broker account management)."""
    if not isinstance(action_id, str):
        return False
    aid = action_id.lower().strip()
    if aid not in SAFE_ACTIONS:
        log.error(f"BLOCKED action '{action_id}' — not in SAFE_ACTIONS allowlist")
        return False
    for prefix in BANNED_PREFIXES:
        if aid.startswith(prefix):
            log.critical(f"BLOCKED banned action '{action_id}' — matched prefix '{prefix}'")
            return False
    return True


def _execute_action(symbol: str, action_id: str) -> dict:
    """Execute a single safe remediation action. Hard-blocked for anything outside
    SAFE_ACTIONS. Returns {action, symbol, ok, detail}."""
    if not _guard_action(action_id):
        return {
            "action": action_id, "symbol": symbol, "ok": False,
            "detail": "BLOCKED: action not in SAFE_ACTIONS allowlist — escalate to operator"
        }

    # Normalize aliases to canonical action_id
    if action_id in ("run_critics_stale", "run_critics_active"):
        action_id = "run_critics"

    result = {"action": action_id, "symbol": symbol, "ok": False, "detail": ""}

    try:
        # ── packet data refresh ──
        if action_id == "refresh_data":
            import subprocess
            proc = subprocess.run(
                ["curl", "-sS", "-X", "POST",
                 "http://localhost:7777/api/v2/watch/decision/refresh",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"symbols": [symbol]})],
                capture_output=True, text=True, timeout=30)
            resp = json.loads(proc.stdout) if proc.stdout else {}
            result["ok"] = resp.get("ok", False)
            result["detail"] = json.dumps(resp)[:200]
            if result["ok"]:
                log.info(f"  ✅ refresh_data {symbol}: queued (run_id={resp.get('run_id')})")
            else:
                log.warning(f"  ⚠ refresh_data {symbol}: {resp.get('error', 'unknown')}")

        # ── CIO synthesis ──
        elif action_id == "cio_synthesis":
            import subprocess
            proc = subprocess.run(
                ["curl", "-sS", "-X", "POST",
                 f"http://localhost:7777/api/v2/watchlist/{symbol}/cio-synthesis",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"lanes": ["deepseek-v4"]})],
                capture_output=True, text=True, timeout=15)
            resp = json.loads(proc.stdout) if proc.stdout else {}
            result["ok"] = resp.get("ok", False)
            result["detail"] = json.dumps(resp)[:200]
            if result["ok"]:
                log.info(f"  ✅ cio_synthesis {symbol}: {resp.get('recommendation', '')}")
            else:
                log.warning(f"  ⚠ cio_synthesis {symbol}: {resp.get('error', 'unknown')[:120]}")

        # ── entry plan build ──
        elif action_id == "build_plan":
            import subprocess
            proc = subprocess.run(
                ["curl", "-sS", "-X", "POST",
                 f"http://localhost:7777/api/v2/watchlist/{symbol}/plan",
                 "-H", "Content-Type: application/json",
                 "-d", "{}"],
                capture_output=True, text=True, timeout=15)
            resp = json.loads(proc.stdout) if proc.stdout else {}
            result["ok"] = resp.get("ok", False)
            result["detail"] = json.dumps(resp)[:200]
            if result["ok"]:
                log.info(f"  ✅ build_plan {symbol}: queued")

        # ── critic reviews ──
        elif action_id == "run_critics":
            import subprocess
            proc = subprocess.run(
                ["curl", "-sS", "-X", "POST",
                 "http://localhost:7777/api/v2/watch/ticket-review/run",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"symbol": symbol,
                                  "lanes": "deepseek-flash,grok,chatgpt,local"})],
                capture_output=True, text=True, timeout=15)
            resp = json.loads(proc.stdout) if proc.stdout else {}
            result["ok"] = resp.get("ok", False)
            result["detail"] = json.dumps(resp)[:200]
            if result["ok"]:
                log.info(f"  ✅ run_critics {symbol}: queued")

        # ── queue agent reviews (direct DB insert — advisory only) ──
        elif action_id == "queue_agent_reviews":
            conn = _get_conn()
            if not conn:
                result["detail"] = "no DB connection"
            else:
                try:
                    cur = conn.cursor()
                    agents = ["maria", "steph", "risk_agent"]
                    for agent in agents:
                        cur.execute("""INSERT INTO watchlist_agent_jobs
                            (id, symbol, requested_agent, request_type, status, priority, submitted_from)
                            VALUES (%s, %s, %s, 'full_analysis', 'queued', 2, 'watchlist_health_agent')
                            ON CONFLICT (id) DO NOTHING""",
                            [str(uuid.uuid4()), symbol, agent])
                    conn.commit()
                    result["ok"] = True
                    result["detail"] = f"Queued {len(agents)} agent reviews"
                    log.info(f"  ✅ queue_agent_reviews {symbol}: {len(agents)} agents")
                except Exception as e:
                    result["detail"] = str(e)[:200]
                    log.warning(f"  ⚠ queue_agent_reviews {symbol}: {e}")
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

        # ── street data refresh ──
        elif action_id == "refresh_street":
            import subprocess
            proc = subprocess.run(
                ["curl", "-sS", "-X", "POST",
                 "http://localhost:7777/api/v2/watchlist/refresh-batch",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"symbols": [symbol], "tier": "MAIN"})],
                capture_output=True, text=True, timeout=15)
            resp = json.loads(proc.stdout) if proc.stdout else {}
            result["ok"] = resp.get("ok", False)
            result["detail"] = json.dumps(resp)[:200]
            if result["ok"]:
                log.info(f"  ✅ refresh_street {symbol}: queued")

    except Exception as e:
        result["detail"] = str(e)[:200]
        log.error(f"  ❌ {action_id} {symbol}: {e}")

    return result


# ── Main scan logic ────────────────────────────────────────────────────────
def _scan_single_symbol(symbol: str, packet_info: dict) -> dict:
    """Scan a single watchlist item for degradation and return findings."""
    issues = []
    now = datetime.now(timezone.utc)

    # Check CIO synthesis age
    synthesis = packet_info.get("cio_synthesis") or {}
    synthesis_at = synthesis.get("as_of")
    if synthesis_at:
        try:
            age_h = (now - datetime.fromisoformat(str(synthesis_at).replace("Z", "+00:00"))).total_seconds() / 3600
            if age_h > CIO_SYNTHESIS_STALE_HOURS:
                issues.append(f"CIO synthesis stale ({age_h:.1f}h)")
        except Exception:
            issues.append("CIO synthesis timestamp unparseable")
    else:
        issues.append("CIO synthesis never run")

    # Check deterministic validation
    ticket_review = packet_info.get("ticket_review") or {}
    deterministic = ticket_review.get("deterministic", "NOT_RUN")
    if deterministic == "NOT_RUN":
        issues.append("Deterministic validation not run")

    # Check quality admission
    quality = ticket_review.get("quality_admission") or {}
    quality_state = quality.get("state", "NOT_ASSESSED")
    if quality_state == "NOT_ASSESSED":
        issues.append("Quality not assessed")

    # Check critic reviews
    reviews = ticket_review.get("reviews") or {}
    has_reviews = any(
        r.get("verdict") for r in reviews.values()
        if isinstance(r, dict) and not str(r.get("verdict", "")).startswith("NOT")
    )
    if not has_reviews:
        issues.append("No critic reviews run")

    # Check street data
    street = packet_info.get("street_data") or packet_info.get("analyst_data") or {}
    street_age = street.get("age_days") or street.get("stale_days")
    if street_age and float(street_age) > STREET_DATA_STALE_DAYS:
        issues.append(f"Street data stale ({street_age}d)")

    # Check entry plan
    plan = packet_info.get("entry_plan") or packet_info.get("plan") or {}
    if not plan or not plan.get("created_at"):
        # Check if plan exists in DB
        plan_rows = _db_query(
            "SELECT created_at FROM watchlist_entry_plans WHERE symbol=%s ORDER BY created_at DESC LIMIT 1",
            (symbol,), fetch="one")
        if not plan_rows:
            plan_age = (now - plan_rows.get("created_at", now)).total_seconds() / 3600 if plan_rows else PLAN_MISSING_HOURS + 1
            if plan_age > PLAN_MISSING_HOURS:
                issues.append("No entry plan built")

    # Check agent review staleness
    agent_rows = _db_query(
        "SELECT agent, MAX(created_at) as latest FROM watchlist_agent_results WHERE symbol=%s GROUP BY agent",
        (symbol,))
    for ar in (agent_rows or []):
        try:
            age_h = (now - ar["latest"]).total_seconds() / 3600
            if age_h > AGENT_REVIEW_STALE_HOURS:
                issues.append(f"Agent {ar['agent']} review stale ({age_h:.1f}h)")
        except Exception:
            pass

    return {
        "symbol": symbol,
        "issues": issues,
        "degraded": len(issues) > 0,
        "severity": "HIGH" if len(issues) >= 3 else ("MEDIUM" if len(issues) >= 2 else "LOW"),
    }


def scan_watchlist(limit: int = 30, dry_run: bool = True) -> dict:
    """Scan all watchlist items for degradation. Auto-fix LOW/MEDIUM, request approval for HIGH."""
    now = datetime.now(timezone.utc)
    report = {
        "timestamp": now.isoformat(),
        "mode": "dry_run" if dry_run else "active",
        "scanned": 0,
        "degraded": 0,
        "auto_fixed": 0,
        "pending_approval": 0,
        "fixed_actions": [],
        "pending_items": [],
        "errors": [],
    }

    # Fetch all active watchlist items with their packet info
    items = _db_query("""
        SELECT symbol, status, last_enriched_at
        FROM watchlist_items
        WHERE status IN ('active', 'researched')
        ORDER BY last_enriched_at DESC NULLS LAST
        LIMIT %s
    """, (limit,))

    if not items:
        report["errors"].append("No watchlist items found")
        return report

    report["scanned"] = len(items)

    for item in items:
        sym = item["symbol"]
        try:
            # Fetch packet info
            packet = _db_query("""
                SELECT packet_id, packet FROM decision_packets
                WHERE upper(symbol)=%s AND superseded_by IS NULL
            """, (sym,), fetch="one")

            packet_info = packet.get("packet") or {} if packet else {}
            packet_info["packet_id"] = packet.get("packet_id")

            # Also fetch CIO synthesis
            synthesis = _db_query("""
                SELECT * FROM watchlist_final_synthesis
                WHERE upper(symbol)=%s
                ORDER BY created_at DESC LIMIT 1
            """, (sym,), fetch="one")
            if synthesis:
                packet_info["cio_synthesis"] = synthesis

            # Fetch ticket review from packet
            packet_info["ticket_review"] = (packet.get("packet") or {}).get("ticket_review") or {}

        except Exception as e:
            packet_info = {}
            log.warning(f"Failed to fetch packet for {sym}: {e}")

        # Scan
        finding = _scan_single_symbol(sym, packet_info)

        if not finding["degraded"]:
            continue

        report["degraded"] += 1

        # Use DeepSeek to diagnose
        diagnosis = _diagnose_with_deepseek(sym, finding["issues"], packet_info)
        actions = diagnosis.get("recommended_actions", [])

        if not actions:
            continue

        # Filter: only actions in SAFE_ACTIONS allowlist
        safe = [a for a in actions if _guard_action(a.get("id", ""))]
        blocked = [a for a in actions if not _guard_action(a.get("id", ""))]

        # Actions requiring approval: HIGH severity or touching active proposals
        is_high = diagnosis.get("severity") == "HIGH"
        need_approval = [a for a in safe if is_high or a.get("risk") in ("HIGH", "MEDIUM")]
        can_auto = [a for a in safe if a not in need_approval]

        # ── Auto-execute LOW-risk actions ──
        if can_auto and not dry_run:
            for action in can_auto:
                result = _execute_action(sym, action["id"])
                report["fixed_actions"].append({
                    "symbol": sym, "action": action["id"],
                    "label": action.get("label", ""),
                    "ok": result.get("ok"),
                    "detail": result.get("detail", "")[:200],
                })
                if result.get("ok"):
                    report["auto_fixed"] += 1
                    _log_health_event(
                        "watchlist_health", "AUTO_FIXED",
                        finding.get("severity", "LOW"),
                        f"Auto-fixed {action['label']} for {sym}",
                        action=action["id"], success=True, symbol=sym)
                else:
                    _log_health_event(
                        "watchlist_health", "AUTO_FIX_FAILED",
                        "WARN",
                        f"Auto-fix failed: {action['label']} for {sym}",
                        action=action["id"], success=False, symbol=sym)

        # ── Escalate blocked actions ──
        if blocked:
            report["pending_items"].append({
                "symbol": sym,
                "diagnosis": diagnosis.get("summary", ""),
                "severity": "ESCALATED",
                "actions": blocked,
                "approval_state": "escalated_to_operator",
                "note": "These actions are outside the agent's safe scope (broker/trade/2FA). Operator must handle manually.",
            })
            if not dry_run:
                _log_health_event(
                    "watchlist_health", "ESCALATED_BLOCKED",
                    "HIGH",
                    f"{len(blocked)} blocked actions on {sym}: {[a['label'] for a in blocked]}",
                    action="escalated_to_operator", symbol=sym)

        # ── Telegram approval for MEDIUM/HIGH safe actions ──
        if need_approval and not dry_run:
            approval_result = _send_telegram_approval(sym, diagnosis, need_approval)
            report["pending_items"].append({
                "symbol": sym,
                "diagnosis": diagnosis.get("summary", ""),
                "severity": diagnosis.get("severity", "MEDIUM"),
                "actions": need_approval,
                "approval_state": approval_result.get("state", "error"),
                "automatable": approval_result.get("automatable", 0),
                "escalated": approval_result.get("escalated", 0),
            })
            if approval_result.get("ok"):
                report["pending_approval"] += 1
                _log_health_event(
                    "watchlist_health", "PENDING_APPROVAL",
                    diagnosis.get("severity", "HIGH"),
                    f"Approval for {len(need_approval)} actions on {sym}",
                    action="telegram_approval", symbol=sym)
            else:
                report["errors"].append(
                    f"Approval request failed for {sym}: {approval_result.get('error')}")

        elif need_approval and dry_run:
            report["pending_items"].append({
                "symbol": sym,
                "diagnosis": diagnosis.get("summary", ""),
                "severity": diagnosis.get("severity", "MEDIUM"),
                "actions": need_approval,
                "approval_state": "dry_run",
            })

        # Rate-limit API calls
        if not dry_run and report["auto_fixed"] > 0:
            time.sleep(0.5)

    return report


# ── Dashboard data provider ────────────────────────────────────────────────
def get_dashboard_state() -> dict:
    """Provide dashboard-queryable state for the operator."""
    now = datetime.now(timezone.utc)

    # Recent health events
    events = _db_query("""
        SELECT component, event_type, severity, message, action_taken, success,
               symbol, created_at
        FROM system_health_events
        WHERE component = 'watchlist_health'
        ORDER BY created_at DESC LIMIT 50
    """)

    # Pending approvals
    approvals = _db_query("""
        SELECT symbol, diagnosis, actions, status, message_id, created_at, resolved_at
        FROM watchlist_health_approvals
        WHERE status = 'pending'
        ORDER BY created_at DESC LIMIT 20
    """)

    # Recent fixed items
    fixed = _db_query("""
        SELECT component, event_type, message, action_taken, symbol, created_at
        FROM system_health_events
        WHERE component = 'watchlist_health' AND event_type = 'AUTO_FIXED'
        ORDER BY created_at DESC LIMIT 30
    """)

    # Degradation summary
    summary = _db_query("""
        SELECT severity, COUNT(*) as count
        FROM system_health_events
        WHERE component = 'watchlist_health'
        AND created_at > NOW() - INTERVAL '24 hours'
        GROUP BY severity
        ORDER BY CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END
    """)

    return {
        "timestamp": now.isoformat(),
        "recent_events": events,
        "pending_approvals": approvals,
        "recently_fixed": fixed,
        "severity_summary": summary,
    }


# ── CLI ────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Watchlist Autonomous Remediation Agent")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Scan only, no actions taken")
    p.add_argument("--apply", action="store_true",
                   help="Execute auto-fixes and request approvals")
    p.add_argument("--limit", type=int, default=30,
                   help="Max symbols to scan")
    p.add_argument("--symbol", type=str,
                   help="Scan a single symbol")
    p.add_argument("--dashboard", action="store_true",
                   help="Output dashboard state as JSON")
    p.add_argument("--output-json", type=str,
                   help="Write report JSON to file")
    args = p.parse_args()

    if args.apply:
        args.dry_run = False

    if args.dashboard:
        state = get_dashboard_state()
        print(json.dumps(state, indent=2, default=str))
        return

    if args.symbol:
        # Single-symbol scan
        sym = args.symbol.upper()
        packet = _db_query("""
            SELECT packet_id, packet FROM decision_packets
            WHERE upper(symbol)=%s AND superseded_by IS NULL
        """, (sym,), fetch="one")
        packet_info = packet.get("packet") or {} if packet else {}
        packet_info["packet_id"] = packet.get("packet_id")

        synthesis = _db_query("""
            SELECT * FROM watchlist_final_synthesis
            WHERE upper(symbol)=%s ORDER BY created_at DESC LIMIT 1
        """, (sym,), fetch="one")
        if synthesis:
            packet_info["cio_synthesis"] = synthesis
        packet_info["ticket_review"] = (packet.get("packet") or {}).get("ticket_review") or {}

        finding = _scan_single_symbol(sym, packet_info)
        diagnosis = _diagnose_with_deepseek(sym, finding["issues"], packet_info) if finding["degraded"] else {}
        actions = diagnosis.get("recommended_actions", []) if diagnosis else []
        executed = []

        # In apply mode, execute safe auto-approve actions
        if not args.dry_run and actions:
            safe = [a for a in actions if _guard_action(a.get("id", ""))]
            for action in safe:
                if action.get("auto_approve", True):
                    r = _execute_action(sym, action["id"])
                    executed.append({
                        "action": action["id"],
                        "label": action.get("label", ""),
                        "ok": r.get("ok"),
                        "detail": r.get("detail", "")[:200],
                    })
                    if r.get("ok"):
                        log.info(f"  ✅ {action['id']} {sym}")
                        _log_health_event("watchlist_health", "AUTO_FIXED", finding.get("severity", "MEDIUM"),
                                          f"Manual {action['id']} for {sym}", action=action["id"],
                                          success=True, symbol=sym)

        result = {
            "symbol": sym,
            "finding": finding,
            "diagnosis": diagnosis if finding["degraded"] else None,
            "executed": executed,
        }
        print(json.dumps(result, indent=2, default=str))
        return

    report = scan_watchlist(limit=args.limit, dry_run=args.dry_run)

    mode = "DRY RUN" if args.dry_run else "ACTIVE"
    log.info(
        f"[{mode}] Scanned {report['scanned']} symbols: "
        f"{report['degraded']} degraded, "
        f"{report['auto_fixed']} auto-fixed, "
        f"{report['pending_approval']} pending approval"
    )

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    # Return non-zero if there are HIGH-severity unresolved items
    high_pending = [p for p in report.get("pending_items", [])
                    if p.get("severity") == "HIGH"]
    if high_pending and not args.dry_run:
        sys.exit(2)


if __name__ == "__main__":
    main()
