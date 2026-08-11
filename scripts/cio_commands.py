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

def _plan_disposition(plan_id: str, status: str, *, note: str = "") -> str:
    """Disposition for converse plans (plan_*). READ_ONLY_ADVISORY."""
    try:
        try:
            from lib.cio_plans import CIOPlanStore
        except Exception:
            from scripts.lib.cio_plans import CIOPlanStore
        store = CIOPlanStore()
        p = store.get_plan(plan_id)
        if not p:
            return f"❌ Plan not found: {plan_id}"
        store.update_plan(plan_id, status=status, actor_id="operator")
        # Learning loop: surface disposition into desk thesis learning_log
        try:
            try:
                from lib.cio_theses import record_plan_disposition_learning
            except Exception:
                from scripts.lib.cio_theses import record_plan_disposition_learning
            record_plan_disposition_learning(
                p, status, note=note, actor_id="operator",
            )
        except Exception:
            pass
        return (
            f"✅ Plan {plan_id} → {status}"
            + (f"\n   {note}" if note else "")
            + f"\n   situation={p.get('situation_type')} symbols={','.join(p.get('symbols') or [])}"
            + f"\n   thesis={p.get('thesis_version') or '—'}"
            + "\n   authority: READ_ONLY_ADVISORY"
        )
    except Exception as e:
        return f"❌ Failed plan disposition {plan_id}: {e}"


def cmd_ack() -> str:
    """Acknowledge a CIO action or plan: /cio ack <action_id|plan_id>"""
    if len(sys.argv) < 3:
        return "Usage: /cio ack <action_id|plan_id>"
    action_id = sys.argv[2]
    if str(action_id).startswith("plan_"):
        return _plan_disposition(action_id, "accepted", note="Acknowledged by operator")
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
    """Defer a CIO action or plan: /cio defer <action_id|plan_id> [date]"""
    if len(sys.argv) < 3:
        return "Usage: /cio defer <action_id|plan_id> [date]"
    action_id = sys.argv[2]
    defer_until = sys.argv[3] if len(sys.argv) >= 4 else None
    if str(action_id).startswith("plan_"):
        note = f"Deferred by operator" + (f" until {defer_until}" if defer_until else "")
        # keep plan open-ish but mark proposed → accepted later; use proposed with note via status draft
        return _plan_disposition(action_id, "proposed", note=note + " (plan stays open)")
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
    """Mark a CIO action or plan done: /cio done <action_id|plan_id>"""
    if len(sys.argv) < 3:
        return "Usage: /cio done <action_id|plan_id>"
    action_id = sys.argv[2]
    if str(action_id).startswith("plan_"):
        return _plan_disposition(action_id, "accepted", note="Marked done by operator")
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
    """Reject a CIO action or plan: /cio reject <action_id|plan_id>

    The CIO Action Ledger has no dedicated REJECTED status.  Operator rejection
    is mapped to CIO_ACTION_CANCELLED (a terminal status) with an operator
    rejection payload.  Plans map to status cancelled.
    """
    if len(sys.argv) < 3:
        return "Usage: /cio reject <action_id|plan_id>"
    action_id = sys.argv[2]
    if str(action_id).startswith("plan_"):
        return _plan_disposition(action_id, "cancelled", note="Rejected by operator")
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


def cmd_traces(n: int = 10, llm: str | None = None, plan_id: str | None = None) -> str:
    """List recent wake traces — deterministic, zero LLM (P5)."""
    try:
        from lib.cio_wake_traces import cmd_traces_text
        return cmd_traces_text(n, plan_id=plan_id, llm=llm)
    except Exception:
        try:
            from scripts.lib.cio_wake_traces import cmd_traces_text
            return cmd_traces_text(n, plan_id=plan_id, llm=llm)
        except Exception as e:
            return f"❌ traces unavailable: {e}"


