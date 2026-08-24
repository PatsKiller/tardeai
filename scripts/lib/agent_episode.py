"""AgentEpisode@v1 — durable GUID-referenced office events.

READ_ONLY_ADVISORY. Episodes are not investment policy.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "AgentEpisode@v1"
PATH = "data/cio/agent_episodes.jsonl"
KINDS = (
    "operator_question",
    "cio_recommendation",
    "research_request",
    "research_completion",
    "curation_change",
    "thesis_change",
    "feedback",
    "NEED_DATA",
    "notification",
    "suppression",
    "portfolio_reassessment",
    "outcome_maturation",
    "weekly_learning_review",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_episode(
    *,
    kind: str,
    subject_guid: str | None = None,
    symbol: str | None = None,
    refs: dict[str, Any] | None = None,
    summary: str = "",
    run_id: str | None = None,
    agent: str = "alex",
) -> dict[str, Any]:
    if kind not in KINDS:
        raise RuntimeError("UNKNOWN_EPISODE_KIND")
    return {
        "schema": SCHEMA,
        "episode_id": str(uuid.uuid4()),
        "kind": kind,
        "subject_guid": subject_guid,
        "symbol": symbol,
        "refs": dict(refs or {}),
        "summary": summary[:500],
        "run_id": run_id,
        "agent": agent,
        "created_at": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
        "policy_effect": False,
    }


def append_episode(root: Path | str, episode: dict[str, Any]) -> dict[str, Any]:
    path = Path(root) / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(episode, default=str) + "\n")
    return {"wrote": True, "episode_id": episode["episode_id"], "path": str(path)}
