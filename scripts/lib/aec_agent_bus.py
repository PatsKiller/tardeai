"""aec_agent_bus.py — shared Command Center bus for parallel AEC agents.

Operator license 2026-09-19: parallel CIO / Advisor / Narrator agents may exist,
but they MUST share one bus. Three hermetic copies of Trade AI is the filing-
cabinet defect at agent scale.

AUTHORITY: READ_ONLY_ADVISORY — no broker, no behavior fields.
MBI_BEHAVIOR=0: bus payloads may carry cognition/advisory fields only.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "AecAgentBusEvent@v1"
AGENT_IDS = ("cio_agent", "advisor_agent", "narrator_agent")


@dataclass(frozen=True)
class BusEvent:
    schema: str
    as_of: str
    agent_id: str
    topic: str
    subject_key: str | None
    workflow_id: str | None
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    # Cognition / advisory only — never size, order, stop, weight.
    authority: str = "READ_ONLY_ADVISORY"

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bus_path(root: Path | None = None) -> Path:
    env = os.environ.get("TRADEAI_AEC_BUS")
    if env:
        return Path(env)
    persistent = Path.home() / "trade-ai-releases/persistent-state/data/cio/aec_agent_bus.jsonl"
    if persistent.parent.is_dir():
        return persistent
    base = root or Path.cwd()
    return base / "data" / "cio" / "aec_agent_bus.jsonl"


def publish(
    *,
    agent_id: str,
    topic: str,
    summary: str,
    subject_key: str | None = None,
    workflow_id: str | None = None,
    payload: dict[str, Any] | None = None,
    path: Path | None = None,
    dry_run: bool = False,
) -> BusEvent:
    if agent_id not in AGENT_IDS:
        raise ValueError(f"unknown agent_id={agent_id!r}; expected one of {AGENT_IDS}")
    # Refuse behavior-shaped keys in payload (belt + BehaviorWriteRefused elsewhere).
    forbidden = {
        "recommended_delta_usd", "size_usd", "shares", "qty", "order", "stop",
        "limit", "target_weight_pct", "trade", "execution",
    }
    body = dict(payload or {})
    bad = forbidden.intersection(body)
    if bad:
        raise ValueError(f"MBI_BEHAVIOR=0: refused behavior fields on bus: {sorted(bad)}")
    ev = BusEvent(
        schema=SCHEMA,
        as_of=_utc_now(),
        agent_id=agent_id,
        topic=topic,
        subject_key=subject_key,
        workflow_id=workflow_id,
        summary=summary,
        payload=body,
    )
    if dry_run:
        return ev
    p = path or bus_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(ev.to_json() + "\n")
    return ev


def read_recent(path: Path | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    p = path or bus_path()
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def topics_for(agent_id: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Events other agents published that this agent should see."""
    return [r for r in rows if r.get("agent_id") != agent_id]
