#!/usr/bin/env python3
"""hermes_health_inspector.py — Hermes Health Inspector Agent (Layer 2)

Reads health surfaces from health_agent.py, system_health_agent.py, pipeline_freshness_monitor,
and hermes_pipeline_health.py. Fuses signals using local LLM (Ollama gemma3:4b) to identify
root cause. Stages findings in hermes_research_intelligence DB table. For P0/P1: writes to
claude_escalation_queue.json and staleness_escalation_queue.json.

Safety controls:
  - File lock: /tmp/hermes_health_inspector.lock
  - Kill-switch: ~/.local/state/tradeai/HERMES_HEALTH_DISABLED
  - Daily cap: 3 findings/day
  - Max runtime: 300s
  - Read-only (no broker/proposal/trade/trading access)

Usage:
    .venv/bin/python scripts/hermes_health_inspector.py
    .venv/bin/python scripts/hermes_health_inspector.py --dry-run
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sys
import time
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LOCK_FILE = Path("/tmp/hermes_health_inspector.lock")
KILL_FILE = Path.home() / ".local" / "state" / "tradeai" / "HERMES_HEALTH_DISABLED"
MAX_RUNTIME_S = 300
DAILY_CAP = 3
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "hermes_health_inspector.log"
ESCALATION_QUEUE = LOG_DIR / "claude_escalation_queue.json"
STALENESS_QUEUE = PROJECT_ROOT / "data" / "runtime" / "staleness_escalation_queue.json"
TODAY = date.today().isoformat()


def _log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts} [hermes-health-inspector] {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _check_kill_switch():
    if KILL_FILE.exists():
        _log(f"ABORT: Kill switch active ({KILL_FILE})")
        sys.exit(1)


def _acquire_lock():
    try:
        fd = open(LOCK_FILE, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (IOError, OSError):
        _log("ABORT: Another instance running (lockfile)")
        sys.exit(1)


def _get_db_conn():
    try:
        from db_adapter import _get_conn
        return _get_conn()
    except Exception as e:
        _log(f"DB connection failed: {e}")
        return None


_heartbeat_conn = None
_hb = None


def _init_heartbeat(conn, dry_run=False):
    """Register agent heartbeat in a separate DB connection."""
    global _heartbeat_conn, _hb
    try:
        from lib.agent_heartbeat import AgentHeartbeat
        _heartbeat_conn = _get_db_conn()
        if _heartbeat_conn:
            _hb = AgentHeartbeat(_heartbeat_conn, 'hermes_health_inspector', task='pipeline_health_sweep')
            _hb.register()
            _log("Heartbeat registered for hermes_health_inspector")
    except Exception as e:
        _log(f"Heartbeat init skipped: {e}")


def _emit_heartbeat():
    """Emit a heartbeat pulse."""
    global _hb
    if _hb:
        try:
            _hb.heartbeat()
        except Exception:
            pass


def _mark_heartbeat_done(success=True, error=None):
    """Mark agent as done."""
    global _hb
    if _hb:
        try:
            _hb.mark_done(success, error)
        except Exception:
            pass


def _daily_count(conn) -> int:
    """Count findings staged by this agent today."""
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM hermes_research_intelligence
               WHERE hermes_agent_name = 'hermes_health_inspector'
                 AND created_at::date = CURRENT_DATE""")
        r = cur.fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


