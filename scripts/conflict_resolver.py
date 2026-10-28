#!/usr/bin/env python3
"""Conflict resolver host runner. Dry-run is write-free; shadow is ledger only.

There is no live/notification mode. Scheduler admission and operator activation
are owned separately by W8. This CLI never calls a broker or model provider.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.conflicts.adapters import (EvaluationInputs, evaluate_inputs, security_inputs_from_truth, timestamp)
from scripts.lib.conflicts.engine import ENGINE_VERSION, Input, Subject
from scripts.lib.conflicts.ledger import ConflictLedger, decision_inputs
from scripts.lib.conflicts.profiles import PROFILES
from scripts.lib.conflicts.profiles.rulebook import RULEBOOK

# ConflictResolverReceipt@v1 is the shadow comparison report (data/conflicts/reports/<run>.json). Its reader is the
# operator's two-trading-day shadow review; the lane's LaneRunReceipt@v2 (which names this report as output evidence)
# is what Jobs & health reads. A programmatic consumer arrives only with the operator's live flip.
NO_CONSUMER_REASON = "shadow comparison report for the operator's 2-trading-day shadow review; lane receipt carries it"


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False).encode()


def collect_inputs(root, now):
    """Only registered W1 canonical and existing read-only broker projections."""
    from scripts.lib.cio_truth import resolve, security_inputs_for, stances_for_symbols
    from scripts.lib.ips_policy import policy_for_security
    from scripts.lib.data_broker.cio_prospect import get_prospects
    from scripts.lib.data_broker.watch_intelligence import compose_universe
    from scripts.lib.data_broker.watch_decision import reentry_rows
    composed = compose_universe(view="all", page_size=100)
    cards = {(row.get("card") or {}).get("symbol"): row.get("card") or {} for row in composed["items"]}
    desk = reentry_rows()
    symbols = sorted(set(cards) | set(desk))
    projection = get_prospects(shadow_base=Path(root) / "data/cio/cio_prospect_shadow.json", now=now)
    canonicals = stances_for_symbols(symbols, root=root, projection=projection, now=now)
    document = resolve(root, now)
    bundles = []
    for symbol in symbols:
        guid = (canonicals.get(symbol) or {}).get("security_guid")
        truth = security_inputs_for(guid, document=document, projection=projection, now=now)
        truth["symbol"] = symbol
        truth.setdefault("context", {})["concentration_policy"] = policy_for_security(guid, document=document)
        bundles.append(security_inputs_from_truth(truth, card=cards.get(symbol), reentry=desk.get(symbol)))
    return bundles


def fixture_inputs(path):
    """Explicit replay inputs; never interpreted as current production acceptance."""
    document = json.loads(Path(path).read_text())
    bundles = []
    def item(row):
        if row is None:
            return None
        row = dict(row)
        if any(row.get(k) and timestamp(row[k]) is None for k in ("as_of", "inputs_as_of")):
            row["metadata"] = {**row.get("metadata", {}), "time_error": True}
        row["as_of"] = timestamp(row.get("as_of"))
        row["inputs_as_of"] = timestamp(row.get("inputs_as_of"))
        return Input(**row)
    for row in document["subjects"]:
        bundles.append(EvaluationInputs(Subject(**row["subject"]), item(row.get("canonical")),
            [item(i) for i in row.get("inputs", [])], PROFILES[row.get("profile", "security_stance")]))
    return bundles


def _run(root, bundles, *, now, shadow=False, run_id=None, memory_writer=None, pg_writer=None, pg_enabled=False):
    """Library entry for reviewed scheduler/fixture callers; no sender exists."""
    started = time.monotonic()
    root = Path(root)
    run_id = run_id or os.environ.get("TRADEAI_RUN_ID") or "conflict-" + uuid.uuid4().hex
    bundles = list(bundles)
    target = root / "data/conflicts/reports" / (hashlib.sha256(run_id.encode()).hexdigest() + ".json")
    st = ConflictLedger(root, memory_writer=memory_writer, pg_writer=pg_writer, pg_enabled=pg_enabled)
    before = st.records()
    before_hash = hashlib.sha256(st.path.read_bytes() if st.path.exists() else b"").hexdigest()
    # Observation history is derived, recoverable poll evidence; not a judgment store.
    observation_path = root / "data/conflicts/conflict_observations.jsonl"
    prior = [json.loads(line) for line in observation_path.read_text().splitlines()] if observation_path.exists() else []
    if shadow and (target.exists() or any(h.get("run_id") == run_id for h in prior)):
        raise ValueError("duplicate or uncertain conflict resolver attempt")
    observations = []
    findings = []
    events = []
    # The one rule-proposal hook (docs/ops/CONFLICT_RULE_PROPOSALS.md): approved data-only amendments, then the
    # unchanged engine, then UNMATCHED detection. A broken amendment store applies no amendment and says so.
    from scripts.lib.conflicts import proposals as rule_proposals
    try:
        effective, amendments_gap = rule_proposals.effective_rulebook(root), None
    except (OSError, ValueError) as exc:
        effective, amendments_gap = None, f"rulebook amendments unavailable: {exc}"
    unmatched = []
    for bundle in bundles:
        bundle = deepcopy(bundle)
        bundle.inputs.extend(decision_inputs(root, bundle.subject, now=now))
        subject_prior = [h for h in prior if h.get("subject_id") == bundle.subject.id]
        current, subject_unmatched = rule_proposals.evaluate(bundle, now=now, history=subject_prior,
                                                             effective=effective, evaluate_inputs=evaluate_inputs)
        unmatched.extend(subject_unmatched)
        findings.extend(f.as_dict() for f in current)
        sources = [i.source for i in bundle.inputs if i.as_of and i.metadata.get("quality", "complete") == "complete"]
        if bundle.canonical:
            sources.append(bundle.canonical.source)
        observed = False
        for f in current:
            if f.rule in {"R15", "U7", "R11"}:
                from scripts.lib.conflicts.profiles.vocabulary import ordinal
                signature = sorted([[i["source"], ordinal(i["value"], bundle.subject.context.get("held"))] for i in f.sides])
                observations.append({"run_id": run_id, "subject_id": bundle.subject.id, "key": f.key,
                                     "signature": signature, "observed_at": now.isoformat()})
                observed = True
        if not observed:
            observations.append({"run_id": run_id, "subject_id": bundle.subject.id,
                                 "key": f"{bundle.subject.kind}:{bundle.subject.id}:reset", "signature": [],
                                 "observed_at": now.isoformat()})
        events.extend(st.reconcile(bundle.subject, current, at=now, observed_sources=sources, apply=shadow))
    report = {"schema": "ConflictResolverReceipt@v1", "phase": "shadow" if shadow else "dry_run", "run_id": run_id,
              "status": "ok", "started_at": now.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
              "engine_version": ENGINE_VERSION, "rulebook_version": RULEBOOK["version"],
              "rulebook_sha256": hashlib.sha256((ROOT / "config/conflict_rulebook.json").read_bytes()).hexdigest(),
              "matrix_sha256": RULEBOOK.get("matrix_sha256"),
              "input_manifest_sha256": hashlib.sha256(_bytes([asdict(b) for b in bundles])).hexdigest(),
              "ledger_before_sha256": before_hash,
              "findings_count": len(findings), "findings": findings, "events_written": len(events) if shadow else 0,
              "planned_events": events if not shadow else [], "notifications": 0,
              "comparison": {"before": len(before), "after": len(st.records()) if shadow else len(before)},
              "unmatched_count": len(unmatched), "unmatched": unmatched, "amendments_gap": amendments_gap,
              "effective_rulebook_version": (effective or {}).get("version"),
              "duration_seconds": time.monotonic() - started}
    if shadow:
        if unmatched:
            rule_proposals.record_unmatched(root, unmatched, at=now, run_id=run_id)
        if observations:
            observation_path.parent.mkdir(parents=True, exist_ok=True)
            with observation_path.open("a") as handle:
                for observation in observations:
                    handle.write(_bytes(observation).decode() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        from scripts.lib.lane_last_receipt import write_lane_receipt
        receipt = write_lane_receipt("conflict-resolver", ok=True, exit_code=0, started_at=now.isoformat(),
            script="scripts/conflict_resolver.py", path=root / "data/runtime/conflict-resolver_last.json",
            summary={"phase": "shadow", "notifications": 0, "rulebook_sha256": report["rulebook_sha256"]},
            produced_count=1, attempted_count=len(bundles), output_evidence=[{"path": str(target),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "kind": "comparison_report"}])
        if receipt is None:
            raise RuntimeError("conflict resolver receipt write failed")
    return report


def run(root, bundles, *, now, shadow=False, **kwargs):
    if not shadow:
        return _run(root, bundles, now=now, shadow=False, **kwargs)
    lock = Path(root) / "data/conflicts/conflict_resolver.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return _run(root, bundles, now=now, shadow=True, **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--shadow", action="store_true")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--input-file")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    run_id = os.environ.get("TRADEAI_RUN_ID")
    try:
        if args.input_file:
            bundles = fixture_inputs(args.input_file)
        else:
            # R9 wash windows, R10 option positions, R12 pending fills — read-only stored-state producers.
            from scripts.lib.conflicts.producers import attach as attach_producers
            bundles, _ = attach_producers(collect_inputs(args.state_root, now), now=now, root=args.state_root)
        from scripts.lib.conflicts.cio import memory_writer
        result = run(args.state_root, bundles, now=now, shadow=args.shadow,
                     run_id=run_id,
                     memory_writer=memory_writer(args.state_root) if args.shadow else None)
        if not args.shadow:
            # The shadow-stage dry_run fire (AGENTS.md §23.12) is the ladder step that must advance ok_at so the
            # lane's output_signal (data/runtime/conflict-resolver_last.json, json_key ok_at) is real for
            # r1_class_admission and the heartbeat watcher. The dry run stays write-free against the judgment ledger
            # (no conflict_events.jsonl, no observations, no comparison report) and writes only this monitoring
            # receipt. W10 owns scripts/conflict_resolver.py; this receipt-on-dry-run change is a PROPOSED edit for
            # the W10 owner handoff.
            from scripts.lib.lane_last_receipt import write_lane_receipt
            receipt = write_lane_receipt("conflict-resolver", ok=True, exit_code=0, started_at=now.isoformat(),
                script="scripts/conflict_resolver.py",
                path=Path(args.state_root) / "data/runtime/conflict-resolver_last.json",
                summary={"phase": "dry_run", "notifications": 0, "rulebook_sha256": result.get("rulebook_sha256")},
                produced_count=1, attempted_count=len(bundles))
            if receipt is None:
                print(json.dumps({"ok": False, "error": "receipt_write_failed", "phase": "dry_run",
                                  "notifications": 0}), file=sys.stderr)
                return 2
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        if args.shadow:
            from scripts.lib.lane_last_receipt import write_lane_receipt
            write_lane_receipt("conflict-resolver", ok=False, exit_code=2, started_at=now.isoformat(),
                script="scripts/conflict_resolver.py", path=Path(args.state_root) / "data/runtime/conflict-resolver_last.json",
                summary={"phase": "shadow", "notifications": 0}, error=type(exc).__name__, produced_count=0,
                attempted_count=0, empty_reason="run_failed")
        print(json.dumps({"ok": False, "error": type(exc).__name__, "phase": "shadow" if args.shadow else "dry_run",
                          "notifications": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
