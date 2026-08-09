#!/usr/bin/env python3
"""cio_heartbeat.py — Autonomous CIO heartbeat: detect material changes, manage action ledger.

Runs as a one-shot bounded sweep. Deterministic collection only — no model calls,
no Telegram, no broker/order/risk/2FA authority.

Cycle:
  1. Build CIO financial snapshot (deterministic, 17 domains)
  2. Compare to previous snapshot; detect material changes
  3. Create/update/close CIO action items in the event-sourced ledger
  4. Report summary to stdout (shadow mode — no Telegram delivery)

Usage:
  python3 scripts/cio_heartbeat.py [--interval-minutes 30] [--max-actions 5]

The action ledger lives at data/cio/cio_action_ledger.jsonl.
Snapshots are stored at data/cio/cio_heartbeat_snapshots.jsonl.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ── Constants ────────────────────────────────────────────────────────────────

DATA_DIR = PROJECT_ROOT / "data" / "cio"
SNAPSHOT_PATH = DATA_DIR / "cio_heartbeat_snapshots.jsonl"
ACTION_LEDGER_PATH = DATA_DIR / "cio_action_ledger.jsonl"

# Domains from the CIO Data Broker (matches cio_portfolio.py's CIO_DOMAINS)
DETERMINISTIC_DOMAINS = [
    "portfolio",
    "risk",
    "watch",
    "rotation",
    "income",
    "reconciliation",
    "hermes_research",
]

# Notification priority tiers
NOTIFICATION_PRIORITIES = ("Critical", "High", "Medium", "Low", "Info")

# Priority computation: (change_type, domain) → notification_priority
_PRIORITY_MAP: dict[tuple[str, str], str] = {
    ("DOMAIN_WENT_STALE", "risk"): "Critical",
    ("DOMAIN_WENT_STALE", "reconciliation"): "Critical",
    ("DOMAIN_WENT_STALE", "portfolio"): "High",
    ("DOMAIN_WENT_STALE", "watch"): "High",
    ("DOMAIN_WENT_STALE", "rotation"): "Medium",
    ("DOMAIN_WENT_STALE", "income"): "Medium",
    ("DATA_CHANGED", "portfolio"): "High",
    ("DATA_CHANGED", "risk"): "High",
    ("DATA_CHANGED", "watch"): "Medium",
    ("DATA_CHANGED", "rotation"): "Medium",
    ("DATA_CHANGED", "income"): "Low",
    ("DATA_CHANGED", "hermes_research"): "Low",
    ("FIRST_RUN", "system"): "Info",
    ("DOMAIN_AVAILABLE", "*"): "Info",
}

# How long before a domain goes STALE (seconds)
DOMAIN_FRESHNESS: dict[str, int] = {
    "portfolio": 3600,              # 1 hour
    "holdings": 1800,               # 30 minutes
    "risk": 3600,
    "watch": 7200,                  # 2 hours
    "reentry": 14400,               # 4 hours
    "rotation": 28800,              # 8 hours (daily rotation summary)
    "income": 86400,                # 24 hours
    "broker_reconciliation": 43200, # 12 hours
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    """Append one line to a JSONL event store with file locking."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    import fcntl
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, default=str) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read all entries from a JSONL file."""
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _last_snapshot() -> Optional[dict[str, Any]]:
    """Return the most recent heartbeat snapshot, or None."""
    entries = _read_jsonl(SNAPSHOT_PATH)
    return entries[-1] if entries else None


# ── Snapshot builder (uses Data Broker CIO projection) ────────────────────────


def build_snapshot() -> dict[str, Any]:
    """Build a deterministic CIO heartbeat snapshot via the Data Broker. Zero model calls."""
    snapshot_id = str(uuid.uuid4())[:8]
    collected_at = _now_iso()

    # Use the Data Broker CIO projection (composes portfolio/risk/watch/rotation/income/reconciliation)
    from lib.data_broker.cio_portfolio import get_cio_snapshot
    broker_snap = get_cio_snapshot(max_age_s=0)  # force fresh collection
    domains = broker_snap.get("domains", {})

    snapshot = {
        "snapshot_id": snapshot_id,
        "event_type": "CIO_HEARTBEAT_SNAPSHOT",
        "collected_at": collected_at,
        "domains": domains,
        "broker_version": broker_snap.get("version"),
        "health": broker_snap.get("health", {}),
    }
    snapshot["content_hash"] = _content_hash(snapshot)
    return snapshot


# ── Change detection ──────────────────────────────────────────────────────────


def detect_changes(
    current: dict[str, Any],
    previous: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare snapshots and return a list of material change descriptions."""
    changes: list[dict[str, Any]] = []
    current_domains = current.get("domains", {})
    previous_domains = previous.get("domains", {}) if previous else {}

    for domain in DETERMINISTIC_DOMAINS:
        cur = current_domains.get(domain, {})
        prev = previous_domains.get(domain, {})

        cur_state = cur.get("state", "NOT_APPLICABLE")
        prev_state = prev.get("state", "NOT_APPLICABLE")

        # Newly available domain
        if cur_state == "AVAILABLE" and prev_state != "AVAILABLE":
            changes.append({
                "domain": domain,
                "change_type": "DOMAIN_AVAILABLE",
                "previous_state": prev_state,
                "current_state": cur_state,
            })
        # Domain went stale
        elif cur_state == "DATA_UNAVAILABLE" and prev_state == "AVAILABLE":
            changes.append({
                "domain": domain,
                "change_type": "DOMAIN_WENT_STALE",
                "previous_state": prev_state,
                "current_state": cur_state,
            })
        # Data content changed
        elif cur_state == "AVAILABLE" and prev_state == "AVAILABLE":
            cur_data = cur.get("data", {})
            prev_data = prev.get("data", {})
            if _content_hash(cur_data) != _content_hash(prev_data):
                changes.append({
                    "domain": domain,
                    "change_type": "DATA_CHANGED",
                    "previous_hash": _content_hash(prev_data),
                    "current_hash": _content_hash(cur_data),
                })

    # Always report on first run (no previous snapshot)
    if previous is None:
        changes.insert(0, {
            "domain": "system",
            "change_type": "FIRST_RUN",
            "note": "Initial CIO heartbeat snapshot — establishing baseline",
        })

    return changes


