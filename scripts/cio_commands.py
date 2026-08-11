#!/usr/bin/env python3
"""cio_commands.py — Deterministic CIO query responder for Telegram /cio commands.

Reads canonical Data Broker projections and the CIO action ledger.
Zero model calls, zero provider cost. Safe for exec on every /cio request.

Usage:
  python3 scripts/cio_commands.py status          # Full CIO dashboard
  python3 scripts/cio_commands.py actions          # Open action items
  python3 scripts/cio_commands.py portfolio        # Portfolio snapshot
  python3 scripts/cio_commands.py watch            # Watch intelligence summary
  python3 scripts/cio_commands.py hermes           # Hermes research topics
  python3 scripts/cio_commands.py risk             # Risk overview
  python3 scripts/cio_commands.py action <id>      # Detail on one action
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()[:19]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _cio_snapshot() -> dict[str, Any]:
    """Get the CIO snapshot from the Data Broker."""
    try:
        from lib.data_broker.cio_portfolio import get_cio_snapshot
        return get_cio_snapshot(max_age_s=0)
    except Exception:
        return {"error": "Data Broker unavailable"}


def _cio_actions(limit: int = 10) -> list[dict[str, Any]]:
    """Get open CIO actions from the ledger."""
    ledger_path = PROJECT_ROOT / "data" / "cio" / "cio_action_ledger.jsonl"
    events = _read_jsonl(ledger_path)
    actions: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload", {})
        aid = payload.get("cio_action_id")
        if not aid:
            continue
        event_type = event.get("event_type", "")
        if event_type == "CIO_ACTION_CREATED":
            actions[aid] = payload
        elif event_type == "CIO_ACTION_UPDATED":
            if aid in actions:
                actions[aid].update(payload)
    # Return open actions, newest first
    open_actions = [
        a for a in actions.values()
        if a.get("status") in ("OPEN", "ACKNOWLEDGED")
    ]
    return sorted(
        open_actions,
        key=lambda a: a.get("created_at", ""),
        reverse=True,
    )[:limit]


def cmd_status() -> str:
    """Full CIO dashboard overview."""
    snap = _cio_snapshot()
    actions = _cio_actions(5)
    domains = snap.get("domains", {})
    health = snap.get("health", {})

    lines = [
        "🏦 CIO Dashboard",
        f"   As of: {_now_iso()}",
        "",
        "📊 Portfolio:",
    ]

    portfolio = domains.get("portfolio", {})
    if portfolio.get("state") == "AVAILABLE":
        lines.append(f"   Total: ${portfolio.get('total_value', 0):,.0f}" if portfolio.get("total_value") else "   Total: N/A")
        lines.append(f"   Day: {portfolio.get('day_change_pct', 0):+.1f}%" if portfolio.get('day_change_pct') else "")

    risk = domains.get("risk", {})
    if risk.get("state") == "AVAILABLE":
        lines.append(f"   Heat: {risk.get('portfolio_heat_pct', 0):.1f}%" if risk.get('portfolio_heat_pct') else "")

    lines.append("")
    lines.append("📋 Open Actions:")
    if actions:
        # Sort by notification_priority
        notif_sort = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
        sorted_actions = sorted(
            actions,
            key=lambda a: (notif_sort.get(a.get("notification_priority", ""), 4), a.get("created_at", "")),
        )
        for a in sorted_actions:
            notif = a.get("notification_priority", a.get("priority", "?"))
            emoji = {"Critical": "🚨", "High": "🔴", "Medium": "🟡", "Low": "⚪", "Info": "ℹ️"}.get(notif, "⚪")
            title = (a.get("title") or a.get("recommendation", ""))[:80]
            op_decision = a.get("operator_decision", "")
            bias = a.get("bias_flag", "")
            bias_tag = f" 🧠{bias.replace('_', ' ')}" if bias else ""
            decision_suffix = f" — {op_decision}" if op_decision and notif in ("Critical", "High") else ""
            lines.append(f"   {emoji} [{a.get('domain', '?')}{bias_tag}] {title}{decision_suffix}")
    else:
        lines.append("   No open actions")

    # Hermes research
    hermes = domains.get("hermes_research", {})
    if hermes.get("state") == "AVAILABLE" and hermes.get("latest_topics"):
        lines.append("")
        lines.append("🔬 Hermes Research:")
        for topic in hermes.get("latest_topics", [])[:5]:
            lines.append(f"   · {topic}")

    # Health
    lines.append("")
    available = health.get("domains_available", 0)
    total = health.get("domains_total", 0)
    status_icon = "✅" if health.get("ok") else "⚠️"
    lines.append(f"   {status_icon} {available}/{total} domains available")

    return "\n".join(lines)


def cmd_actions() -> str:
    """List open CIO action items."""
    actions = _cio_actions(20)
    if not actions:
        return "📋 No open CIO actions."

    lines = ["📋 CIO Action Ledger", f"   {len(actions)} open actions", ""]
    notif_sort = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
    emoji_map = {"Critical": "🚨", "High": "🔴", "Medium": "🟡", "Low": "⚪", "Info": "ℹ️"}
    for a in sorted(actions, key=lambda a: (notif_sort.get(a.get("notification_priority", ""), 4), a.get("created_at", ""))):
        aid = a.get("cio_action_id", "?")
        notif = a.get("notification_priority", a.get("priority", "?"))
        domain = a.get("domain", "?")
        title = (a.get("title") or "")[:70]
        op = a.get("operator_decision", "")
        lines.append(f"   {emoji_map.get(notif, '⚪')} [{notif}] {aid} — {domain}")
        lines.append(f"   {title}")
        if op:
            lines.append(f"   {op}")
        lines.append("")
    return "\n".join(lines)


def cmd_portfolio() -> str:
    """Portfolio snapshot."""
    snap = _cio_snapshot()
    domains = snap.get("domains", {})

    pf = domains.get("portfolio", {})
    risk = domains.get("risk", {})
    income = domains.get("income", {})

    lines = [
        "📊 CIO Portfolio Snapshot",
        f"   As of: {_now_iso()}",
        "",
    ]
    if pf.get("state") == "AVAILABLE":
        lines.append(f"   Total Value: ${pf.get('total_value', 0):,.0f}" if pf.get("total_value") else "   Total: N/A")
        lines.append(f"   Holdings: {pf.get('holdings_count', 0)}")
        lines.append(f"   Day Change: {pf.get('day_change_pct', 0):+.1f}%" if pf.get('day_change_pct') else "")
    if risk.get("state") == "AVAILABLE":
        lines.append(f"   Portfolio Heat: {risk.get('portfolio_heat_pct', 0):.1f}%" if risk.get('portfolio_heat_pct') else "")
        lines.append(f"   Stops Active: {risk.get('stops_active', 0)}")
    if income.get("state") == "AVAILABLE":
        lines.append(f"   Annual Dividend Est: ${income.get('annual_dividend_est', 0):,.0f}" if income.get('annual_dividend_est') else "")

    return "\n".join(lines)


def cmd_hermes() -> str:
    """Latest Hermes research topics."""
    snap = _cio_snapshot()
    hermes = snap.get("domains", {}).get("hermes_research", {})

    lines = [
        "🔬 Hermes Research Intelligence",
        f"   Promoted: {hermes.get('promoted_research_count', 0)}",
        f"   Staged: {hermes.get('staged_research_count', 0)}",
        f"   Model: {hermes.get('model_provider', 'deepseek-v4-flash')}",
        f"   Fallback: {hermes.get('fallback', 'free-oauth')}",
        f"   Autonomous: {'✅' if hermes.get('autonomous') else '❌'}",
        "",
        "   Latest Topics:",
    ]
    for topic in hermes.get("latest_topics", [])[:10]:
        lines.append(f"   · {topic}")

    if not hermes.get("latest_topics"):
        lines.append("   (no topics available)")

    return "\n".join(lines)


def cmd_risk() -> str:
    """Risk overview."""
    snap = _cio_snapshot()
    risk = snap.get("domains", {}).get("risk", {})

    lines = ["🛡️ CIO Risk Overview", ""]
    if risk.get("state") == "AVAILABLE":
        lines.append(f"   Portfolio Heat: {risk.get('portfolio_heat_pct', 0):.1f}%")
        lines.append(f"   Total Risk: ${risk.get('total_risk_dollars', 0):,.0f}")
        lines.append(f"   Stops Active: {risk.get('stops_active', 0)}")
    else:
        lines.append("   Risk data unavailable")

    return "\n".join(lines)


COMMANDS = {
    "status": cmd_status,
    "actions": cmd_actions,
    "portfolio": cmd_portfolio,
    "hermes": cmd_hermes,
    "risk": cmd_risk,
}

def cmd_ack() -> str:
    """Acknowledge a CIO action: /cio ack <action_id>"""
    if len(sys.argv) < 3:
        return "Usage: /cio ack <action_id>"
    action_id = sys.argv[2]
    try:
        from lib.cio_action_ledger import CIOActionLedger
        ledger = CIOActionLedger()
        result = ledger.transition_action(
            cio_action_id=action_id,
            new_event_type="CIO_ACTION_ACKNOWLEDGED",
            payload={"operator_decision": "Acknowledged by operator"},
            actor_id="operator",
            actor_type="operator",
            authority="operator",
        )
        return f"✅ Acknowledged: {action_id}\n   {json.dumps(result, default=str)}"
    except Exception as e:
        return f"❌ Failed to acknowledge {action_id}: {e}"


def cmd_rate() -> str:
    """Rate a CIO action's usefulness: /cio rate <action_id> <useful|notuseful>"""
    if len(sys.argv) < 4:
        return "Usage: /cio rate <action_id> <useful|notuseful>"
    action_id = sys.argv[2]
    rating = sys.argv[3].lower()
    if rating not in ("useful", "notuseful"):
        return f"Invalid rating: {rating}. Use 'useful' or 'notuseful'."
    try:
        from lib.cio_outcome_store import CIOOutcomeStore
        store = CIOOutcomeStore()
        disposition = "ACCEPTED" if rating == "useful" else "REJECTED"
        status = "POSITIVE" if rating == "useful" else "NEGATIVE"
        result = store.record_outcome(
            cio_action_id=action_id,
            operator_disposition=disposition,
            outcome_status=status,
            result_summary=f"Operator rated as {rating} via cio_commands",
            actor="operator",
        )
        return f"✅ Rated {action_id} as {rating}\n   {json.dumps(result, default=str)}"
    except Exception as e:
        return f"❌ Failed to rate {action_id}: {e}"


