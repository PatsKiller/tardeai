#!/usr/bin/env python3
"""pipeline_health_agent.py — Pipeline Execution Health & Auto-Remediation Agent.

Scans every registered pipeline for missed runs, failed jobs, and stale data.
Uses pipeline_schedule + pipeline_runs tables (shared with pipeline_watchdog.py).
Auto-fixes safe failures (re-run idempotent pipelines). Escalates risky fixes
to the operator via Telegram.

HARD BOUNDARIES (enforced in _guard_action):
- NO 2FA — never touches broker approval
- NO TRADING — never places/modifies/cancels trades
- NO BROKER ACCOUNT MANAGEMENT — never reads/writes holdings.json
- ALL broker/trade/2fa issues ESCALATE TO OPERATOR

Runs every 10 min.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [pl-health] %(message)s")
log = logging.getLogger("pipeline_health_agent")

# ══════════════════════════════════════════════════════════════════════════
# HARD BOUNDARIES
# ══════════════════════════════════════════════════════════════════════════

SAFE_ACTIONS = frozenset({
    "retry_pipeline",        # Re-run a failed/missed pipeline via subprocess
    "retry_pipeline_batch",  # Re-run multiple stalled pipelines
    "re_run_ingest",         # Re-run data ingestion (youtube, news, etc.)
    "re_run_discovery",      # Re-run discovery pipeline
    "flush_queue",           # Flush stuck queue entries
})

BANNED_PREFIXES = ("bk", "bkr", "broker", "trade", "order", "exec", "alpaca",
                    "schwab", "snap", "fidelity", "moomoo", "2fa", "approve_order",
                    "cancel", "modify", "atm", "position_close", "sell", "buy")

# Pipe to Safe_actions allowlist mapping
PIPE_SAFE = {
    "youtube_transcript_ingest.py": "re_run_ingest",
    "hermes_youtube_discovery.py": "re_run_discovery",
    "aegis_transcript_discovery.py": "re_run_discovery",
    "transcript_processor.py": "re_run_ingest",
    "transcript_tagger.py": "re_run_ingest",
    "youtube_cookie_health_check.py": "re_run_ingest",
    "transcript_slow_processor.py": "re_run_ingest",
    "news_ingestion": "re_run_ingest",
    "social_ingest": "re_run_ingest",
    "finviz_enrichment": "retry_pipeline",
    "finviz_screener_runner": "retry_pipeline",
    "rag_indexer": "retry_pipeline",
    "premarket_watcher": "retry_pipeline",
    "incubator_llm_screener": "retry_pipeline",
    "incubator_proposal_promoter": "retry_pipeline",
    "agent_outcome_scorer": "retry_pipeline",
}

# ── DB helpers ────────────────────────────────────────────────────────────
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
        return [dict(zip(cols, r)) for r in cur.fetchall()]
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
        full_message = (f"[{symbol}] {message}" if symbol else message)[:500]
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


# ── Telegram ──────────────────────────────────────────────────────────────
def _send_telegram_approval(pipeline_key: str, diagnosis: dict,
                             actions: list[dict]) -> dict:
    try:
        from telegram_alert import chokepoint_send

        automatable = [a for a in actions if _guard_action(a.get("id", ""))]
        escalated = [a for a in actions if not _guard_action(a.get("id", ""))]

        sev = diagnosis.get("severity", "MEDIUM")
        emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "⚪")

        lines = [
            f"{emoji} **Pipeline Health: {pipeline_key}**",
            f"*Diagnosis:* {diagnosis.get('summary', 'Unknown')}",
            f"*Cost:* {diagnosis.get('estimated_cost', 'free')}",
        ]

        if automatable:
            lines.append("\n*Auto-fixable:*")
            for a in automatable:
                lines.append(f"  - {a['label']}")
            action_ids = "+".join(a["id"] for a in automatable)
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ Approve", "callback_data": f"pl_health_approve:{pipeline_key}:{action_ids}"}],
                    [{"text": "❌ Deny", "callback_data": f"pl_health_deny:{pipeline_key}"}],
                ]
            }
        else:
            keyboard = None

        if escalated:
            lines.append("\n*Escalated (manual only):*")
            for a in escalated:
                lines.append(f"  ❗ {a['label']}")

        msg = "\n".join(lines)
        result = chokepoint_send(msg, reply_markup=keyboard, parse_mode="Markdown")
        message_id = result.get("message_id") if isinstance(result, dict) else None

        conn = _get_conn()
        if conn:
            try:
                cur = conn.cursor()
                now = datetime.now(timezone.utc)
                cur.execute("""INSERT INTO pipeline_health_approvals
                    (pipeline_key, diagnosis, actions, status, message_id, created_at)
                    VALUES (%s, %s, %s, 'pending', %s, %s)""",
                    [pipeline_key, json.dumps(diagnosis, default=str),
                     json.dumps(actions, default=str),
                     str(message_id) if message_id else None, now])
                conn.commit()
            except Exception as e:
                log.warning(f"Failed to store approval: {e}")
            finally:
                try: conn.close()
                except Exception: pass

        return {"ok": True, "message_id": message_id, "state": "pending_approval"}
    except Exception as e:
        log.error(f"Telegram approval failed: {e}")
        return {"ok": False, "error": str(e)[:200]}


# ── DeepSeek diagnosis ────────────────────────────────────────────────────
def _diagnose_with_deepseek(pipeline_key: str, issues: list[str],
                             context: dict) -> dict:
    api_key = os.environ.get("deepseek_tradeai", "").strip()
    if not api_key:
        return _deterministic_diagnosis(pipeline_key, issues, context)

    prompt = f"""Pipeline {pipeline_key} is DEGRADED.

