#!/usr/bin/env python3
"""report_n8n_shadow_policy.py — READ-ONLY: regression-canary plan + shadow-cadence savings (N8nShadowPolicy@v1).

  canaries  which ACCEPTED lanes (dispatch live, stage canary/cutover, a verified live run) need a purposeful dry
            run because their config or entry script changed between their last verified live run's code_sha and
            --current-sha (default: CURRENT/BUILD_SHA of the served release, else this checkout's HEAD). Git reads
            only (git show / git diff --quiet). Prints a plan; requests nothing.
  cadence   the shadow-cadence proposals' fires per week and worker-seconds saved (an operator §17 call).

Writes nothing, dispatches nothing. scripts/lib/n8n_shadow_policy.py holds the logic.
Usage: report_n8n_shadow_policy.py {canaries|cadence} [--state-root DIR] [--current-sha SHA] [--policy PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_shadow_policy as SP  # noqa: E402

RUNS_REL = Path("data") / "runtime" / "n8n_runs"
CONFIGS = ("config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json")


def _git(*args: str) -> Optional[str]:
    try:
        p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


@lru_cache(maxsize=64)
def _configs_at(sha: str) -> Optional[tuple]:
    docs = []
    for rel in CONFIGS:
        raw = _git("show", f"{sha}:{rel}")
        if raw is None:
            return None
        try:
            docs.append(json.loads(raw))
        except ValueError:
            return None
    return tuple(docs)


def config_digest(sha: str, lane: str) -> Optional[str]:
    docs = _configs_at(sha)
    return None if docs is None else SP.digest(SP.lane_config(*docs, lane))


def entry_changed(old: str, new: str, lane: str) -> Optional[bool]:
    docs = _configs_at(new)
    if docs is None:
        return None
    path = SP.entry_script(SP.lane_config(*docs, lane)["allowlist_entry"])
    if path is None:
        return None
    try:
        p = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", old, new, "--", path],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: False, 1: True}.get(p.returncode)


def current_sha_default() -> Optional[str]:
    try:
        sha = (Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "BUILD_SHA").read_text().strip()
        if len(sha) == 40:
            return sha
    except OSError:
        pass
    out = _git("rev-parse", "HEAD")
    return out.strip() if out else None


def load_receipts(runs_dir: Path) -> list[dict]:
    out = []
    for name in sorted(os.listdir(runs_dir)):
        if name.endswith(".json"):
            try:
                rec = json.loads((runs_dir / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("canaries", "cadence"))
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT")
                    or str(Path.home() / "trade-ai-releases" / "persistent-state"))
    ap.add_argument("--current-sha", default=None)
    ap.add_argument("--policy", default=str(SP.DEFAULT_POLICY_PATH))
    args = ap.parse_args(argv)
    policy = SP.load_policy(args.policy)
    if args.cmd == "cadence":
        print(json.dumps(SP.cadence_savings(policy), indent=1))
        return 0
    runs_dir = Path(args.state_root) / RUNS_REL
    if not runs_dir.is_dir():
        print(json.dumps({"ok": False, "reason": "runs_dir_missing", "path": str(runs_dir)}))
        return 2
    sha = args.current_sha or current_sha_default()
    if not sha:
        print(json.dumps({"ok": False, "reason": "current_sha_unknown"}))
        return 2
    registry = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    last = SP.last_verified_live(load_receipts(runs_dir))
    lanes = SP.accepted_lanes(registry, last, policy)
    plan = SP.plan_regression_canaries(lanes, last, sha, policy, config_digest=config_digest,
                                       entry_changed=entry_changed)
    print(json.dumps(plan, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
