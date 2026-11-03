"""CIO conflict memory and shared prompt/brief/Ask/conviction inputs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from .adapters import timestamp
from .ledger import ACTIVE, ConflictLedger, list_records


def memory_writer(root):
    """CIO spine outbox sink, idempotent by immutable conflict event ID."""
    def write(event):
        from scripts.lib.cross_asset.security_research_spine import load_latest, upsert_research_memory
        subject = event["subject"]
        prior = load_latest(subject["label"], root=root) or {}
        if any(c.get("artifact_id") == event["event_id"] for c in prior.get("contributions", [])):
            return True
        decision = event.get("decision") or {}
        finding = event.get("finding") or {}
        summary = {"event": event["event"], "key": event["key"], "sides": finding.get("sides"),
                   "chosen_side": decision.get("chosen_side"), "reason": decision.get("reason"),
                   "evidence": event.get("evidence")}
        import json
        result = upsert_research_memory(subject["label"], silo="cio", kind="conflict",
            summary=json.dumps(summary, ensure_ascii=False), artifact_id=event["event_id"],
            refs=[event["key"], *(decision.get("evidence_refs") or [])], tags=["conflict", event["event"]],
            thesis_patch=None, subject_guid=subject["id"], root=root)
        return result.get("ok") is True
    return write


def context_for(root, security_guid, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not (Path(root) / "data/conflicts/conflict_events.jsonl").exists():
        return {"open_conflicts": [], "blocks_promotion": True,
                "gap": {"reason": "conflict evaluation not yet produced"}, "owner": "the CIO"}
    try:
        records = list_records(root, subject_kind="security", subject_id=security_guid, limit=200, active_only=True)["records"]
    except (OSError, ValueError):
        return {"open_conflicts": [], "blocks_promotion": True,
                "gap": {"reason": "conflict evaluation unavailable or invalid"}, "owner": "the CIO"}
    opened = [r for r in records if r["state"] in ACTIVE]
    def decided(record):
        decision = record.get("decision") or {}
        expiry = timestamp(decision.get("expires_at"))
        return bool(expiry and expiry > now)
    return {"open_conflicts": opened,
            "blocks_promotion": any(r.get("kind") in {"GATE", "NEEDS_OPERATOR", "DATA_ERROR"} or
                                    r.get("rule") in {"U7", "R11"} and not decided(r) for r in opened),
            "gap": None,
            "owner": "the CIO", "instruction": "Cite both sources, explain the CIO position and what clears each conflict."}


def digest(root, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not (Path(root) / "data/conflicts/conflict_events.jsonl").exists():
        return {"waiting_on_operator": [], "decided": [], "groups": [],
                "gap": {"reason": "conflict ledger not yet produced"}}
    try:
        records = list(ConflictLedger(root).records().values())
    except (OSError, ValueError):
        return {"waiting_on_operator": [], "decided": [], "groups": [],
                "gap": {"reason": "conflict ledger unavailable or invalid"}}
    return {"waiting_on_operator": _waiting_with_age(records, now),
            "decided": [r for r in records if r.get("decision") and timestamp(r["decision"].get("at")) and
                        timedelta(0) <= now - timestamp(r["decision"]["at"]) <= timedelta(days=1)],
            "groups": _groups([r for r in records if r["state"] in ACTIVE]), "gap": None}


def _waiting_with_age(records, now) -> list[dict]:
    """The items waiting on the CIO, each carrying how long it has been waiting.

    The brief used to print "N waiting on you" with no clock, so an item opened nine days ago and one opened nine
    minutes ago read the same. Age comes from the record's own ``opened_at`` (the ledger keeps the first open time
    across re-reconciles), never from the read time. A record with no readable open time gets ``None`` — the brief
    says "age unknown" rather than inventing zero.
    """
    out = []
    for record in records:
        if record.get("kind") != "NEEDS_OPERATOR" or record["state"] not in ACTIVE:
            continue
        opened = timestamp(record.get("opened_at"))
        seconds = (now - opened).total_seconds() if opened else None
        age = round(seconds / 3600, 1) if seconds is not None and seconds >= 0 else None
        out.append({**record, "age_hours": age})
    return out


def waiting_with_age(root, *, now=None) -> list[dict]:
    """Same list the brief renders, for any other surface that needs the clock."""
    return digest(root, now=now)["waiting_on_operator"]


def age_text(hours) -> str:
    """How long, in words short enough for a Telegram line. Never a fabricated zero."""
    if hours is None:
        return "age unknown"
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 48:
        return f"{round(hours)}h"
    return f"{round(hours / 24)}d"



def _groups(records):
    groups = {}
    for row in records:
        groups.setdefault((row.get("kind"), row.get("rule")), []).append(row)
    return [{"kind": k[0], "rule": k[1], "count": len(rows), "keys": [r["key"] for r in rows]}
            for k, rows in sorted(groups.items())]
