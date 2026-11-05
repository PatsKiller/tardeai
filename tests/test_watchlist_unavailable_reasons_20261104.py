"""FQ-076: the four disabled filters and an unknown next-review time explain themselves in visible text.

Registered as the CI gate's file, so the shard runner (pytest) executes it. A ``.mjs`` cannot be collected, so
this test **runs** ``apps/command-center-v3/src/lib/watchlistUnavailableReasons.view.test.mjs``, which renders
the real ``WatchIntelligenceUnified`` page — the surface ``/watchlist`` redirects to — through React server
rendering with a fixture payload and asserts the words and the disabled controls it prints.

Why the rewrite (cc-deepseek-3 RECHECK BLOCK on #2606, 2026-11-05T14:35Z, F1): the first version of the render
test and this mirror both grepped the page's SOURCE for the sentence and the testid. That stays green on a page
whose condition never renders the span, or whose fallback lives in a branch the operator never reaches — the
FQ-132 class. The render test is RED under two mutations of the committed component (the reason span removed;
the next-review fallback restored to a bare dash) and GREEN on the committed component.

Hermetic: node, the committed component, a synthetic fixture. No browser, no network, no API, no data.

ANCHOR: WATCHLIST_UNAVAILABLE_REASONS_20261104
"""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "apps/command-center-v3/src/lib/watchlistUnavailableReasons.view.test.mjs"
MARKER = "FQ-076 ok:"


def test_the_rendered_page_explains_itself():
    """Render the component and assert the words it prints (a .mjs cannot be collected, so run it)."""
    assert RENDER.is_file(), f"the render test is missing: {RENDER}"
    node = shutil.which("node")
    assert node, "node is not on PATH — the render test cannot run, so the gate proves nothing"
    proc = subprocess.run(
        [node, "--experimental-strip-types", str(RENDER)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    tail = (proc.stdout + proc.stderr)[-3000:]
    assert proc.returncode == 0, f"the rendered page failed FQ-076:\n{tail}"
    assert MARKER in proc.stdout, f"the render test did not report its verdict:\n{tail}"


def test_the_gate_file_is_the_one_this_test_registers():
    """A gate whose registered file is not this one would leave the render test unrun in CI."""
    import json

    gate = ROOT / "config/ci_gates/watchlist_unavailable_reasons_20261104.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["name"] == gate.stem, "the gate name must equal its file stem"
    assert doc["files"] == ["tests/test_watchlist_unavailable_reasons_20261104.py"], doc["files"]
    assert "WATCHLIST_UNAVAILABLE_REASONS_20261104" in " ".join(doc.get("comment") or [])