def _fetch_health_agent() -> dict | None:
    """Fetch health_agent.py output from local API."""
    try:
        req = urllib.request.Request("http://localhost:7777/api/v2/health", method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        _log(f"Failed to fetch /api/v2/health: {e}")
        return None


def _read_freshness_monitor() -> dict | None:
    """Read pipeline_freshness_monitor output from DB or log."""
    try:
        conn = _get_db_conn()
        if not conn:
            return None
        cur = conn.cursor()
        # Read latest pipeline_freshness snapshot from health_agent_snapshots
        cur.execute(
            """SELECT findings FROM health_agent_snapshots
               WHERE captured_at > now() - interval '4 hours'
               ORDER BY captured_at DESC LIMIT 1""")
        r = cur.fetchone()
        if r and r[0]:
            findings = json.loads(r[0]) if isinstance(r[0], str) else r[0]
            pipeline_findings = [f for f in findings if f.get("category") == "pipeline_freshness"]
            return {"pipeline_freshness": pipeline_findings, "count": len(pipeline_findings)}
        return None
    except Exception as e:
        _log(f"Freshness monitor read failed: {e}")
        return None


def _read_hermes_pipeline_health() -> dict | None:
    """Read hermes_pipeline_health.py log."""
    try:
        log_path = LOG_DIR / "hermes_pipeline_health.log"
        if not log_path.exists():
            return None
        tail = log_path.read_text(errors="replace")[-4000:]
        return {"tail": tail[-2000:]}
    except Exception:
        return None


def _fuse_signals(
    health_snap: dict | None,
    freshness: dict | None,
    hermes_health: dict | None,
    dry_run: bool = False,
) -> list[dict]:
    """Fuse health signals using local LLM (Ollama gemma3:4b) to identify root cause.
    Returns list of findings with severity, evidence, remediation."""
    findings = []

    # Phase 1: Deterministic aggregation — collect all stale/degraded items
    stale_items: list[dict] = []

    if health_snap:
        for f in health_snap.get("findings") or []:
            if f.get("severity") in ("critical", "warning"):
                stale_items.append({
                    "source": "health_agent",
                    "type": f.get("type"),
                    "severity": f.get("severity"),
                    "message": f.get("message", "")[:300],
                    "category": f.get("category"),
                })

    if freshness:
        for f in freshness.get("pipeline_freshness") or []:
            if f.get("severity") in ("critical", "warning"):
                stale_items.append({
                    "source": "pipeline_freshness",
                    "type": f.get("type"),
                    "severity": f.get("severity"),
                    "message": f.get("message", "")[:300],
                })

    if not stale_items:
        _log("No stale or degraded items found — all clear")
        return []

    _log(f"Found {len(stale_items)} stale/degraded items to analyze")

    # Phase 2: LLM fusion for root cause (gemma3:4b via Ollama)
    if len(stale_items) > 20:
        stale_items = sorted(stale_items, key=lambda x: (0 if x.get("severity") == "critical" else 1))[:20]

    critical_count = sum(1 for s in stale_items if s.get("severity") == "critical")
    warning_count = sum(1 for s in stale_items if s.get("severity") == "warning")

    # Build prompt for LLM
    items_text = "\n".join(
        f"- [{s['severity'].upper()}] {s['source']}:{s.get('type')} — {s.get('message', '')[:150]}"
        for s in stale_items
    )

    prompt = (
        f"/no_think You are a Trade AI system health analyst. Analyze these stale indicators:\n\n"
        f"Total: {len(stale_items)} ({critical_count} critical, {warning_count} warning)\n\n"
        f"{items_text}\n\n"
        f"Determine:\n"
        f"1. ROOT CAUSE: What is the common underlying cause (if any)?\n"
        f"2. PRIORITY: Rank by P0/P1/P2/P3 severity\n"
        f"3. RECOMMENDATION: What should be done?\n\n"
        f"Respond in JSON format: {{\"root_cause\": \"...\", \"priority\": \"P0|P1|P2|P3\", "
        f"\"recommendation\": \"...\", \"evidence\": \"...\", \"linked_producers\": [...]}}"
    )

    if dry_run:
        root_cause = "DRY_RUN: Deterministic aggregation only"
        priority = "P1" if critical_count > 0 else "P2"
        recommendation = f"{len(stale_items)} items need attention: {critical_count} critical, {warning_count} warning"
        evidence = json.dumps(stale_items[:5], default=str)[:500]
    else:
        try:
            import requests
            resp = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": os.getenv("LOCAL_LLM_MODEL", "gemma3:4b"),
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 400, "temperature": 0.2},
                },
                timeout=90,
            )
            if resp.ok:
                llm_out = resp.json().get("response", "")
                try:
                    parsed = json.loads(llm_out)
                    root_cause = parsed.get("root_cause", llm_out[:200])
                    priority = parsed.get("priority", "P2")
                    recommendation = parsed.get("recommendation", llm_out[:200])
                    evidence = parsed.get("evidence", llm_out[:300])
                except json.JSONDecodeError:
                    root_cause = llm_out[:300]
                    priority = "P2"
                    recommendation = "See LLM analysis"
                    evidence = llm_out[:400]
            else:
                root_cause = f"LLM unreachable (HTTP {resp.status_code})"
                priority = "P1" if critical_count > 0 else "P2"
                recommendation = f"Manual inspection needed: {critical_count} critical, {warning_count} warning items"
                evidence = json.dumps(stale_items[:5], default=str)[:500]
        except Exception as e:
            root_cause = f"LLM analysis failed: {e}"
            priority = "P1" if critical_count > 0 else "P2"
            recommendation = f"Manual inspection needed — LLM unavailable"
            evidence = json.dumps(stale_items[:5], default=str)[:500]

    # Map priority to severity
    sev_map = {"P0": "critical", "P1": "critical", "P2": "warning", "P3": "info"}
    severity = sev_map.get(priority, "warning")

    findings.append({
        "source_agent": "hermes_health_inspector",
        "priority": priority,
        "severity": severity,
        "root_cause": root_cause,
        "recommendation": recommendation,
        "evidence": evidence,
        "stale_count": len(stale_items),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "linked_producers": [s.get("type") for s in stale_items[:10] if s.get("type")],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    })

    return findings


