"""CIO conflict memory and shared prompt/brief/Ask/conviction inputs."""
from __future__ import annotations

from .ledger import ACTIVE, list_records


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


def context_for(root, security_guid):
    records = list_records(root, subject_kind="security", subject_id=security_guid, limit=200)["records"]
    opened = [r for r in records if r["state"] in ACTIVE]
    return {"open_conflicts": opened,
            "blocks_promotion": any(r.get("rule") == "U7" and not r.get("decision") for r in opened),
            "owner": "the CIO", "instruction": "Cite both sources, explain the CIO position and what clears each conflict."}


def digest(root):
    records = list_records(root, limit=200)["records"]
    return {"waiting_on_operator": [r for r in records if r.get("kind") == "NEEDS_OPERATOR" and r["state"] in ACTIVE],
            "decided": [r for r in records if r.get("decision")],
            "groups": _groups([r for r in records if r["state"] in ACTIVE])}


def _groups(records):
    groups = {}
    for row in records:
        groups.setdefault((row.get("kind"), row.get("rule")), []).append(row)
    return [{"kind": k[0], "rule": k[1], "count": len(rows), "keys": [r["key"] for r in rows]}
            for k, rows in sorted(groups.items())]
