#!/usr/bin/env python3
"""catalyst-momentum-engine-overnight entry (2026-10-14): the overnight band of catalyst_momentum_engine.py, with
no proposal handoff in its reach.

CLI: python3 scripts/catalyst_momentum_overnight.py [--band overnight] [--apply] [--dry-run]

Same work and lane receipt (data/runtime/catalyst-momentum-engine-overnight_last.json) as
`catalyst_momentum_engine.py --band overnight [--apply]`, which is what the overnight cron line runs: catalyst
findings staged into hermes_research_intelligence. `--generate-proposals` does not exist here, and nothing this
entry reaches references auto_proposal_generator.py, so advisory_lane_guard.scan_entry finds no send, no account
read and no broker client module (AGENTS.md §23.20 / the 7.0.0 dispatcher sender gate). --dry-run is write-free
(catalyst_momentum_engine._dry_run).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalyst_momentum_engine import run_overnight  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_overnight())
