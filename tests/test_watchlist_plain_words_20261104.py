"""FQ-075: the watchlist row states its state in plain words, never in screaming policy codes.

Registered as the CI gate's file, so the shard runner (pytest) executes it. It does not grep the page source:
it **runs** ``apps/command-center-v3/src/lib/watchlistPlainWords.view.test.mjs``, which renders the real
``WatchlistIntelligenceBoard`` through React server rendering with a fixture payload and asserts the words the row
actually prints.

Why the change (codex P2605-R1 on #2605): the first version of this file searched the source for helper names and
map literals. Two deliberately broken copies of the component — the JSX call replaced by the raw code, and the
unknown-code fallback returning the key — left the whole suite GREEN while the page rendered ``NOT_SCHEDULED`` in
every review box. A gate that stays green when the thing it protects is removed is decoration. The render test is
RED under both mutations and GREEN on the committed component; the gate now sits on the behaviour, not on the text.

Hermetic: node, the committed component, a synthetic fixture. No browser, no network, no API, no data.

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
