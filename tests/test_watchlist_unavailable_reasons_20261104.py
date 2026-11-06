"""FQ-076: the four disabled filters and an unknown next-review time explain themselves in visible text.

Registered as the CI gate's file, so the shard runner (pytest) executes it. The PROOF is a render test — a ``.mjs``
cannot be collected by pytest, and (cc-deepseek-4's BLOCK at 15:15Z, F1) the sharded pytest job installs Python only:
it has ``node`` but no ``node_modules``, so running a render test from here fails on ``Cannot find module 'typescript'``
before it looks at the page. That would be permanently red for the environment rather than for the page.

So the render runs where the packages are — the frontend ``build`` chain in ``apps/command-center-v3/package.json``
(``npm ci``, then ``node scripts/run-tests.mjs``, which runs every discovered test under ``src/``) — and this file
guards the coverage: if the file stops being discovered (or becomes dormant), this gate fails and the page loses its
proof. It does not pin the retired explicit step: discovery runs the file because it exists, and naming it again would
run it twice (cc-deepseek-9's BLOCK at a5ab0a0e1; the same defect #2676 removed).

What the render asserts (``apps/command-center-v3/src/lib/watchlistUnavailableReasons.view.test.mjs``): the four-filter
reason and four named controls on the actual page. Missing generic next-review fields say the producer has not provided
a review time, even when CIO defaults to NOT_SCHEDULED while Maria is queued or deferred. Explicit flat times,
conditions and a producer-projected generic negative are preserved. Restoring the CIO-only inference is RED.

Hermetic: node, the committed component and its packages, a synthetic fixture. No browser, no network, no API, no data.

ANCHOR: WATCHLIST_UNAVAILABLE_REASONS_20261104
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "apps/command-center-v3/src/lib/watchlistUnavailableReasons.view.test.mjs"


def test_the_build_chain_runs_the_render_test():
    """The proof runs in the job that has `npm ci`. Since #2676 the build discovers tests instead of naming them, so
    coverage here means: the runner is in the build chain, this file matches its discovery pattern, and it is not
    dormant. Asserting the old explicit step would pin a mechanism main retired — and re-adding that step would run
    this test twice."""
    assert RENDER.is_file(), f"the render test is missing: {RENDER}"
    app = ROOT / "apps/command-center-v3"
    pkg = json.loads((app / "package.json").read_text(encoding="utf-8"))
    assert "scripts/run-tests.mjs" in pkg["scripts"]["build"], (
        "the frontend build chain no longer runs the discovered test set — the page has lost its proof")
    assert re.search(r"\.test\.(ts|mjs|js|tsx|jsx)$", RENDER.name), (
        f"{RENDER.name} does not match the runner's discovery pattern, so it would never run")
    rel = str(RENDER.relative_to(app))
    dormant = json.loads((app / "scripts/tests.dormant.json").read_text(encoding="utf-8")).get("files") or {}
    assert rel not in dormant, f"the render test is dormant ({rel}); discovery will not run it"


def test_the_gate_file_is_the_one_this_test_registers():
    """A gate whose registered file is not this one would leave the render test unrun in CI."""
    gate = ROOT / "config/ci_gates/watchlist_unavailable_reasons_20261104.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["name"] == gate.stem, "the gate name must equal its file stem"
    assert doc["files"] == ["tests/test_watchlist_unavailable_reasons_20261104.py"], doc["files"]
    assert "WATCHLIST_UNAVAILABLE_REASONS_20261104" in " ".join(doc.get("comment") or [])
