"""FQ-075, retirement half: the shadow watchlist board stays unmounted and both the route and the file say so.

Registered as the CI gate's file, so the shard runner (pytest) executes it. A ``.mjs`` cannot be collected, so this
test **runs** ``apps/command-center-v3/src/lib/watchlistPlainWords.view.test.mjs``, which scans the tree for importers
of ``WatchlistIntelligenceBoard`` and reads the route and the file's own header.

The plain-words half of this PR moved: the same wording landed on the live surface in FQ-078 (PR 2611,
cc-deepseek-4) — the component that actually renders ``/watchlist`` — so this gate no longer asserts it. Asserting it in
two places would duplicate that PR's gate and fail on any head that does not carry it. What remains here has no other
owner: cc-deepseek-3's original finding was that the fix had landed in a file no route renders, and a comment alone
does not stop that recurring — this gate does.

Hermetic: node, the committed sources. No browser, no network, no API, no data.

ANCHOR: WATCHLIST_PLAIN_WORDS_20261104
"""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "apps/command-center-v3/src/lib/watchlistPlainWords.view.test.mjs"
MARKER = "FQ-075 ok:"


def test_the_rendered_row_speaks_plain_words():
    """Render the component and assert the words it prints (a .mjs cannot be collected, so run it)."""
    assert RENDER.is_file(), f"the render test is missing: {RENDER}"
    node = shutil.which("node")
    assert node, "node is not on PATH — the render test cannot run, so the gate proves nothing"
    proc = subprocess.run(
        [node, "--experimental-strip-types", str(RENDER)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    tail = (proc.stdout + proc.stderr)[-3000:]
    assert proc.returncode == 0, f"the rendered row failed FQ-075:\n{tail}"
    assert MARKER in proc.stdout, f"the render test did not report its verdict:\n{tail}"


def test_the_gate_file_is_the_one_this_test_registers():
    """A gate whose registered file is not this one would leave the render test unrun in CI."""
    import json

    gate = ROOT / "config/ci_gates/watchlist_plain_words_20261104.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["name"] == gate.stem, "the gate name must equal its file stem"
    assert doc["files"] == ["tests/test_watchlist_plain_words_20261104.py"], doc["files"]
    assert "WATCHLIST_PLAIN_WORDS_20261104" in " ".join(doc.get("comment") or [])
