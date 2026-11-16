"""CI gate wrapper for the Wealth Portfolio browser acceptance suite.

Builds the wealth bundle (or uses WEALTH_QUAL_DIST) and runs
apps/wealth/qual/portfolio/run.cjs. The suite is an acceptance gate: it is red
while any Portfolio lane is unfinished. Skips when Node/Playwright is absent.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
WEALTH = ROOT / "apps" / "wealth"
RUNNER = WEALTH / "qual" / "portfolio" / "run.cjs"


def _node_path():
    for cand in (os.environ.get("WEALTH_QUAL_NODE_PATH"), str(WEALTH / "node_modules"), str(ROOT / "node_modules")):
        if cand and (Path(cand) / "playwright").exists():
            return cand
    return None


def test_portfolio_browser_acceptance():
    node = shutil.which("node")
    node_path = _node_path()
    if not node or not node_path:
        pytest.skip("node or playwright not available")
    work = Path(tempfile.mkdtemp(prefix="wealth-qual-"))
    dist = os.environ.get("WEALTH_QUAL_DIST")
    env = dict(os.environ, NODE_PATH=node_path)
    if not dist:
        dist = str(work / "dist")
        build = subprocess.run(["npx", "vite", "build", "--outDir", dist], cwd=WEALTH, env=env,
                               capture_output=True, text=True, timeout=900)
        assert (Path(dist) / "index.html").exists(), build.stdout[-800:] + build.stderr[-800:]
    run = subprocess.run([node, str(RUNNER), "--dist", dist, "--out", str(work / "out")], env=env,
                         capture_output=True, text=True, timeout=1800)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1000:]
