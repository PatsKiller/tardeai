#!/usr/bin/env python3
"""Fail when a producer writes state the served plane never reads.

The defect this exists to catch
-------------------------------
`scripts/lib/persistent_overlay.py` declares OVERLAY_RELS -- the trees that
"must symlink into GOOD_PERSISTENT_ROOT" -- and the deploy applies that rule to
the RELEASE directory. It was never applied to the canonical source tree, which
is where the batch plane actually executes: 106 active cron lines cd into
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild and write its real
data/runtime, while the API reads CURRENT/data/runtime -> persistent-state.

Two directories, two inodes, no error anywhere. Measured 2026-09-12:

    served   data/runtime/sector_momentum_latest.json  inode 9633692  Aug 25
    producer data/runtime/sector_momentum_latest.json  inode 3573658  Sep 11

The board consequently served a 17-day-old oscillator reading while the
producer had a current one, and nothing in the pipeline was failing. This is
the L1 producer-to-consumer reachability clause: the snapshot a producer writes
must be the snapshot the reader serves.

Exit codes
----------
0  every overlay tree resolves to one inode, or divergence is within tolerance
1  at least one tree is forked, or a served copy lags its producer copy
2  the check could not run (never reported as a pass)
"""

from __future__ import annotations

#: Dark-contract guard: StateRootSplitCheck@v1 has no in-repo caller on purpose.
#:
#: The obvious consumer is cio_phase2_exact_main_deploy.sh, gating promote on a
#: clean census. Wiring that now would block EVERY deploy on a pre-existing
#: condition: 164 served files are currently behind their producers across five
#: overlay trees, and the reconciliation is not a change an agent may make
#: unattended -- the fork is bidirectional (19 files in data/runtime are newer on
#: the SERVED side, by up to 31.9 days), so a newer-wins merge destroys real data
#: in whichever direction it runs, and data/portfolios/state holds live holdings.
#:
#: So this ships as an operator-run detector first. The gate wiring belongs in
#: the same change that reconciles the existing divergence, which needs a human
#: decision per file. Procedure and the per-file direction census:
#: trade-ai-campaigns/trade-ai-maturity-overnight-20260912/final/
#: STATE_ROOT_RECONCILIATION_RUNBOOK.md
NO_CONSUMER_REASON = (
    "Operator-run detector for the producer/served state-root fork. The consumer "
    "is the promote gate in cio_phase2_exact_main_deploy.sh, which cannot be "
    "wired until the existing 164-file divergence is reconciled -- gating promote "
    "on a pre-existing condition would block every deploy. The reconciliation is "
    "bidirectional and needs operator adjudication per file."
)

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.persistent_overlay import OVERLAY_RELS, overlay_data_source  # noqa: E402

DEFAULT_CANONICAL = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
DEFAULT_SERVED = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")

#: A producer copy may legitimately be a few minutes ahead of the served copy
#: mid-write. Beyond this the two roots are genuinely different stores.
DEFAULT_TOLERANCE_S = 300


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def compare_tree(producer_root: Path, served_root: Path, rel: str, tolerance_s: int) -> dict:
    """Compare one overlay-relative tree across the two roots."""
    p_dir = _resolved(producer_root / rel)
    s_dir = _resolved(served_root / rel)
    out: dict = {
        "rel": rel,
        "producer_path": str(p_dir),
        "served_path": str(s_dir),
        "same_directory": p_dir == s_dir,
        "producer_exists": p_dir.is_dir(),
        "served_exists": s_dir.is_dir(),
        "common_files": 0,
        "producer_newer": [],
        "producer_only": [],
        "max_lag_seconds": 0.0,
    }
    if out["same_directory"]:
        # One inode by construction: nothing can diverge.
        return out
    if not (out["producer_exists"] and out["served_exists"]):
        return out

    p_files = {f.name: f for f in p_dir.iterdir() if f.is_file()}
    s_files = {f.name: f for f in s_dir.iterdir() if f.is_file()}
    common = sorted(set(p_files) & set(s_files))
    out["common_files"] = len(common)
    out["producer_only"] = sorted(set(p_files) - set(s_files))
    for name in common:
        try:
            p_m = p_files[name].stat().st_mtime
            s_m = s_files[name].stat().st_mtime
        except OSError:
            continue
        lag = p_m - s_m
        if lag > tolerance_s:
            out["producer_newer"].append({"file": name, "lag_seconds": round(lag, 1)})
            out["max_lag_seconds"] = max(out["max_lag_seconds"], round(lag, 1))
    out["producer_newer"].sort(key=lambda r: -r["lag_seconds"])
    return out


def run_check(
    *,
    producer_root: Path,
    served_root: Path,
    rels: tuple[str, ...] = OVERLAY_RELS,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> dict:
    trees = [compare_tree(producer_root, served_root, rel, tolerance_s) for rel in rels]
    forked = [t for t in trees if not t["same_directory"] and t["producer_exists"] and t["served_exists"]]
    stale = [t for t in trees if t["producer_newer"]]
    return {
        "schema": "StateRootSplitCheck@v1",
        "producer_root": str(producer_root),
        "served_root": str(served_root),
        "persistent_root": str(overlay_data_source(canonical_source=producer_root)),
        "tolerance_seconds": tolerance_s,
        "trees": trees,
        "forked_trees": [t["rel"] for t in forked],
        "trees_with_stale_served_copies": [t["rel"] for t in stale],
        "total_stale_files": sum(len(t["producer_newer"]) for t in trees),
        "ok": not stale,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--producer-root", default=str(DEFAULT_CANONICAL))
    ap.add_argument("--served-root", default=str(DEFAULT_SERVED))
    ap.add_argument("--tolerance-seconds", type=int, default=DEFAULT_TOLERANCE_S)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--max-listed", type=int, default=12, help="cap the per-tree file list in text output"
    )
    args = ap.parse_args(argv)

    try:
        report = run_check(
            producer_root=Path(args.producer_root),
            served_root=Path(args.served_root),
            tolerance_s=args.tolerance_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — a check that cannot run is not a pass
        print(f"STATE_ROOT_CHECK_UNAVAILABLE: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    print("State root split check")
    print(f"  producer root  : {report['producer_root']}")
    print(f"  served root    : {report['served_root']}")
    print(f"  persistent root: {report['persistent_root']}")
    for tree in report["trees"]:
        if tree["same_directory"]:
            print(f"  OK   {tree['rel']}: one directory ({tree['producer_path']})")
            continue
        if not (tree["producer_exists"] and tree["served_exists"]):
            print(f"  --   {tree['rel']}: only one side present, nothing to compare")
            continue
        n = len(tree["producer_newer"])
        mark = "FAIL" if n else "ok"
        print(
            f"  {mark} {tree['rel']}: FORKED, {tree['common_files']} common files, "
            f"{n} served copies behind, max lag {tree['max_lag_seconds']}s, "
            f"{len(tree['producer_only'])} producer-only"
        )
        for row in tree["producer_newer"][: args.max_listed]:
            print(f"        {row['file']}  behind by {row['lag_seconds'] / 86400:.1f}d")
        if n > args.max_listed:
            print(f"        ... {n - args.max_listed} more")
    print()
    if report["ok"]:
        print("PASS: no served copy lags its producer copy.")
        return 0
    print(
        f"FAIL: {report['total_stale_files']} served files are behind the producer that writes "
        f"them. The read plane is not serving what the batch plane produced."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
