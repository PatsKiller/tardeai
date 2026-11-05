"""FQ-077: at phone width the whole filter toolbar is inside the disclosure; nothing renders twice.

Registered as the CI gate's file, so the shard runner (pytest) executes it. A ``.mjs`` cannot be collected, so this
test **runs** ``apps/command-center-v3/src/lib/watchlistFiltersCompact.view.test.mjs``, which renders the real
``WatchIntelligenceUnified`` page at both widths through React server rendering and asserts what it prints.

Why the rewrite (cc-deepseek-5's whole-head BLOCK on #2609, 2026-11-05T13:08Z): the first version of the render test
and this mirror both grepped the page source, and one of them REQUIRED the arrangement that caused the defect
(R3). The block's four findings:
  R1  the disclosure was a sibling of the toolbar — a phone got one extra line and then the same wall of controls;
  R2  the chips rendered twice once it opened;
  R3  no assertion could see containment, so no arrangement of the page could fail the suite;
  R4  `matchMedia(...).matches` was read once during render and never updated.
All four are now held by rendered assertions and a subscribed hook: the controls must be INSIDE the disclosure at
phone width, inline at desktop, each chip exactly once at both.

Hermetic: node, the committed component, a synthetic fixture. No browser, no network, no API, no data.

ANCHOR: WATCHLIST_FILTERS_COMPACT_20261104
"""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "apps/command-center-v3/src/lib/watchlistFiltersCompact.view.test.mjs"
MARKER = "FQ-077 ok:"


def test_the_rendered_page_collapses_the_toolbar_and_nothing_twice():
    """Render the component at both widths and assert the arrangement (a .mjs cannot be collected, so run it)."""
    assert RENDER.is_file(), f"the render test is missing: {RENDER}"
    node = shutil.which("node")
    assert node, "node is not on PATH — the render test cannot run, so the gate proves nothing"
    proc = subprocess.run(
        [node, "--experimental-strip-types", str(RENDER)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    tail = (proc.stdout + proc.stderr)[-3000:]
    assert proc.returncode == 0, f"the rendered page failed FQ-077:\n{tail}"
    assert MARKER in proc.stdout, f"the render test did not report its verdict:\n{tail}"


def test_the_gate_file_is_the_one_this_test_registers():
    """A gate whose registered file is not this one would leave the render test unrun in CI."""
    import json

    gate = ROOT / "config/ci_gates/watchlist_filters_compact_20261104.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["name"] == gate.stem, "the gate name must equal its file stem"
    assert doc["files"] == ["tests/test_watchlist_filters_compact_20261104.py"], doc["files"]
    assert "WATCHLIST_FILTERS_COMPACT_20261104" in " ".join(doc.get("comment") or [])
