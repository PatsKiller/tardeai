#!/usr/bin/env python3
"""hermes-learning cutover — the config edits for each cutover PR, generated so they are exact and reviewable.

Writes ONLY the four config files below, in the checkout given by --repo (default: this file's repo), and only with
--write; never commits, pushes, serves, edits a crontab, a unit or the relay env. Without --write it prints the plan.

    python3 10_cutover_pr.py --phase claim            # PR-1: cron_claim true for the LEARN step lanes (C2 needs it)
    python3 10_cutover_pr.py --phase live             # PR-2: spec mode live, live_arg = cutover_live_arg, stage canary
    python3 10_cutover_pr.py --phase promote          # PR-3: stage cutover (after the 5-day live parity, 03_parity.py)
    python3 10_cutover_pr.py --phase live --write     # apply to the checkout; then run the tests in README "REGRESSION"

Scope: the LEARN stage only (outcome_grader, tag_engine, outcome_feedback_agent, outcome_learning, config_governor).
autonomous_self_tune (tune stage) stays at stage shadow: its cron step runs both the learn and the purge halves in one
--apply, so an n8n-owned effect key would also stop the purge half on cron. Its cutover needs the manifest split PR
first (README "WHAT REMAINS"). score_history_retention is EXCLUDED (cron retention, operator decision).

Files: config/n8n_effect_keys.json (cron_claim), config/n8n_fabric_processes.json (mode), config/n8n_run_allowlist.json
(live_arg), config/lane_registry.json (scheduler.stage).
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

PROCESS = "hermes-learning"
LEARN_STEPS = ("outcome_grader", "tag_engine", "outcome_feedback_agent", "outcome_learning", "config_governor")


def _load(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw), raw


def _set_in_text(raw: str, old: str, new: str, *, count: int = 1) -> str:
    """Byte-preserving edit for the hand-formatted files (spec, effect keys): refuse unless ``old`` occurs exactly
    ``count`` times."""
    if raw.count(old) != count:
        raise SystemExit(f"REFUSED: expected {count} occurrence(s) of {old!r}, found {raw.count(old)}")
    return raw.replace(old, new)


def plan(repo: Path, phase: str) -> dict[str, tuple[str, str]]:
    """{rel_path: (old_text, new_text)} for every file the phase changes."""
    spec_p = repo / "config" / "n8n_fabric_processes.json"
    spec, spec_raw = _load(spec_p)
    proc = spec["processes"][PROCESS]
    lanes = {sid: proc["steps"][sid]["lane_id"] for sid in LEARN_STEPS}
    for sid in LEARN_STEPS:
        if proc["steps"][sid].get("blocked"):
            raise SystemExit(f"REFUSED: step {sid} is BLOCKED in the spec")
    out: dict[str, tuple[str, str]] = {}

    if phase == "claim":
        p = repo / "config" / "n8n_effect_keys.json"
        doc, raw = _load(p)
        new = raw
        for lane in lanes.values():
            if doc["lanes"][lane].get("cron_claim") is True:
                continue
            block = json.dumps(doc["lanes"][lane], ensure_ascii=False)
            if '"cron_claim": false' not in new:
                raise SystemExit(f"REFUSED: {lane} cron_claim not found")
            # edit inside this lane's block only
            start = new.index(f'"{lane}"')
            end = new.index("}", start)
            seg = new[start:end]
            if seg.count('"cron_claim": false') != 1:
                raise SystemExit(f"REFUSED: {lane} block is not the expected shape: {block}")
            new = new[:start] + seg.replace('"cron_claim": false', '"cron_claim": true') + new[end:]
        out["config/n8n_effect_keys.json"] = (raw, new)

    if phase == "live":
        if proc["mode"] != "live":
            out["config/n8n_fabric_processes.json"] = (
                spec_raw,
                _set_in_text(spec_raw, '"mode": "dry_run",', '"mode": "live",'),
            )
        ap = repo / "config" / "n8n_run_allowlist.json"
        allow, araw = _load(ap)
        for e in allow["lanes"]:
            for sid, lane in lanes.items():
                if e["lane_id"] == lane:
                    e["live_arg"] = list(proc["steps"][sid]["cutover_live_arg"])
        out["config/n8n_run_allowlist.json"] = (araw, json.dumps(allow, indent=2, ensure_ascii=False) + "\n")

    if phase in ("live", "promote"):
        stage = "canary" if phase == "live" else "cutover"
        rp = repo / "config" / "lane_registry.json"
        reg, rraw = _load(rp)
        for r in reg["lanes"]:
            if r.get("lane_id") in lanes.values():
                r["scheduler"]["stage"] = stage
        new = json.dumps(reg, indent=2, ensure_ascii=False) + "\n"
        if json.dumps(json.loads(rraw), indent=2, ensure_ascii=False) + "\n" != rraw:
            raise SystemExit("REFUSED: config/lane_registry.json is not in canonical json.dumps(indent=2) form")
        out["config/lane_registry.json"] = (rraw, new)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="10_cutover_pr.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--phase", required=True, choices=("claim", "live", "promote"))
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[4]))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    changes = plan(repo, a.phase)
    for rel, (old, new) in changes.items():
        diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{rel}", f"b/{rel}", lineterm="", n=1))
        print(f"{'WRITE' if a.write else 'WOULD WRITE'} {rel}: {sum(1 for d in diff if d[:1] in '+-') - 2} +/- line(s)")
        if not a.write:
            print("\n".join(diff))
        if a.write and old != new:
            (repo / rel).write_text(new, encoding="utf-8")
    if not a.write:
        print(
            "DRY RUN — nothing written. Re-run with --write in a branch checkout, then `git diff` and the REGRESSION tests."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
