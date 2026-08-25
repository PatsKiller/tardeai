"""One autonomous advisory cycle: truth → situation → CIO → notify → memory.

READ_ONLY_ADVISORY. No broker/order/stop/risk/2FA mutation.
The second cycle must start from persisted prior cognition, not raw history.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.agent_episode import append_episode, build_episode
from scripts.lib.cio_advisory_message import assert_not_json_dump, render_advisory_message
from scripts.lib.cio_advisory_synthesis import synthesize
from scripts.lib.cio_situation_state import NOTIFY, SUPPRESS, detect_office_situations

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "OfficeCycleResult@v1"
PRIOR_PATH = "data/cio/cio_situation_states.jsonl"
MEMORY_BEHAVIOR_INFLUENCE = 0


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_prior_states(root: Path) -> dict[str, Any]:
    path = Path(root) / PRIOR_PATH
    if not path.is_file():
        return {}
    latest: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("record_type") == "OFFICE_CYCLE":
            latest = row
    return latest


def persist_cycle(root: Path, result: dict[str, Any]) -> None:
    path = Path(root) / PRIOR_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "record_type": "OFFICE_CYCLE",
        "recorded_at": _now(),
        "scan": {
            "classes": result.get("classes"),
            "notification_decision": result.get("notification_decision"),
            "situations": result.get("situations"),
        },
        "prior_used": result.get("prior_used"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def _semantic_dedupe(scan: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    prior_fps = {
        str((s or {}).get("fingerprint"))
        for s in ((prior.get("scan") or {}).get("situations") or [])
        if isinstance(s, dict)
    }
    notify = []
    suppressed_extra = []
    for row in scan.get("notify") or []:
        if row.get("fingerprint") in prior_fps:
            updated = dict(row)
            updated["notification_eligibility"] = SUPPRESS
            updated["suppression_reason"] = "SEMANTIC_DEDUPE"
            suppressed_extra.append(updated)
        else:
            notify.append(row)
    scan = dict(scan)
    scan["notify"] = notify
    scan["suppress"] = list(scan.get("suppress") or []) + suppressed_extra
    if not notify and scan.get("defer"):
        scan["notification_decision"] = "DEFER"
    elif not notify:
        scan["notification_decision"] = SUPPRESS
        scan["llm_required"] = False
    else:
        scan["notification_decision"] = NOTIFY
    return scan


def run_office_cycle(
    office: dict[str, Any],
    *,
    root: Path | str,
    envelope: dict[str, Any] | None = None,
    persisted_summary: str | None = None,
    generate=None,
    persist: bool = True,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    prior = load_prior_states(root_path)
    office = dict(office)
    if prior and not office.get("prior_situations"):
        office["prior_situations"] = {
            "cash": None,
            "market_regime": None,
            "seasonality": None,
            "prior_cycle": (prior.get("scan") or {}).get("classes"),
        }
        for sit in (prior.get("scan") or {}).get("situations") or []:
            if sit.get("situation_class") == "MARKET_REGIME_CHANGE":
                office["prior_situations"]["market_regime"] = (sit.get("new_state") or {}).get("regime")
    scan = detect_office_situations(office, evaluated_at=evaluated_at)
    scan = _semantic_dedupe(scan, prior)
    primary = (scan.get("notify") or scan.get("defer") or scan.get("situations") or [{}])[0]
    synthesis = synthesize(
        scan,
        envelope=envelope,
        persisted_summary=persisted_summary,
        generate=generate,
    )
    message = render_advisory_message(primary, synthesis_text=synthesis.get("text") or None)
    assert_not_json_dump(message)
    episode = None
    if persist:
        kind = "notification" if scan.get("notification_decision") == NOTIFY else "suppression"
        episode = build_episode(
            kind=kind,
            subject_guid=str((primary.get("affected_guids") or ["office:primary"])[0]),
            summary=(primary.get("what_changed") or scan.get("notification_decision") or "")[:500],
            refs={
                "situation_id": primary.get("situation_id"),
                "decision": scan.get("notification_decision"),
            },
        )
        append_episode(root_path, episode)
    result = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
        "financial_action": False,
        "executable_order": None,
        "broker_mutation": False,
        "situations": scan.get("situations"),
        "classes": scan.get("classes"),
        "notification_decision": scan.get("notification_decision"),
        "primary_situation": primary,
        "message": message,
        "synthesis": synthesis,
        "episode": episode,
        "llm_calls": (synthesis.get("model") or {}).get("llm_calls") or 0,
        "prior_used": bool(prior),
        "reconstructed_from_raw_history": not bool(prior),
        "same_brain_envelope": bool(envelope),
    }
    if persist:
        persist_cycle(root_path, result)
    return result
