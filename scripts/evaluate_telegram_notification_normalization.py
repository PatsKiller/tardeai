#!/usr/bin/env python3
"""Replay Telegram audit CSVs through notification-normalization policy."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from notification_url_builder import operator_text_policy_violations, publicize_message, sanitize_operator_message
from operator_alert_policy_v2 import APPROVALS_ONLY, alert_fingerprint, classify_legacy_message, incident_id_for, route_event


def evaluate(path: Path) -> dict:
    rows = list(csv.DictReader(path.open(newline="")))
    route_counts = Counter()
    digest_counts = Counter()
    immediate_incidents = set()
    immediate_raw = 0
    duplicate_suppression = 0
    cross_channel_duplicate_count = 0
    approval_total = 0
    approval_live_auth = 0
    paper_to_approvals = 0
    violations_before = Counter()
    violations_after = Counter()
    seen_fingerprints = set()
    messages_by_text = defaultdict(set)

    for row in rows:
        text = row.get("text") or ""
        ev = classify_legacy_message(text, source_producer=f"csv:{row.get('chat') or 'unknown'}")
        decision = route_event(ev)
        fp = alert_fingerprint(ev)
        if fp in seen_fingerprints:
            duplicate_suppression += 1
        else:
            seen_fingerprints.add(fp)
        for v in operator_text_policy_violations(publicize_message(text)):
            violations_before[v] += 1
        sanitized, _ = sanitize_operator_message(text)
        for v in operator_text_policy_violations(sanitized):
            violations_after[v] += 1
        route_counts[decision.route_mode] += 1
        if decision.digest_bucket:
            digest_counts[decision.digest_bucket] += 1
        if decision.route_mode == "IMMEDIATE":
            immediate_raw += 1
            immediate_incidents.add(incident_id_for(ev))
        if decision.logical_destination == APPROVALS_ONLY:
            approval_total += 1
            if ev.operator_action_required and ev.authorization_or_order_id:
                approval_live_auth += 1
            if ev.alert_type.startswith("paper") or "paper proposal" in text.lower():
                paper_to_approvals += 1
        normalized_text = " ".join(publicize_message(text).split())
        if normalized_text:
            messages_by_text[normalized_text].add(decision.logical_destination or decision.route_mode)

    for channels in messages_by_text.values():
        if APPROVALS_ONLY in channels and "CRITICAL_OPERATIONS" in channels:
            cross_channel_duplicate_count += 1

    return {
        "fixture": str(path),
        "rows": len(rows),
        "route_counts": dict(route_counts),
        "digest_counts": dict(digest_counts),
        "immediate_raw_count": immediate_raw,
        "immediate_correlated_incident_count": len(immediate_incidents),
        "dashboard_only_count": route_counts.get("COMMAND_CENTER", 0),
        "log_only_count": route_counts.get("LOG", 0),
        "duplicate_suppression_count": duplicate_suppression,
        "cross_channel_duplicate_count": cross_channel_duplicate_count,
        "approval_total": approval_total,
        "approval_live_authorization_count": approval_live_auth,
        "paper_to_approvals_count": paper_to_approvals,
        "url_policy_violations_before_sanitize": dict(violations_before),
        "url_policy_violations_after_sanitize": dict(violations_after),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = evaluate(args.csv_path)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for k, v in result.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
