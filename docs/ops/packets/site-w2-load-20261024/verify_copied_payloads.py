#!/usr/bin/env python3
"""Copy only named JSON/journal inputs, then exercise W2 reads without DB/network.

This measures the isolated handler process, not the served application with all
browser tabs open. The latter proof remains blocked with the browser harness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts"))
from lib import site_payload_reads as reads  # noqa: E402
from lib.scanner_candidate_projection import read_candidate_snapshot  # noqa: E402

INPUTS = ("PERSISTENT_STATE_ROOT.json", "data/runtime/trade_ai_cache.json",
          "data/active_trader/momentum_alerts.jsonl", "data/runtime/identity_registry.json",
          "data/runtime/broker_list_cache.json")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-state", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--now", required=True)
    args = parser.parse_args()
    clock = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    assert clock.tzinfo is not None
    args.out.mkdir(parents=True, exist_ok=False)
    copied = args.out / "copied-state"
    evidence, gaps = {}, []
    for rel in INPUTS:
        source, target = args.source_state / rel, copied / rel
        if not source.is_file():
            gaps.append(f"missing:{rel}")
            continue
        if source.stat().st_size > 64_000_000:
            raise ValueError(f"Input exceeds reviewed copy limit: {rel}")
        evidence[rel] = {"sha256": digest(source), "bytes": source.stat().st_size}
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    cache, journal = copied / INPUTS[1], copied / INPUTS[2]
    raw = read_candidate_snapshot(cache, journal, now=clock, state_root=copied)
    expected = [r["candidate_id"] for r in raw.get("candidates") or []]
    offset, seen, page_bytes = 0, [], []
    while True:
        page = reads.read_candidates(copied, {"filter": "ALL", "offset": offset, "limit": 100}, now=clock)
        assert page["schema"] == "SharedMomentumCandidates@v1"
        size = reads.encoded_size({"ok": True, "data": page})
        assert size < 200_000
        page_bytes.append(size)
        seen.extend(r["candidate_id"] for r in page["candidates"])
        assert not page.get("payload_gap"), page.get("payload_gap")
        if not page["pagination"]["has_more"]:
            break
        offset = page["pagination"]["next_offset"]
        assert offset is not None
    assert seen == expected, "Every observed candidate must be reachable once"
    def poll(i):
        out = reads.read_candidates(copied, {"filter": "ALL", "offset": i % max(1, len(expected)), "limit": 20}, now=clock)
        size = reads.encoded_size({"ok": True, "data": out})
        assert size < 200_000
        return size
    with ThreadPoolExecutor(max_workers=12) as pool:
        stress = list(pool.map(poll, range(180)))
    broker_query = {}
    try:
        snapshots = json.loads((copied / INPUTS[-1]).read_text())
        for key in snapshots:
            if not key.startswith("v2|") or "refresh=" in key or "_=" in key:
                continue
            parts = key[3:].split("|")
            if parts == ["default"]:
                break
            if all("=" in part for part in parts):
                broker_query = dict(part.split("=", 1) for part in parts)
                break
    except (OSError, ValueError):
        gaps.append("broker_cache_unreadable")
    broker = reads.read_broker_list(copied, {**broker_query, "refresh": "1"}, now=clock)
    assert broker["provider_calls"] == 0
    assert reads.encoded_size(broker) < 500_000
    for rel, original in evidence.items():
        assert digest(args.source_state / rel) == original["sha256"]
        assert digest(copied / rel) == original["sha256"]
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    assert peak < 1.3 * 1024**3
    receipt = {"clock": clock.isoformat(), "inputs": evidence, "gaps": gaps,
        "copy_root": str(copied), "source_files_unchanged": True, "copied_files_unchanged": True,
        "provider_calls": 0, "production_db_queries": 0, "browser_executed": False,
        "candidate_count": raw.get("candidate_count"), "all_candidate_ids_reached_once": True,
        "pages": len(page_bytes), "max_candidate_response_bytes": max(page_bytes),
        "concurrent_clients": 12, "handler_polls": len(stress), "peak_handler_rss_bytes": peak,
        "rss_scope": "isolated copied-state handler process; all-browser-pages server RSS unproven",
        "broker_cache_status": broker["cache_status"], "broker_refresh_started": False,
        "broker_query_key_hash": hashlib.sha256(json.dumps(broker_query, sort_keys=True).encode()).hexdigest()}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("candidate_count", "pages", "max_candidate_response_bytes", "peak_handler_rss_bytes", "broker_cache_status", "browser_executed")}))


if __name__ == "__main__":
    main()