Issues: {json.dumps(issues)}
Context: {json.dumps(context, default=str)}

Diagnose root cause. Recommend minimal corrective actions.
Reply ONLY JSON:
{{"severity":"LOW|MEDIUM|HIGH","summary":"one-line diagnosis",
 "recommended_actions":[{{"id":"action","label":"readable","risk":"LOW|MEDIUM|HIGH",
 "auto_approve":true|false}}],
 "estimated_cost":"free|paid:<$0.01",
 "root_cause":"why","needs_approval_reason":null or string}}"""

    try:
        import requests
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={"model": "deepseek-v4-flash",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": 512},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        log.warning(f"DeepSeek diagnosis skipped for {pipeline_key}: {e}")

    return _deterministic_diagnosis(pipeline_key, issues, context)


def _deterministic_diagnosis(pipeline_key: str, issues: list[str],
                              context: dict) -> dict:
    actions = []
    severity = "MEDIUM"

    has_missed = any("missed" in i.lower() for i in issues)
    has_failed = any("failed" in i.lower() for i in issues)
    has_stale_data = any("stale" in i.lower() or "0 rows" in i.lower()
                         for i in issues)

    if has_missed or has_failed:
        severity = "HIGH" if has_failed else "MEDIUM"
        safe_action = PIPE_SAFE.get(pipeline_key, "retry_pipeline")
        actions.append({
            "id": safe_action,
            "label": f"Re-run {pipeline_key}",
            "risk": "LOW",
            "auto_approve": True,
        })

    return {
        "severity": severity,
        "summary": f"{pipeline_key}: {len(issues)} issues",
        "recommended_actions": actions,
        "root_cause": "deterministic",
        "estimated_cost": "free",
        "needs_approval_reason": None,
    }


# ── Guard ─────────────────────────────────────────────────────────────────
def _guard_action(action_id: str) -> bool:
    if not isinstance(action_id, str):
        return False
    aid = action_id.lower().strip()
    if aid not in SAFE_ACTIONS:
        return False
    for prefix in BANNED_PREFIXES:
        if aid.startswith(prefix):
            log.critical(f"BLOCKED banned action '{action_id}'")
            return False
    return True


# ── Scan ──────────────────────────────────────────────────────────────────
def _scan_pipelines() -> list[dict]:
    """Scan all active pipeline_schedule entries against pipeline_runs."""
    now = datetime.now(timezone.utc)
    weekend = now.weekday() >= 5
    findings = []

    schedules = _db_query("""
        SELECT script_name, display_name, expected_hour, expected_min,
               max_latency_min, min_rows, critical, run_days
        FROM pipeline_schedule WHERE active = true
        ORDER BY script_name
    """)

    for s in (schedules or []):
        sn = s["script_name"]
        rd = s.get("run_days", "1-5") or "*"

        # Skip if not scheduled today
        if rd != "*":
            if rd == "1-5" and weekend:
                continue
            if rd == "0,6" and not weekend:
                continue
            try:
                allowed = set()
                for part in rd.split(","):
                    part = part.strip()
                    if "-" in part:
                        a, b = part.split("-", 1)
                        allowed.update(range(int(a), int(b) + 1))
                    else:
                        allowed.add(int(part))
                if now.weekday() not in allowed:
                    continue
            except Exception:
                pass

        # Calculate when this pipeline should have last run
        expected_dt = now.replace(hour=s["expected_hour"],
                                   minute=s["expected_min"], second=0, microsecond=0)
        if expected_dt > now:
            expected_dt -= timedelta(days=1)  # hasn't happened yet today
        deadline = expected_dt + timedelta(minutes=s["max_latency_min"])

        # Status
        if now < deadline:
            status = "WAITING"
        else:
            # Check if it ran
            run = _db_query("""
                SELECT status, finished_at, duration_seconds, summary
                FROM pipeline_runs
                WHERE pipeline_key = %s
                  AND created_at >= %s
                ORDER BY created_at DESC LIMIT 1
            """, (sn, expected_dt - timedelta(minutes=5)), fetch="one")

            if not run:
                status = "MISSED"
            elif run.get("status") == "failed":
                status = "FAILED"
            elif run.get("status") == "success":
                status = "OK"
            else:
                status = "UNKNOWN"

        # Data check
        data_rows = 0
        target_tables = {
            "youtube_transcript_ingest.py": "youtube_transcripts",
            "youtube_cookie_health_check.py": None,
            "hermes_youtube_discovery.py": "hermes_sources",
            "aegis_transcript_discovery.py": "transcript_observations",
            "transcript_processor.py": "youtube_transcripts",
            "transcript_tagger.py": "youtube_transcripts",
            "transcript_slow_processor.py": "youtube_transcripts",
            "news_ingestion": "news_articles",
            "social_ingest": "social_sentiment",
            "finviz_enrichment": "finviz_screeners",
            "rag_indexer": "rag_entries",
            "premarket_watcher": "premarket_signals",
        }
        tbl = target_tables.get(sn)
        if tbl:
            try:
                r = _db_query(
                    f"SELECT count(*) as cnt FROM {tbl} WHERE created_at > %s",
                    (now - timedelta(hours=36),), fetch="one")
                data_rows = int(r.get("cnt", 0)) if r else 0
            except Exception:
                data_rows = -1

        last_run_at = run.get("finished_at") if run else None
        issues = []
        if status == "MISSED":
            issues.append(f"Pipeline not run within {s['max_latency_min']}min of expected {s['expected_hour']:02d}:{s['expected_min']:02d}")
        elif status == "FAILED":
            issues.append(f"Last run failed: {run.get('summary', 'unknown error')[:120]}")
        elif status == "OK":
            if s["min_rows"] > 0 and data_rows >= 0 and data_rows < s["min_rows"]:
                issues.append(f"Ran OK but only {data_rows} rows produced (min {s['min_rows']})")

        if issues:
            findings.append({
                "pipeline_key": sn,
                "display_name": s["display_name"],
                "status": status,
                "last_run_at": str(last_run_at) if last_run_at else None,
                "data_rows": data_rows,
                "max_latency_min": s["max_latency_min"],
                "critical": s.get("critical", False),
                "issues": issues,
            })

    return findings


# ── Executor ──────────────────────────────────────────────────────────────
def _execute_action(pipeline_key: str, action_id: str) -> dict:
    if not _guard_action(action_id):
        return {"action": action_id, "pipeline_key": pipeline_key, "ok": False,
                "detail": "BLOCKED: not in SAFE_ACTIONS"}

    result = {"action": action_id, "pipeline_key": pipeline_key, "ok": False,
              "detail": ""}
    try:
        import subprocess
        cmd = [sys.executable, f"scripts/{pipeline_key}"]
        # Add common flags
        if "discovery" in pipeline_key:
            cmd.append("--apply")
        if "ingest" in pipeline_key:
            cmd.append("--all-channels")

        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT),
                              capture_output=True, text=True, timeout=300)
        result["ok"] = proc.returncode == 0
        result["detail"] = (proc.stdout.strip() or proc.stderr.strip())[:200]
        if result["ok"]:
            log.info(f"  OK {pipeline_key}: rc={proc.returncode}")
        else:
            log.warning(f"  FAIL {pipeline_key}: rc={proc.returncode}")
    except subprocess.TimeoutExpired:
        result["detail"] = "timeout after 300s"
        log.warning(f"  TIMEOUT {pipeline_key}")
    except Exception as e:
        result["detail"] = str(e)[:200]
        log.error(f"  ERROR {pipeline_key}: {e}")

    return result


# ── Main scan + fix ───────────────────────────────────────────────────────
def scan_and_remediate(limit: int = 50, dry_run: bool = True) -> dict:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if dry_run else "active",
        "total_pipelines": 0,
        "healthy": 0,
        "issues_found": 0,
        "auto_fixed": 0,
        "pending_approval": 0,
        "fixed_actions": [],
    }

    findings = _scan_pipelines()
    report["total_pipelines"] = len(findings)

    healthy = [f for f in findings if not f.get("issues")]
    degraded = [f for f in findings if f.get("issues")]
    report["healthy"] = len(healthy)
    report["issues_found"] = len(degraded)

    for f in degraded[:limit]:
        pk = f["pipeline_key"]
        diagnosis = _diagnose_with_deepseek(pk, f["issues"], f)
        actions = diagnosis.get("recommended_actions", [])
        if not actions:
            continue

        safe = [a for a in actions if _guard_action(a.get("id", ""))]
        is_critical = f.get("critical") or diagnosis.get("severity") == "HIGH"

        if is_critical:
            if not dry_run:
                _send_telegram_approval(pk, diagnosis, safe)
                report["pending_approval"] += 1
        else:
            for action in safe:
                if not dry_run:
                    r = _execute_action(pk, action["id"])
                    report["fixed_actions"].append({
                        "pipeline_key": pk, "action": action["id"],
                        "ok": r.get("ok"), "detail": r.get("detail", "")[:200],
                    })
                    if r.get("ok"):
                        report["auto_fixed"] += 1
                        _log_health_event("pipeline_health", "AUTO_FIXED",
                                          diagnosis.get("severity", "LOW"),
                                          f"Re-ran {pk}", action=action["id"],
                                          success=True)
                    else:
                        _log_health_event("pipeline_health", "AUTO_FIX_FAILED",
                                          "WARN",
                                          f"Re-run failed: {pk}", action=action["id"],
                                          success=False)

    return report


# ── Dashboard data ────────────────────────────────────────────────────────
def get_dashboard_data() -> dict:
    pipelines = _scan_pipelines()
    events = _db_query("""
        SELECT severity, event_type, message, action_taken, success, created_at
        FROM system_health_events
        WHERE component = 'pipeline_health'
        ORDER BY created_at DESC LIMIT 50
    """) or []
    approvals = _db_query("""
        SELECT pipeline_key, diagnosis, actions, status, created_at
        FROM pipeline_health_approvals WHERE status = 'pending'
        ORDER BY created_at DESC LIMIT 20
    """) or []

    return {
        "pipelines": pipelines,
        "total": len(pipelines),
        "healthy": sum(1 for p in pipelines if not p.get("issues")),
        "degraded": sum(1 for p in pipelines if p.get("issues")),
        "critical": sum(1 for p in pipelines if p.get("issues") and p.get("critical")),
        "events": events,
        "pending_approvals": approvals,
    }


# ── CLI ───────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Pipeline Health Agent")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--dump", action="store_true",
                   help="Output full scan as JSON")
    p.add_argument("--dashboard", action="store_true",
                   help="Output dashboard state as JSON")
    args = p.parse_args()

    if args.apply:
        args.dry_run = False

    if args.dashboard:
        print(json.dumps(get_dashboard_data(), indent=2, default=str))
        return

    if args.dump:
        findings = _scan_pipelines()
        print(json.dumps(findings, indent=2, default=str))
        return

    report = scan_and_remediate(limit=args.limit, dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "ACTIVE"
    log.info(
        f"[{mode}] {report['total_pipelines']} pipelines: "
        f"{report['healthy']} healthy, {report['issues_found']} issues, "
        f"{report['auto_fixed']} fixed, {report['pending_approval']} pending"
    )


if __name__ == "__main__":
    main()
