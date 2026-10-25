#!/usr/bin/env python3
"""W8 source/receipt CHECK. Prints JSON; never executes or activates a writer."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_writer_restoration import audit, health_proposals  # noqa: E402


def read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("oversized source/capture")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("source/capture must be an object")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--capture", type=Path, help="explicit copied receipt map; never reads live state")
    parser.add_argument("--now", help="aware ISO observation time; pin for repeatable fixture evidence")
    parser.add_argument("--health-proposals", action="store_true", help="print nonoperative owner-review drafts")
    args = parser.parse_args(argv)
    try:
        catalog = read_json(args.root / "config/n8n_writer_restoration.json")
        if args.health_proposals:
            print(json.dumps(health_proposals(catalog), indent=2, ensure_ascii=False))
            return 0
        manifests = {}
        for writer in catalog["writers"]:
            source = (args.root / writer["source"]).resolve()
            if not source.is_relative_to(args.root.resolve()) or not source.is_file():
                raise ValueError(f"writer source is unavailable: {writer['key']}")
            binding = writer.get("pipeline")
            if binding:
                relative = binding["manifest"]
                path = (args.root / relative).resolve()
                if not path.is_relative_to(args.root.resolve() / "config/pipelines"):
                    raise ValueError("manifest path outside config/pipelines")
                manifests[relative] = {"document": read_json(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
        report = audit(catalog, read_json(args.root / "config/lane_registry.json"),
                       read_json(args.root / "config/n8n_run_allowlist.json"),
                       read_json(args.root / "config/n8n_health_contracts.json"), manifests,
                       now=now, receipts=read_json(args.capture) if args.capture else {})
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"W8 CHECK cannot run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
