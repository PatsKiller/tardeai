#!/usr/bin/env python3
"""Read-only census for research-due-diligence-v1 packets.

Consumes one or more existing JSON artifacts and reports Proposal, Defense,
Sector, Industry and Watch diligence states. It never refreshes evidence,
rebuilds packets, calls models, writes databases, changes schedules or invokes
external actions.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

CONTRACT = "research-due-diligence-census-v1"
PACKET_CONTRACT = "research-due-diligence-v1"
DOMAINS = ("PROPOSAL", "DEFENSE", "SECTOR", "INDUSTRY", "WATCH")


def _walk(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        if value.get("contract") == PACKET_CONTRACT and str(value.get("domain") or "").upper() in DOMAINS:
            yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def census(documents: Iterable[Any]) -> dict:
    packets: list[dict] = []
    for document in documents:
        packets.extend(_walk(document))

    by_domain: dict[str, Counter] = defaultdict(Counter)
    subjects: dict[str, list[dict]] = defaultdict(list)
    for packet in packets:
        domain = str(packet.get("domain") or "UNKNOWN").upper()
        state = str(packet.get("state") or "MISSING").upper()
        by_domain[domain][state] += 1
        subjects[domain].append({
            "subject": packet.get("subject"),
            "state": state,
            "release_allowed": packet.get("release_allowed") is True,
            "evidence_hash": packet.get("evidence_hash"),
            "missing_evidence": packet.get("missing_evidence") or [],
            "hard_failures": packet.get("hard_failures") or [],
            "warnings": packet.get("warnings") or [],
        })

    domain_summary = {}
    blockers = Counter()
    for domain in DOMAINS:
        rows = subjects.get(domain, [])
        states = dict(sorted(by_domain.get(domain, Counter()).items()))
        release_eligible = sum(1 for row in rows if row["release_allowed"])
        domain_summary[domain] = {
            "packet_count": len(rows),
            "state_counts": states,
            "release_eligible": release_eligible,
            "release_blocked": len(rows) - release_eligible,
        }
        for row in rows:
            for item in row["missing_evidence"]:
                blockers[(domain, "missing", str(item))] += 1
            for item in row["hard_failures"]:
                blockers[(domain, "hard", str(item))] += 1
            for item in row["warnings"]:
                blockers[(domain, "warning", str(item))] += 1

    proposal_packets = subjects.get("PROPOSAL", [])
    return {
        "contract": CONTRACT,
        "packet_contract": PACKET_CONTRACT,
        "read_only": True,
        "domains": list(DOMAINS),
        "packet_count": len(packets),
        "domain_summary": domain_summary,
        "proposal_release_eligible": sum(1 for row in proposal_packets if row["release_allowed"]),
        "top_blockers": [
            {"domain": domain, "kind": kind, "reason": reason, "count": count}
            for (domain, kind, reason), count in blockers.most_common(50)
        ],
        "packets": {domain: subjects.get(domain, []) for domain in DOMAINS},
        "authority": {
            "database_write": False,
            "packet_rebuild": False,
            "model_provider_call": False,
            "schedule_change": False,
            "service_restart": False,
            "external_action": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    documents = []
    for path in args.inputs:
        with path.open(encoding="utf-8") as handle:
            documents.append(json.load(handle))

    report = census(documents)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
