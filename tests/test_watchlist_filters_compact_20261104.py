"""FQ-077: at phone width the whole filter toolbar is inside the disclosure; nothing renders twice.

Registered as the CI gate's file, so the shard runner (pytest) executes it. The PROOF is a render test — a ``.mjs``
cannot be collected by pytest, and the sharded pytest job installs Python only: it has ``node`` but no ``node_modules``
(cc-deepseek-4's F1 on #2606, same class, same day). A render test run from here would fail on ``Cannot find module
'typescript'`` before it looked at the page — red for the environment, not the page.

So the render runs where the packages are: the frontend ``build`` chain in ``apps/command-center-v3/package.json``
(``npm ci`` then every ``.view.test.mjs``), and this file guards the registration — if the build step disappears, this
gate fails and the page loses its proof.

What the render asserts (``apps/command-center-v3/src/lib/watchlistFiltersCompact.view.test.mjs``), closing
cc-deepseek-5's four findings on #2609:
  R1 at phone width EVERY data-filter control, the decision-filters button, the sort select, ★/Held and Grid/Table are
     INSIDE the <details> — not a summary beside them;
  R2 each active chip renders exactly once;
  R3 the arrangement is what is asserted, so the test can fail on the defect it protects;
  R4 the width comes from a subscribed matchMedia (the render supplies the matchMedia it reads).
Desktop renders the toolbar inline. RED on the old component (the controls render outside the disclosure), GREEN here.

Hermetic: node, the committed component and its packages, a synthetic fixture. No browser, no network, no API, no data.

ANCHOR: WATCHLIST_FILTERS_COMPACT_20261104
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "apps/command-center-v3/src/lib/watchlistFiltersCompact.view.test.mjs"


def test_the_build_chain_runs_the_render_test():
    """The proof runs in the job that has `npm ci`. Since #2686 the build line names no test: `scripts/run-tests.mjs`
    discovers every runnable `*.test.*` under `src/` unless `scripts/tests.dormant.json` lists it. So the guard asserts
    the three things that make the render test run: discovery is on the build line before `tsc`, the file is a runnable
    test under `src/`, and it is not dormant."""
    assert RENDER.is_file(), f"the render test is missing: {RENDER}"
    app = ROOT / "apps/command-center-v3"
    pkg = json.loads((app / "package.json").read_text(encoding="utf-8"))
    steps = [step.strip() for step in pkg["scripts"]["build"].split("&&")]
    assert "node scripts/run-tests.mjs" in steps, "the build line no longer runs test discovery (scripts/run-tests.mjs)"
    assert "tsc" in steps and steps.index("node scripts/run-tests.mjs") < steps.index("tsc"), (
        "test discovery must run before `tsc && vite build`")
    rel = RENDER.relative_to(app).as_posix()
    assert rel.startswith("src/") and re.search(r"\.test\.(ts|mjs|cjs|js|tsx|jsx)$", rel), f"{rel} is not a runnable test"
    dormant = json.loads((app / "scripts/tests.dormant.json").read_text(encoding="utf-8")).get("files", {})
    assert rel not in dormant, (
        "the FQ-077 render test is listed as dormant — the phone layout has lost its proof; remove it from tests.dormant.json")


def test_the_gate_file_is_the_one_this_test_registers():
    """A gate whose registered file is not this one would leave the render test unrun in CI."""
    gate = ROOT / "config/ci_gates/watchlist_filters_compact_20261104.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["name"] == gate.stem, "the gate name must equal its file stem"
    assert doc["files"] == ["tests/test_watchlist_filters_compact_20261104.py"], doc["files"]
    assert "WATCHLIST_FILTERS_COMPACT_20261104" in " ".join(doc.get("comment") or [])
