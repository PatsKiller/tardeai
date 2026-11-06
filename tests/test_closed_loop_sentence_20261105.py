"""CLOSED_LOOP_SENTENCE_20261105: execute the actual evidence formatter in backend shards.

The rendered production proposal modal is separately exercised by
closedLoopSentence.view.test.mjs in the frontend build, after npm ci. This gate
executes the same formatter used by that caller without requiring npm packages
in Python-only shards. No skips, network, browser, API or live data.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "apps/command-center-v3/src/lib/closedLoopEvidence.test.ts"


def test_actual_evidence_formatter():
    node = shutil.which("node")
    assert node, "Node is required to run the production formatter regression"
    result = subprocess.run(
        [node, "--experimental-strip-types", str(SUITE)],
        cwd=ROOT,
        env={key: value for key, value in os.environ.items() if key in ("PATH", "SYSTEMROOT")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    measured = re.search(r"closedLoopEvidence: ([1-9][0-9]*) passed", result.stdout)
    assert measured, "The real formatter suite must report executed assertions"
