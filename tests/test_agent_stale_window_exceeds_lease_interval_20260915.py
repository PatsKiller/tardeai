"""An agent's staleness window must exceed how often it leases — 2026-09-15.

stale_input_seconds asks "has this job rotted in the queue". If a runner leases less often than
that window, it refuses every row it is ever given — by construction, not by meaning — and each
refusal permanently consumes the row's UNIQUE (agent_id, trigger_kind, dedup_key) slot, so that
candidate can never be enqueued again.

Measured on 2026-09-15, the first time anything ever leased this queue: a single uniform
stale_input_seconds = 900 was applied to agents whose lease intervals ranged from 5 minutes to
24 hours. Six (atlas, argus, risk_agent, darwin, reflection, tax_agent) leased more slowly than
the window. Sentinel's first real lease refused 8 of 8 rows, which had waited 997s against the
900s window — 97 seconds over — and 221 of 288 queued rows were already past it.

The shipped timer template is included deliberately: it is what an agent gets with no host
drop-in, and at OnCalendar=*:0/15 it was itself broken against the 900s default.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.agents.base import ShadowAgentSpec  # noqa: E402
from agent_runtime.agents.definitions import (  # noqa: E402
    FLEET,
    LEASE_CADENCE_SECONDS,
    LEASE_JITTER_SECONDS,
    LEASE_WINDOW_TICK_MARGIN,
)

TEMPLATE = ROOT / "config" / "systemd" / "agent_runtime" / "tradeai-agent-runtime@.timer"


def _template_cadence_seconds() -> int:
    text = TEMPLATE.read_text()
    m = re.search(r"OnCalendar=\*:0/(\d+)", text)
    if m:
        return int(m.group(1)) * 60
    if re.search(r"OnCalendar=hourly", text):
        return 3600
    raise AssertionError(f"could not parse OnCalendar from {TEMPLATE}")


def _template_jitter_seconds() -> int:
    m = re.search(r"RandomizedDelaySec=(\d+)", TEMPLATE.read_text())
    return int(m.group(1)) if m else 0


@pytest.mark.parametrize("agent_id", sorted(LEASE_CADENCE_SECONDS))
def test_window_survives_missed_ticks(agent_id: str):
    spec: ShadowAgentSpec = FLEET[agent_id]
    worst = LEASE_CADENCE_SECONDS[agent_id] + LEASE_JITTER_SECONDS
    required = LEASE_WINDOW_TICK_MARGIN * worst
    assert spec.stale_input_seconds >= required, (
        f"{agent_id} leases every {worst}s worst-case but its staleness window is "
        f"{spec.stale_input_seconds}s — it would refuse rows it had no chance to lease in time"
    )


def test_every_declared_cadence_names_a_real_fleet_agent():
    unknown = sorted(set(LEASE_CADENCE_SECONDS) - set(FLEET))
    assert unknown == [], f"cadence declared for agents not in the fleet: {unknown}"


def test_the_shipped_timer_template_is_not_broken_on_arrival():
    """An agent installed with no host drop-in gets this schedule; the default window must cover it."""
    worst = _template_cadence_seconds() + _template_jitter_seconds()
    default = ShadowAgentSpec.__dataclass_fields__["stale_input_seconds"].default
    assert default >= LEASE_WINDOW_TICK_MARGIN * worst, (
        f"the shipped template leases every {worst}s worst-case but the default window is "
        f"{default}s — any agent without a host drop-in refuses everything it is given"
    )


def test_no_fleet_agent_keeps_a_window_shorter_than_the_template_it_ships_with():
    worst = _template_cadence_seconds() + _template_jitter_seconds()
    offenders = {
        a: s.stale_input_seconds
        for a, s in FLEET.items()
        if a not in LEASE_CADENCE_SECONDS and s.stale_input_seconds < LEASE_WINDOW_TICK_MARGIN * worst
    }
    assert offenders == {}, (
        "agents with no declared cadence fall back to the shipped template schedule, "
        f"and these windows are too short for it: {offenders}"
    )