def cmd_thesis() -> str:
    """Show current desk thesis (P3). Zero LLM."""
    try:
        from lib.cio_theses import CIOThesisStore
    except Exception:
        from scripts.lib.cio_theses import CIOThesisStore
    try:
        store = CIOThesisStore()
        # optional: /cio thesis <id>
        tid = "desk"
        if len(sys.argv) >= 3 and not sys.argv[2].startswith("@"):
            # "thesis history" handled elsewhere; bare id
            if sys.argv[2].lower() not in ("history", "list", "versions"):
                tid = sys.argv[2].strip().lower()
        cur = store.get_current(tid)
        if not cur:
            return (
                f"No thesis published for `{tid}`.\n"
                "Publish: `.venv/bin/python -c \"from scripts.lib.cio_theses import CIOThesisStore; "
                "print(CIOThesisStore().publish('...', owner_agent='alex'))\"`"
            )
        bullets = cur.get("bullets") or []
        b_s = "\n".join(f"  • {b}" for b in bullets[:8]) or "  (none)"
        return (
            f"📌 Desk thesis `{cur.get('thesis_version')}` · {cur.get('status')}\n"
            f"owner={cur.get('owner_agent')} published={str(cur.get('published_ts') or '')[:19]}\n"
            f"stance: {cur.get('stance') or '—'}\n"
            f"summary: {cur.get('summary') or ''}\n"
            f"bullets:\n{b_s}\n"
            f"symbols: {', '.join(cur.get('linked_symbols') or []) or '—'}\n"
            f"authority: READ_ONLY_ADVISORY"
        )
    except Exception as e:
        return f"❌ thesis unavailable: {e}"


def cmd_thesis_history() -> str:
    """List recent versions of a thesis. Zero LLM."""
    try:
        from lib.cio_theses import CIOThesisStore
    except Exception:
        from scripts.lib.cio_theses import CIOThesisStore
    tid = "desk"
    limit = 10
    args = sys.argv[2:]
    for a in args:
        if a.isdigit():
            limit = max(1, min(int(a), 50))
        elif a.lower() not in ("history", "list", "versions"):
            tid = a.strip().lower()
    try:
        rows = CIOThesisStore().list_versions(tid, limit=limit)
        if not rows:
            return f"No versions for `{tid}`."
        lines = [f"📚 Thesis versions `{tid}` (newest first):"]
        for r in rows:
            lines.append(
                f"• `{r.get('thesis_version')}` {str(r.get('published_ts') or '')[:19]} "
                f"{r.get('status')} — {(r.get('summary') or '')[:80]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ thesis history unavailable: {e}"


HELP = """🤖 CIO Commands:
  /cio                 — Full CIO dashboard
  /cio actions         — Open action items
  /cio portfolio       — Portfolio snapshot
  /cio hermes          — Hermes research topics
  /cio risk            — Risk overview
  /cio plans           — Open advisory plans
  /cio plan <id>       — Show one plan
  /cio thesis          — Current desk thesis (versioned, P3)
  /cio thesis history  — Thesis version list
  /cio traces [n]      — Recent wake traces (why wake / llm path)
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
    elif subcommand == "traces":
        n = 10
        llm_f = None
        plan_f = None
        for tok in sys.argv[2:]:
            if tok.isdigit():
                n = max(1, min(int(tok), 50))
            elif tok.startswith("llm="):
                llm_f = tok.split("=", 1)[1]
            elif tok.startswith("plan="):
                plan_f = tok.split("=", 1)[1]
        print(cmd_traces(n=n, llm=llm_f, plan_id=plan_f))
    elif subcommand == "thesis":
        rest = [a.lower() for a in sys.argv[2:]]
        if rest and rest[0] in ("history", "list", "versions"):
            print(cmd_thesis_history())
        else:
            print(cmd_thesis())
    elif subcommand == "action" and len(sys.argv) > 2:
        print(f"📋 Action detail for {sys.argv[2]} — coming soon")
    else:
        print(f"Unknown CIO command: {subcommand}")
        print(HELP)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
