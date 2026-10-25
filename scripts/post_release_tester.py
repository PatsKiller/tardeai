#!/usr/bin/env python3
"""post_release_tester.py — verify every release: API checks at once, browser sweep when allowed (AGENTS.md §29).

    python3 scripts/post_release_tester.py                # dry run: the plan for this tick, runs nothing
    python3 scripts/post_release_tester.py --live         # run what is due; write receipts
    python3 scripts/post_release_tester.py --live --force api   # run one phase now (api | light | nightly)

Phases, windows, the memory gate and receipts: scripts/lib/post_release_tester.py. A FAILED receipt is paged by
scripts/delivery_failure_alerts.py. Exit 0 = ran; 1 = a phase FAILED; 2 = usage/config error.
MBI_BEHAVIOR = 0. Authority: READ_ONLY_ADVISORY (GET only; never restarts, rolls back or writes the server).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import post_release_tester as PRT  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--force", action="append", choices=("api", "light", "nightly"))
    ap.add_argument("--config", type=Path, default=PRT.CONFIG_PATH)
    ap.add_argument("--state-root", type=Path)
    ap.add_argument("--deploy-state-dir", type=Path)
    ap.add_argument("--releases-base", type=Path)
    ap.add_argument("--project-root", type=Path, default=ROOT, help="where scripts/site_sweep.sh lives")
    ap.add_argument("--now", help="ISO time (proofs and tests)")
    a = ap.parse_args(argv)
    try:
        cfg = PRT.load_config(a.config)
    except (OSError, ValueError) as exc:
        print(f"[post-release-tester] config: {exc}", file=sys.stderr)
        return 2
    state_root = a.state_root or Path(
        os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state"
    )
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    env = PRT.Env(
        state_root=state_root,
        deploy_state_dir=a.deploy_state_dir or Path.home() / ".local" / "state" / "cio-phase2-exact-main",
        releases_base=a.releases_base or Path.home() / "trade-ai-releases" / "portfolio-server",
        project_root=a.project_root,
        now=now,
        config=cfg,
        memory=lambda: PRT._default_memory(str(cfg.get("memory_unit") or "portfolio-server.service")),
    )
    report = PRT.tick(env, live=a.live, force=a.force)
    print(json.dumps(report, indent=2, default=str))
    return 1 if any(r.get("status") == PRT.FAILED for r in report.get("results", {}).values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