def _stage_finding(source, summary, severity='P2', confidence_score=0.5, metadata=None):
    """Stage a single agent finding in hermes_research_intelligence."""
    conn = _get_db_conn()
    if not conn:
        return None
    try:
        sev = "critical" if severity in ("P0",) else ("warning" if severity in ("P1",) else "info")
        pri = severity
        meta = metadata or {}
        cur = conn.cursor()
        linked = meta.get("linked_producers", [])
        producer_str = ",".join(linked[:5]) if linked else "unknown"
        pattern_sig = f"agent_liveness::{pri}::{meta.get('agent_id', 'unknown')}"[:200]
        cur.execute(
            """INSERT INTO hermes_research_intelligence
               (source, hermes_agent_name, research_type, topic, summary, thesis, evidence_json,
                confidence_score, status, tags, pattern_signature, freshness_date, model_used,
                created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, %s, NOW(), NOW())
               RETURNING id""",
            (
                source or "hermes",
                "hermes_health_inspector",
                "agent_liveness",
                f"agent_liveness_{pri}",
                f"Agent Liveness: {summary[:200]}",
                summary[:500],
                json.dumps(meta),
                float(confidence_score),
                "staged",
                "{" + ",".join(['"agent_liveness"', f'"{sev}"', f'"{pri}"']) + "}",
                pattern_sig,
                "watchdog",
            ),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        _log(f"Staged agent liveness finding id={row_id} for {meta.get('agent_id', 'unknown')}")
        return row_id
    except Exception as e:
        _log(f"Failed to stage agent finding: {e}")
        return None


def _stage_findings(conn, findings: list[dict]) -> tuple[int, list[dict]]:
    """Stage findings in hermes_research_intelligence DB table.
    Returns (staged_count, list of staged records with ids and pattern info)."""
    if not conn:
        return 0, []
    staged = 0
    staged_records = []
    try:
        cur = conn.cursor()
        for f in findings:
            sev = f.get("severity", "warning")
            pri = f.get("priority", "P2")
            root_cause = f.get("root_cause", "")[:100]
            linked = f.get("linked_producers", [])
            producer_str = ",".join(linked[:5]) if linked else "unknown"
            pattern_sig = f"stale::{pri}::{[p[:30] for p in linked[:3]]}"[:200]
            cur.execute(
                """INSERT INTO hermes_research_intelligence
                   (source, hermes_agent_name, research_type, topic, summary, thesis, evidence_json,
                    confidence_score, status, tags, pattern_signature, freshness_date, model_used,
                    created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, %s, NOW(), NOW())
                   RETURNING id""",
                (
                    "hermes",
                    f.get("source_agent", "hermes_health_inspector"),
                    "health_inspection",
                    f"{sev}_{pri}",
                    f"Hermes Health Inspection: {sev.upper()} — {root_cause}",
                    f.get("root_cause", "")[:500],
                    json.dumps({"evidence": f.get("evidence", ""), "stale_count": f.get("stale_count", 0),
                                "priority": pri, "recommendation": f.get("recommendation", ""),
                                "linked_producers": linked}),
                    float(0.80 if pri == "P0" else 0.65 if pri == "P1" else 0.50 if pri == "P2" else 0.35),
                    "staged",
                    "{" + ",".join(['"health_inspection"', f'"{sev}"', f'"{pri}"'] + 
                                   [f'"{p}"' for p in linked[:5]]) + "}",
                    pattern_sig,
                    "local_llm",
                ),
            )
            row_id = cur.fetchone()[0]
            conn.commit()
            staged += 1
            staged_records.append({
                "id": row_id,
                "priority": pri,
                "root_cause": root_cause,
                "linked_producers": linked,
                "pattern_signature": pattern_sig,
            })
        _log(f"Staged {staged} finding(s) in hermes_research_intelligence")
    except Exception as e:
        _log(f"Failed to stage findings: {e}")
    return staged, staged_records


def _record_remediation_outcome(conn, finding_id, success, duration_ms, pattern_signature):
    """Record remediation outcome for a staged finding."""
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE hermes_research_intelligence
               SET remediation_success = %s,
                   remediation_duration_ms = %s,
                   pattern_signature = COALESCE(pattern_signature, %s)
               WHERE id = %s""",
            (success, duration_ms, pattern_signature, finding_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        _log(f"Failed to record remediation outcome for id={finding_id}: {e}")


def _escalate(findings: list[dict]):
    """Write P0/P1 findings to escalation queues."""
    for f in findings:
        if f.get("priority") not in ("P0", "P1"):
            continue

        item = {
            "component": "hermes_health_inspector:staleness_escalation",
            "detail": f"{f.get('priority')}: {f.get('root_cause', '')[:200]}",
            "status": f.get("severity", "critical"),
            "critical": f.get("severity") == "critical",
            "fixable": False,
            "source": "hermes_health_inspector",
            "priority": f.get("priority"),
            "recommendation": f.get("recommendation", "")[:300],
            "linked_producers": f.get("linked_producers", []),
            "captured_at": f.get("captured_at"),
        }

        # Write to main escalation queue
        try:
            existing = json.loads(ESCALATION_QUEUE.read_text()) if ESCALATION_QUEUE.exists() else []
        except Exception:
            existing = []
        existing.append(item)
        try:
            ESCALATION_QUEUE.parent.mkdir(parents=True, exist_ok=True)
            ESCALATION_QUEUE.write_text(json.dumps(existing, indent=2))
            _log("Written to claude_escalation_queue.json")
        except Exception as e:
            _log(f"Failed to write escalation queue: {e}")

        # Write to staleness-specific queue
        try:
            stale_q = json.loads(STALENESS_QUEUE.read_text()) if STALENESS_QUEUE.exists() else []
        except Exception:
            stale_q = []
        stale_q.append(item)
        try:
            STALENESS_QUEUE.parent.mkdir(parents=True, exist_ok=True)
            STALENESS_QUEUE.write_text(json.dumps(stale_q, indent=2))
            _log("Written to staleness_escalation_queue.json")
        except Exception as e:
            _log(f"Failed to write staleness queue: {e}")


def _run(dry_run: bool = False):
    _check_kill_switch()
    lock_fd = _acquire_lock()
    start_time = time.time()

    try:
        _log(f"Starting health inspection{' [DRY RUN]' if dry_run else ''}")

        conn = _get_db_conn()
        if not conn:
            _log("ERROR: No DB connection — cannot proceed")
            return

        # Register heartbeat
        _init_heartbeat(conn, dry_run)

        # Daily cap check
        done_today = _daily_count(conn)
        if done_today >= DAILY_CAP:
            _log(f"Daily cap reached ({done_today}/{DAILY_CAP}) — skipping")
            return
        remaining = DAILY_CAP - done_today
        _log(f"Daily budget: {done_today}/{DAILY_CAP} used, {remaining} remaining")

        # Read health surfaces
        _log("Fetching health surfaces...")
        health_snap = _fetch_health_agent()
        freshness = _read_freshness_monitor()
        hermes_health = _read_hermes_pipeline_health()

        # ── Agent Liveness ──
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT agent_id, last_seen, status,
                       EXTRACT(EPOCH FROM (now() - last_seen))/60 as mins
                FROM agent_heartbeat
                WHERE (now() - last_seen) > interval '10 minutes' OR status IN ('HUNG', 'DEAD')
            """)
            hung_agents = cur.fetchall()
            cur.close()

            for agent in hung_agents:
                _stage_finding(
                    source='hermes',
                    summary=f"Agent {agent[0]} is {agent[2]} — last seen {agent[3]:.0f}min ago",
                    severity='P0' if agent[3] > 30 else 'P1',
                    confidence_score=0.9,
                    metadata={"agent_id": agent[0], "status": agent[2], "mins_since_seen": agent[3]},
                )
        except Exception:
            pass  # graceful if table doesn't exist yet

        if health_snap:
            score = health_snap.get("overall_score", "N/A")
            status = health_snap.get("status", "N/A")
            findings_count = len(health_snap.get("findings") or [])
            _log(f"Health Agent: score={score} status={status} findings={findings_count}")
        else:
            _log("WARNING: Could not read health agent output")
            return

        # Fuse signals
        _log("Fusing health signals...")
        fused_findings = _fuse_signals(health_snap, freshness, hermes_health, dry_run)

        if not fused_findings:
            _log("No findings to stage — all healthy")
            return

        # Cap to remaining daily budget
        fused_findings = fused_findings[:remaining]

        # Stage in DB
        staged, staged_records = _stage_findings(conn, fused_findings)

        # Escalate P0/P1
        _escalate(fused_findings)

        elapsed = time.time() - start_time
        _log(f"Complete: {staged} finding(s) staged in {elapsed:.1f}s")

        # Mark heartbeat done
        _mark_heartbeat_done(success=True)

    except Exception as e:
        _log(f"FATAL: {e}")
        _mark_heartbeat_done(success=False, error=str(e))
        raise
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    # Hard timeout: cannot exceed MAX_RUNTIME_S
    signal.alarm(MAX_RUNTIME_S)

    ap = argparse.ArgumentParser(description="Hermes Health Inspector (Layer 2)")
    ap.add_argument("--dry-run", action="store_true", help="Analyze without calling LLM or writing")
    args = ap.parse_args()

    _run(dry_run=args.dry_run)
