"""WS7-09 (incident SPCX 2026-10-14): health-agent auto-remediation never runs a broker-class script.

On 2026-10-14 the remediation_map ran ``unified_stop_supervisor.py --apply`` 101 times, outside its
cron line's flock and market-day gate, including after the Schwab pause. Broker-class scripts belong
to their governed schedule only; a stale/log finding may alert, never act at a broker.
"""

from __future__ import annotations

import json
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / "config" / "health_agent_policy.json"

# Scripts that can place, replace or cancel broker orders (directly or through a pilot).
BROKER_CLASS = (
    "unified_stop_supervisor",
    "schwab_stop_batch_request",
    "schwab_oco_bracket",
    "synthetic_stop_monitor",
    "schwab_broker_trade_monitor",
    "protective_stop_pilot",
    "options_order_pilot",
    "broker_entry_pilot",
    "snaptrade_trade",
    "tastytrade_adapter",
)


def _commands(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _commands(value)
    elif isinstance(node, list):
        for value in node:
            yield from _commands(value)
    elif isinstance(node, str):
        yield node


def test_remediation_map_has_no_broker_class_script():
    policy = json.loads(POLICY.read_text())
    rmap = policy.get("remediation_map") or {}
    hits = {k: v for k, v in rmap.items() if any(b in v for b in BROKER_CLASS)}
    assert not hits, f"broker-class script in health-agent remediation_map: {hits}"


def test_no_broker_class_script_anywhere_in_policy_actions():
    policy = json.loads(POLICY.read_text())
    hits = [c for c in _commands(policy) if "--apply" in c and any(b in c for b in BROKER_CLASS)]
    assert not hits, f"broker-class --apply command in health-agent policy: {hits}"
