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
        for a in actions:
            priority = a.get("priority", "?")
            emoji = {"P1": "🔴", "P2": "🟡", "P3": "⚪"}.get(priority, "⚪")
            title = (a.get("title") or a.get("recommendation", ""))[:80]
            lines.append(f"   {emoji} [{a.get('domain', '?')}] {title}")
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
    for a in actions:
        aid = a.get("cio_action_id", "?")
        priority = a.get("priority", "?")
        domain = a.get("domain", "?")
        title = (a.get("title") or "")[:70]
        lines.append(f"   [{priority}] {aid} — {domain}")
        lines.append(f"   {title}")
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

HELP = """🤖 CIO Commands:
  /cio              — Full CIO dashboard
  /cio actions      — Open action items
  /cio portfolio    — Portfolio snapshot
  /cio hermes       — Hermes research topics
  /cio risk         — Risk overview
  /cio action <id>  — Detail on one action (coming soon)

Data source: CIO Data Broker (7 domains). Zero model calls."""


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        print(HELP)
        return 0

    subcommand = sys.argv[1]
    if subcommand in COMMANDS:
        print(COMMANDS[subcommand]())
    elif subcommand == "action" and len(sys.argv) > 2:
        print(f"📋 Action detail for {sys.argv[2]} — coming soon")
    else:
        print(f"Unknown CIO command: {subcommand}")
        print(HELP)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
