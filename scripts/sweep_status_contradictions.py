#!/usr/bin/env python3
"""ANCHOR: SWEEP_STATUS_CONTRADICTIONS_LQ1803_20261110 — list every receipt whose health fields disagree.

LQ-20261107-1803, operator addendum 20261110T1725Z, deliverable 2:

    "A sweep script: lists every CURRENT runtime/*_last.json contradiction (path, fields, values). Quote its output
     BEFORE your fix and AFTER (on live, after fold) in READY."

Read-only. It walks ``<state-root>/data/runtime/*_last.json`` and ``*_last_run.json`` — the mutable last-run documents
every lane and the n8n executor publish — and asks ``scripts.lib.status_consistency`` what each one claims. A document
is a CONTRADICTION when one of its health fields (``status``, ``outcome``, ``verdict``, ``health``,
``overall_status``, ``display``, ``display_state``, ``summary.verdict``) or its exit code ranks worse than its own
``status``. An ``unknown``-ranked claim is an ADVISORY: reported, never rewritten (see the module docstring).

Two rows per document are printed when they differ:

* ``file``    — what is written on disk now (the field that disagrees, and its value);
* ``display`` — what the Jobs projection shows for it: the same reconcile the writer and the readers apply, so a
  pre-fix file still renders truthfully before its lane next runs.

Usage::

    python3 scripts/sweep_status_contradictions.py [--state-root DIR] [--json] [--fail-on-contradiction]

Exit status: 0 when it ran (contradictions found or not), 1 only with ``--fail-on-contradiction`` and at least one
contradiction, 2 on a bad invocation. Nothing under the state root is opened for writing. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import status_consistency as SC  # noqa: E402

GLOBS = ("*_last.json", "*_last_run.json")


def _docs(runtime: Path):
    seen: set[Path] = set()
    for pattern in GLOBS:
        for path in sorted(runtime.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def sweep(state_root: Path) -> dict:
    runtime = state_root / "data/runtime"
    out = {"schema": "StatusContradictionSweep@v1", "state_root": str(state_root), "runtime": str(runtime),
           "read": 0, "unreadable": [], "contradictions": [], "advisories": [], "clean": 0}
    if not runtime.is_dir():
        out["unreadable"].append({"path": str(runtime), "error": "no such directory"})
        return out
    for path in _docs(runtime):
        out["read"] += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out["unreadable"].append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not isinstance(doc, dict):
            out["unreadable"].append({"path": str(path), "error": f"top level is {type(doc).__name__}, not an object"})
            continue
        result = SC.scan(doc)
        rel = str(path.relative_to(state_root))
        item = {"path": rel, "status": result["status"], "outcome": result["outcome"],
                "fields": [{"field": c["field"], "value": c["value"], "rank": c["rank"]}
                           for c in (result["contradictions"] or result["advisories"])]}
        if result["contradictions"]:
            item["display"] = {"status": result["proposed_status"], "outcome": result["proposed_outcome"]}
            out["contradictions"].append(item)
        elif result["advisories"]:
            out["advisories"].append(item)
        else:
            out["clean"] += 1
    return out


def _render(result: dict) -> str:
    lines = [f"status sweep  state_root={result['state_root']}  files={result['read']}  "
             f"contradictions={len(result['contradictions'])}  advisories={len(result['advisories'])}  "
             f"clean={result['clean']}"]
    if result["contradictions"]:
        lines.append("")
        lines.append("CONTRADICTIONS (the file says two things about one run):")
        for c in result["contradictions"]:
            fields = ", ".join(f"{f['field']}={f['value']!r} ({f['rank']})" for f in c["fields"])
            lines.append(f"  {c['path']}")
            lines.append(f"    file:    status={c['status']!r} outcome={c['outcome']!r}; {fields}")
            lines.append(f"    display: status={c['display']['status']!r} outcome={c['display']['outcome']!r}"
                         "  (what the Jobs page shows after the LQ-1803 reconcile)")
    if result["advisories"]:
        lines.append("")
        lines.append("ADVISORIES (a health claim with no status field to reconcile, or an unverified/unknown claim:"
                     " reported, never rewritten):")
        for a in result["advisories"]:
            fields = ", ".join(f"{f['field']}={f['value']!r}" for f in a["fields"])
            lines.append(f"  {a['path']}  status={a['status']!r}; {fields}")
    if result["unreadable"]:
        lines.append("")
        lines.append("UNREADABLE (not judged, listed so the sweep cannot look clean by skipping a file):")
        for u in result["unreadable"]:
            # REVIEW-LQ1829 S2: acceptance 4's literal phrase, so a reader sees the cause beside the path.
            lines.append(f"  {u['path']}  cannot be read: {u['error']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT")
                    or str(Path.home() / "trade-ai-releases/persistent-state"))
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--fail-on-contradiction", action="store_true", help="exit 1 when a contradiction is found")
    args = ap.parse_args(argv)
    root = Path(args.state_root)
    if not root.is_dir():
        print(f"state root not found: {root}", file=sys.stderr)
        return 2
    result = sweep(root)
    print(json.dumps(result, indent=1, sort_keys=True) if args.json else _render(result))
    if args.fail_on_contradiction and result["contradictions"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
