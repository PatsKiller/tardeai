"""FQ-076: the four disabled filters and an unknown next-review time explain themselves in visible text.

Registered as the CI gate's file, so the shard runner (pytest) executes it. The PROOF is a render test — a ``.mjs``
cannot be collected by pytest, and (cc-deepseek-4's BLOCK at 15:15Z, F1) the sharded pytest job installs Python only:
it has ``node`` but no ``node_modules``, so running a render test from here fails on ``Cannot find module 'typescript'``
before it looks at the page. That would be permanently red for the environment rather than for the page.

So the render runs where the packages are — the frontend ``build`` chain in ``apps/command-center-v3/package.json``
(``npm ci`` then every ``.view.test.mjs``) — and this file guards the registration: if the build step disappears, this
gate fails, and the page loses its proof. That is the pattern #2611 landed for the same reason.

What the render asserts (``apps/command-center-v3/src/lib/watchlistUnavailableReasons.view.test.mjs``): the four-filter
reason and four named controls on the actual page. Missing generic next-review fields say the producer has not provided
a review time, even when CIO defaults to NOT_SCHEDULED while Maria is queued or deferred. Explicit flat times,
conditions and a producer-projected generic negative are preserved. Restoring the CIO-only inference is RED.

Hermetic: node, the committed component and its packages, a synthetic fixture. No browser, no network, no API, no data.

ANCHOR: WATCHLIST_UNAVAILABLE_REASONS_20261104
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER_STEP = "node src/lib/watchlistUnavailableReasons.view.test.mjs"
RENDER = ROOT / "apps/command-center-v3/src/lib/watchlistUnavailableReasons.view.test.mjs"


def test_the_build_chain_runs_the_render_test():
    """The proof runs in the job that has `npm ci`; this asserts the step is still there."""
    assert RENDER.is_file(), f"the render test is missing: {RENDER}"
    pkg = json.loads((ROOT / "apps/command-center-v3/package.json").read_text(encoding="utf-8"))
    steps = [step.strip() for step in pkg["scripts"]["build"].split("&&")]
    assert RENDER_STEP in steps, (
        "the frontend build chain no longer runs the FQ-076 render test — the page has lost its proof; "
        "re-add it before `tsc && vite build`"
    )


def test_the_gate_file_is_the_one_this_test_registers():
    """A gate whose registered file is not this one would leave the render test unrun in CI."""
    gate = ROOT / "config/ci_gates/watchlist_unavailable_reasons_20261104.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["name"] == gate.stem, "the gate name must equal its file stem"
    assert doc["files"] == ["tests/test_watchlist_unavailable_reasons_20261104.py"], doc["files"]
    assert "WATCHLIST_UNAVAILABLE_REASONS_20261104" in " ".join(doc.get("comment") or [])
