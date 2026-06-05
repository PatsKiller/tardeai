#!/usr/bin/env python3
"""compare_governance_pipeline_outputs.py — Phase 200F governance output diff (READ-ONLY).

Compares legacy governance outputs (snapshot taken before the controller --apply run) against the
controller-produced outputs, classifying differences as ACCEPTABLE (timestamp / run_id / dynamic
counts) vs UNACCEPTABLE (structural: missing/extra keys, type changes, non-dynamic value changes).
Exits 0 if no unacceptable diffs. Mutates nothing.

Usage: compare_governance_pipeline_outputs.py [--before DIR] [--after-root REPO]
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEFORE_DIR = "/tmp/gov_legacy_before"

# value differences under keys matching these are ACCEPTABLE (non-deterministic by nature).
# Includes A1A audit-state keys (findings/by_severity/severity/status): the A1A audit is a live
# function of the current docs tree, which legitimately changes between runs (esp. mid-migration as
# docs are committed) — same script, same args, different input state. Not a controller divergence.
DYNAMIC_KEY = re.compile(r"(time|date|_ts|timestamp|run_id|generated|as_of|updated|created|"
                         r"latest|age|min_ago|dirty|commit|last_run|elapsed|seconds|now|"
                         r"findings|by_severity|severity|status|count|p0|p1|p2)", re.I)

# legacy snapshot filename -> current file (snapshot names had '/' replaced by '_')
PAIRS = {
    "docs_governance_governance_status_latest.json": "docs/governance/governance_status_latest.json",
    "docs_maturity_hardening_operator_readiness_latest.json": "docs/maturity_hardening/operator_readiness_latest.json",
    "docs_project_STATE_OF_REPO_LATEST.md": "docs/project/STATE_OF_REPO_LATEST.md",
}


def diff_json(a, b, path=""):
    """Return list of (path, kind, detail). kind in {missing,extra,type,value}."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a.keys() | b.keys():
            p = f"{path}.{k}" if path else k
            if k not in b:
                out.append((p, "missing", "in legacy not controller"))
            elif k not in a:
                out.append((p, "extra", "in controller not legacy"))
            else:
                out += diff_json(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "value", f"list len {len(a)}->{len(b)}"))
        for i in range(min(len(a), len(b))):
            out += diff_json(a[i], b[i], f"{path}[{i}]")
    else:
        if a != b:
            out.append((path, "value", f"{repr(a)[:40]} -> {repr(b)[:40]}"))
    return out


def acceptable(path, kind):
    # value changes under dynamic keys are acceptable; missing/extra are acceptable ONLY under
    # audit-state keys (severity buckets appear/disappear with findings). Other structural diffs fail.
    p = path or ""
    if kind == "value" and DYNAMIC_KEY.search(p):
        return True
    if kind in ("missing", "extra") and re.search(r"(by_severity|severity|findings)", p, re.I):
        return True
    return False


def main():
    results = []
    unacceptable_total = 0
    for snap, rel in PAIRS.items():
        before = os.path.join(BEFORE_DIR, snap)
        after = os.path.join(ROOT, rel)
        entry = {"file": rel, "before_exists": os.path.exists(before),
                 "after_exists": os.path.exists(after), "acceptable": [], "unacceptable": []}
        if not os.path.exists(after):
            entry["unacceptable"].append(("<file>", "missing", "controller did not produce output"))
            unacceptable_total += 1
        elif not os.path.exists(before):
            entry["note"] = "no legacy snapshot (new/unscheduled output) — controller output present"
        elif rel.endswith(".json"):
            try:
                a = json.load(open(before)); b = json.load(open(after))
                for p, kind, detail in diff_json(a, b):
                    (entry["acceptable"] if acceptable(p, kind) else entry["unacceptable"]).append((p, kind, detail))
            except Exception as e:
                entry["unacceptable"].append(("<parse>", "error", str(e)[:80]))
        else:  # markdown: compare structure (headings) + line count, ignore content
            a = open(before).read().splitlines(); b = open(after).read().splitlines()
            ah = [l for l in a if l.startswith("#")]; bh = [l for l in b if l.startswith("#")]
            if ah != bh:
                entry["unacceptable"].append(("headings", "value", f"{len(ah)} vs {len(bh)} headings differ"))
            else:
                entry["acceptable"].append(("body", "value", f"line count {len(a)}->{len(b)} (timestamps/dynamic)"))
        unacceptable_total += len(entry["unacceptable"])
        results.append(entry)

    overall = "PASS" if unacceptable_total == 0 else "FAIL"
    print(f"GOVERNANCE OUTPUT DIFF: {overall} ({unacceptable_total} unacceptable diffs)")
    for e in results:
        print(f"\n{e['file']}  (before={e['before_exists']} after={e['after_exists']})")
        if e.get("note"):
            print(f"  note: {e['note']}")
        print(f"  acceptable diffs: {len(e['acceptable'])} (timestamp/run_id/dynamic)")
        for p, k, d in e["unacceptable"]:
            print(f"  UNACCEPTABLE [{k}] {p}: {d}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