# ── Action creation ───────────────────────────────────────────────────────────

def _compute_notification_priority(domain: str, change_type: str) -> str:
    """Compute notification_priority from change type + domain."""
    key = (change_type, domain)
    if key in _PRIORITY_MAP:
        return _PRIORITY_MAP[key]
    # Wildcard match
    wildcard = (change_type, "*")
    if wildcard in _PRIORITY_MAP:
        return _PRIORITY_MAP[wildcard]
    return "Low"


def _evaluate_escalation_triggers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate hard escalation triggers against the snapshot. Returns High+ findings."""
    triggers: list[dict[str, Any]] = []
    domains = snapshot.get("domains", {})

    pf = domains.get("portfolio", {})
    risk = domains.get("risk", {})

    # Portfolio P&L day > ±1.5%
    if pf.get("state") == "AVAILABLE" and pf.get("day_change_pct") is not None:
        day_pct = abs(float(pf.get("day_change_pct", 0)))
        if day_pct > 1.5:
            triggers.append({
                "trigger": "portfolio_day_move",
                "priority": "High",
                "detail": f"Portfolio day change {pf['day_change_pct']:+.1f}% exceeds ±1.5% threshold",
            })

    # Risk heat > 0.5
    if risk.get("state") == "AVAILABLE" and risk.get("portfolio_heat_pct") is not None:
        heat = float(risk.get("portfolio_heat_pct", 0))
        if heat > 0.5:
            triggers.append({
                "trigger": "risk_heat_elevated",
                "priority": "High",
                "detail": f"Portfolio heat {heat:.1f}% exceeds 0.5% threshold",
            })

    return triggers


def _add_flash_context(action: dict[str, Any], snapshot: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    """For Medium+ priority actions, call deepseek-v4-flash for context. Fails gracefully."""
    priority = action.get("notification_priority", "Low")
    if priority in ("Low", "Info"):
        return action  # skip — not worth the model call

    try:
        import urllib.request
        prompt = (
            f"CIO heartbeat detected a material change in the {action['domain']} domain. "
            f"Change type: {change.get('change_type', 'UNKNOWN')}. "
            f"Portfolio: {json.dumps(snapshot.get('domains', {}).get('portfolio', {}), default=str)[:200]}. "
            f"Risk: {json.dumps(snapshot.get('domains', {}).get('risk', {}), default=str)[:100]}. "
            f"In 2 sentences: what changed and why does it matter to the operator? "
            f"Be specific. No disclaimers."
        )
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps({
                "model": "deepseek-v4-flash",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 120},
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        context = (data.get("response") or "").strip()
        if context:
            action["why_now"] = f"[Flash] {context}"
            action["flash_context_added"] = True
    except Exception:
        action["why_now"] = action.get("why_now", f"Material change in {action['domain']} — operator review recommended")

    return action


def _operator_decision(priority: str) -> str:
    """Operator override language based on notification priority."""
    if priority in ("Critical", "High"):
        return "Operator review recommended"
    if priority == "Medium":
        return "Operator awareness suggested — no urgent action required"
    return "No action required — continuing to monitor"


def _create_action(
    domain: str,
    change: dict[str, Any],
    priority: str = "P2",
    notification_priority: str = "Low",
) -> dict[str, Any]:
    """Create a CIO action item payload with notification priority."""
    action_id = str(uuid.uuid4())[:8]
    change_type = change.get("change_type", "UNKNOWN")
    return {
        "cio_action_id": f"cio-hb-{action_id}",
        "created_at": _now_iso(),
        "status": "OPEN",
        "priority": priority,
        "notification_priority": notification_priority,
        "domain": domain,
        "title": f"[{change_type}] {domain} — CIO heartbeat {_now_iso()[:16]}",
        "recommendation": (
            f"Review {domain} evidence. "
            f"Previous state: {change.get('previous_state', 'N/A')}. "
            f"Current state: {change.get('current_state', change_type)}."
        ),
        "why_now": f"CIO heartbeat detected change in {domain} domain",
        "evidence_refs": [],
        "affected_accounts": [],
        "affected_symbols": [],
        "estimated_financial_impact": None,
        "estimated_tax_impact": None,
        "risk_if_done": "None (advisory review only)",
        "risk_if_not_done": f"Stale or missing {domain} evidence may degrade CIO advice",
        "alternatives": [],
        "dependencies": [],
        "operator_decision_required": notification_priority in ("Critical", "High"),
        "operator_decision": _operator_decision(notification_priority),
        "source_snapshot_id": "cio-heartbeat",
        "hermes_challenge_ref": None,
        "cio_artifact_id": None,
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def run_heartbeat(interval_minutes: int = 30, max_actions: int = 5) -> dict[str, Any]:
    """Run one CIO heartbeat cycle. Returns summary dict."""
    t0 = time.time()

    # 1. Build snapshot
    snapshot = build_snapshot()
    _append_jsonl(SNAPSHOT_PATH, snapshot)

    # 2. Detect changes
    previous = _last_snapshot()
    # _last_snapshot returns the one we just wrote; use the entry before that
    all_snapshots = _read_jsonl(SNAPSHOT_PATH)
    previous = all_snapshots[-2] if len(all_snapshots) >= 2 else None

    changes = detect_changes(snapshot, previous)

    # 3. Delegate to specialists + Hermes for material changes
    delegation_summary = {"handoffs": 0, "challenges": 0}
    for change in changes[:3]:  # delegate for top 3 changes
        if change.get("domain") != "system":
            try:
                from cio_delegation import run_delegation_cycle
                dsum = run_delegation_cycle(
                    domain=change.get("domain"),
                    change=change,
                    snapshot=snapshot,
                    max_handoffs=2,
                    max_challenges=1,
                )
                delegation_summary["handoffs"] += dsum.get("handoffs_enqueued", 0)
                delegation_summary["challenges"] += dsum.get("challenges_enqueued", 0)
            except Exception:
                pass  # delegation is non-fatal — heartbeat continues

    # 4. Create actions for material changes
    actions_created = 0
    for change in changes[:max_actions]:
        change_type = change.get("change_type", "UNKNOWN")
        domain = change.get("domain", "system")
        notif_priority = _compute_notification_priority(domain, change_type)

        if change_type == "FIRST_RUN":
            action = _create_action("system", change, "P1", notif_priority)
            _append_jsonl(ACTION_LEDGER_PATH, {
                "event_type": "CIO_ACTION_CREATED",
                "event_id": str(uuid.uuid4()),
                "timestamp": _now_iso(),
                "actor": "cio_heartbeat",
                "authority": "advisory",
                "payload": action,
            })
            actions_created += 1
            print(f"  [cio-hb] FIRST RUN [{notif_priority}] — baseline action {action['cio_action_id']}")
        elif change_type in ("DOMAIN_WENT_STALE", "DATA_CHANGED", "DOMAIN_AVAILABLE"):
            priority = "P1" if change_type == "DOMAIN_WENT_STALE" else "P2"
            action = _create_action(domain, change, priority, notif_priority)

            # Flash model context for Medium+ priority
            if notif_priority in ("Critical", "High", "Medium"):
                action = _add_flash_context(action, snapshot, change)

            _append_jsonl(ACTION_LEDGER_PATH, {
                "event_type": "CIO_ACTION_CREATED",
                "event_id": str(uuid.uuid4()),
                "timestamp": _now_iso(),
                "actor": "cio_heartbeat",
                "authority": "advisory",
                "payload": action,
            })
            actions_created += 1
            print(f"  [cio-hb] {change_type} [{notif_priority}]: {domain} → {action['cio_action_id']}")

    elapsed = time.time() - t0
    summary = {
        "heartbeat_id": snapshot.get("snapshot_id"),
        "collected_at": snapshot.get("collected_at"),
        "domains_collected": list(snapshot.get("domains", {}).keys()),
        "changes_detected": len(changes),
        "actions_created": actions_created,
        "delegation": delegation_summary,
        "elapsed_ms": int(elapsed * 1000),
        "mode": "shadow",
        "model_calls": 0,
        "cost_usd": 0.0,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CIO Heartbeat — autonomous action ledger manager (shadow-only)"
    )
    parser.add_argument(
        "--interval-minutes", type=int, default=30,
        help="expected interval between heartbeats (for staleness calc)"
    )
    parser.add_argument(
        "--max-actions", type=int, default=5,
        help="maximum actions to create per heartbeat"
    )
    parser.add_argument(
        "--once", action="store_true", default=True,
        help="run once and exit (default)"
    )
    args = parser.parse_args()

    print(f"CIO Heartbeat — {_now_iso()[:19]}")
    print(f"  mode=shadow  max_actions={args.max_actions}")

    summary = run_heartbeat(
        interval_minutes=args.interval_minutes,
        max_actions=args.max_actions,
    )

    print(f"  summary: {json.dumps(summary, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