def cmd_defer() -> str:
    """Defer a CIO action: /cio defer <action_id> [YYYY-MM-DD|YYYY-MM-DDTHH:MM]"""
    if len(sys.argv) < 3:
        return "Usage: /cio defer <action_id> [date]"
    action_id = sys.argv[2]
    defer_until = sys.argv[3] if len(sys.argv) >= 4 else None
    try:
        from lib.cio_action_ledger import CIOActionLedger
        ledger = CIOActionLedger()
        payload: dict[str, Any] = {
            "operator_decision": "Deferred by operator",
            "operator_action": "defer",
        }
        if defer_until:
            payload["defer_until"] = defer_until
            payload["operator_decision"] += f" until {defer_until}"
        result = ledger.transition_action(
            cio_action_id=action_id,
            new_event_type="CIO_ACTION_DEFERRED",
            payload=payload,
            actor_id="operator",
            actor_type="operator",
            authority="operator",
        )
        return f"⏸️ Deferred: {action_id}" + (
            f" until {defer_until}" if defer_until else ""
        ) + f"\n   {json.dumps(result, default=str)}"
    except Exception as e:
        return f"❌ Failed to defer {action_id}: {e}"


def cmd_done() -> str:
    """Mark a CIO action as done: /cio done <action_id>"""
    if len(sys.argv) < 3:
        return "Usage: /cio done <action_id>"
    action_id = sys.argv[2]
    try:
        from lib.cio_action_ledger import CIOActionLedger
        ledger = CIOActionLedger()
        result = ledger.transition_action(
            cio_action_id=action_id,
            new_event_type="CIO_ACTION_DONE",
            payload={
                "operator_decision": "Marked done by operator",
                "operator_action": "done",
            },
            actor_id="operator",
            actor_type="operator",
            authority="operator",
        )
        return f"✅ Done: {action_id}\n   {json.dumps(result, default=str)}"
    except Exception as e:
        return f"❌ Failed to mark {action_id} done: {e}"


