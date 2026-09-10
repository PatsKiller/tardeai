#!/usr/bin/env python3
"""run_cortex_shadow_pipeline.py — CLI for Phase 8 AgentView/scoring shadow.

No-ops unless ``AGENT_VIEW_V1_ENABLED`` or ``CORTEX_SHADOW_ENABLED`` is truthy.
``--dry-run`` is the default; pass ``--execute`` to append under ``--state-root``.
Does NOT install systemd/cron. MBI_BEHAVIOR=0; refuses trade verbs via critic.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from scripts.lib.cortex_shadow_pipeline import (  # noqa: E402
    AGENT_VIEW_FLAG,
    CORTEX_SHADOW_FLAG,
    enabled,
    run_cortex_shadow,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--state-root", type=Path, required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--citation", action="append", default=[], dest="citations")
    p.add_argument("--confidence", type=float, default=0.6)
    p.add_argument("--source-sha", default="")
    p.add_argument("--falsifier", default="observation contradicts claim within horizon")
    p.add_argument("--horizon", default="7d")
    p.add_argument("--observation-json", type=Path, default=None,
                   help="optional JSON file with confirmed/refuted observation")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="build artifacts in memory only (default)")
    p.add_argument("--execute", action="store_true",
                   help="append/write under --state-root (overrides dry-run)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = dict(os.environ)

    if not enabled(env):
        print(json.dumps({
            "ok": True,
            "outcome": "disabled",
            "reason": "feature_flag_off",
            "flags": [AGENT_VIEW_FLAG, CORTEX_SHADOW_FLAG],
            "mbi_behavior": 0,
        }, sort_keys=True))
        return 0

    observation = None
    if args.observation_json:
        observation = json.loads(args.observation_json.read_text(encoding="utf-8"))

    citations = list(args.citations) or [f"shadow:{args.subject}"]
    result = run_cortex_shadow(
        subject=args.subject,
        summary=args.summary,
        citations=citations,
        confidence=args.confidence,
        state_root=args.state_root,
        source_sha_value=args.source_sha or None,
        falsifier=args.falsifier,
        horizon=args.horizon,
        observation=observation,
        dry_run=not args.execute,
        env=env,
    )
    print(json.dumps(result.to_dict(), sort_keys=True, default=str))
    return 0 if result.ok or result.disabled else 1


if __name__ == "__main__":
    raise SystemExit(main())