def cmd_reject() -> str:
    """Reject a CIO action: /cio reject <action_id>

    The CIO Action Ledger has no dedicated REJECTED status.  Operator rejection
    is mapped to CIO_ACTION_CANCELLED (a terminal status) with an operator
    rejection payload.  If semantically a distinct REJECTED status is needed,
    it should be added to the ledger schema as a first-class terminal status.
    """
    if len(sys.argv) < 3:
        return "Usage: /cio reject <action_id>"
    action_id = sys.argv[2]
    try:
        from lib.cio_action_ledger import CIOActionLedger
        ledger = CIOActionLedger()
        result = ledger.transition_action(
            cio_action_id=action_id,
            new_event_type="CIO_ACTION_CANCELLED",
            payload={
                "operator_decision": "Rejected by operator (mapped to CANCELLED)",
                "operator_action": "reject",
                "cancel_reason": "operator_rejection",
            },
            actor_id="operator",
            actor_type="operator",
            authority="operator",
        )
        schema_gap = (
            "Note: CIO Action Ledger has no dedicated REJECTED terminal status. "
            "Rejection is stored as CANCELLED with cancel_reason=operator_rejection. "
            "Consider adding CIO_ACTION_REJECTED and REJECTED status to "
            "VALID_EVENT_TYPES/TERMINAL_STATUSES for semantic clarity."
        )
        return (
            f"🚫 Rejected (cancelled): {action_id}\n"
            f"   {schema_gap}\n"
            f"   {json.dumps(result, default=str)}"
        )
    except Exception as e:
        return f"❌ Failed to reject {action_id}: {e}"


def cmd_plans() -> str:
    """List open advisory plans (deterministic)."""
    try:
        from lib.cio_plans import CIOPlanStore
        rows = CIOPlanStore().list_open_plans(limit=20)
    except Exception as e:
        return f"❌ plans unavailable: {e}"
    if not rows:
        return "No open plans."
    lines = ["📋 Open plans (READ_ONLY):"]
    for p in rows:
        syms = ",".join(p.get("symbols") or []) or "—"
        lines.append(
            f"• {p.get('plan_id')}  {p.get('situation_type')}  "
            f"[{syms}]  {p.get('status')}"
        )
    return "\n".join(lines)


def cmd_plan() -> str:
    """Show one plan: /cio plan <plan_id>"""
    if len(sys.argv) < 3:
        return "Usage: /cio plan <plan_id>"
    plan_id = sys.argv[2]
    try:
        from lib.cio_plans import CIOPlanStore
        p = CIOPlanStore().get_plan(plan_id)
    except Exception as e:
        return f"❌ plan lookup failed: {e}"
    if not p:
        return f"Plan not found: {plan_id}"
    opts = p.get("options") or []
    opt_s = "\n".join(f"  - {o.get('label') or o.get('id')}" for o in opts[:6])
    refs = p.get("evidence_refs") or []
    ref_s = "\n".join(
        f"  - {r.get('domain')} as_of={r.get('as_of')}" for r in refs[:8]
    )
    return (
        f"📌 {p.get('plan_id')} · {p.get('situation_type')} · {p.get('status')}\n"
        f"Symbols: {', '.join(p.get('symbols') or []) or '—'}\n"
        f"Owner: {p.get('owner_agent')}\n"
        f"Summary: {p.get('summary') or p.get('title')}\n"
        f"Recommendation: {p.get('recommendation')}\n"
        f"Options:\n{opt_s or '  (none)'}\n"
        f"Evidence:\n{ref_s or '  (none)'}\n"
        f"revisit_at: {p.get('revisit_at')}\n"
        f"authority: READ_ONLY_ADVISORY"
    )


HELP = """🤖 CIO Commands:
  /cio                 — Full CIO dashboard
  /cio actions         — Open action items
  /cio portfolio       — Portfolio snapshot
  /cio hermes          — Hermes research topics
  /cio risk            — Risk overview
  /cio plans           — Open advisory plans
  /cio plan <id>       — Show one plan
  /cio action <id>     — Detail on one action (coming soon)
  /cio ack <id>        — Acknowledge an action
  /cio defer <id> [date] — Defer an action (optionally until date)
  /cio reject <id>     — Reject/cancel an action
  /cio done <id>       — Mark an action as done
  /cio rate <id> <useful|notuseful> — Rate action usefulness

Data source: CIO Data Broker (13 domains). Zero model calls for status.
Free-text converse uses dedicated CIO bot (READ_ONLY_ADVISORY)."""


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        print(HELP)
        return 0

    subcommand = sys.argv[1]
    if subcommand in COMMANDS:
        print(COMMANDS[subcommand]())
    elif subcommand == "ack":
        print(cmd_ack())
    elif subcommand == "rate":
        print(cmd_rate())
    elif subcommand == "defer":
        print(cmd_defer())
    elif subcommand == "reject":
        print(cmd_reject())
    elif subcommand == "done":
        print(cmd_done())
    elif subcommand == "plans":
        print(cmd_plans())
    elif subcommand == "plan":
        print(cmd_plan())
    elif subcommand == "action" and len(sys.argv) > 2:
        print(f"📋 Action detail for {sys.argv[2]} — coming soon")
    else:
        print(f"Unknown CIO command: {subcommand}")
        print(HELP)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
