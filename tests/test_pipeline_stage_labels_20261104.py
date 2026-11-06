"""FQ-032: on a phone the pipeline stage strip NAMES the current stage instead of showing unlabeled bars.

Registered as the CI gate's file so the shard runner (pytest) executes it; a `.mjs` file cannot be collected.
``apps/command-center-v3/src/lib/pipelineStageLabels.view.test.mjs`` mirrors it for a node run.

Hermetic: reads the panel source. No browser, no network, no data.

ANCHOR: PIPELINE_STAGE_LABELS_20261104
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "apps/command-center-v3/src/pages/WorkPipelinePanel.tsx").read_text(encoding="utf-8")


def _phone_block() -> str:
    match = re.search(r"@media \(max-width: (\d+)px\) \{([\s\S]*?)\n      \}", SRC)
    assert match, "no phone media query found in the panel"
    return match.group(2)


def test_the_phone_names_the_current_stage_on_its_own_line():
    # Review at 64b3abc24 measured the cells at 26-28 px on a 390 px phone while the labels need 39-54 px, so a label
    # inside the cell clipped. The words now lead on a full-width line and the strip keeps the colour.
    block = _phone_block()
    # cc-deepseek-5 review at c5a25828c: asserting only the ABSENCE of one exact selector let a plain
    # `.wp-cell-text { display: inline; }` — every label back in a 22 px bar, the original bug — pass. Assert the
    # hiding itself, which is what the operator gets.
    assert re.search(r"\.wp-cell-text \{ display: none", block), (
        "the phone does not hide the in-cell label, so every label is drawn in a 22 px bar and clips"
    )
    assert not re.search(r"\.wp-cell-text \{[^}]*display: (inline|block)", block), (
        "the phone re-shows the in-cell label in a cell too small to fit it"
    )
    assert re.search(r"\.wp-current-stage \{ display: block", block), "no full-width current-stage line on the phone"


def test_the_current_stage_line_is_phone_only():
    """cc-deepseek-3 R1 at e983b7d7: the style block set display:block only INSIDE the phone media query, which is
    the element's default — so the line also rendered at 1440 and every desktop card stated the stage twice. The
    assertion must look OUTSIDE the phone block, where the phone assertions cannot."""
    outside = re.split(r"@media \(max-width: \d+px\)", SRC)[0]
    assert re.search(r"\.wp-current-stage \{ display: none", outside), (
        "no base rule hides the current-stage line above the phone width — it renders on the desktop too"
    )


def test_cells_keep_their_label():
    # cc-deepseek-5 review at c5a25828c: `data-current` was emitted and asserted but no rule or code read it, so the
    # assertion proved a marker nothing consumed. The attribute is gone; what a cell must keep is its accessible label.
    assert re.search(r"aria-label=\{cellTitle\(c\)\}", SRC), "cells lost their accessible label"
    assert 'data-testid="wp-current-stage"' in SRC, "no full-width current-stage line in the component"
    assert "Failed at" not in SRC, (
        "the line still infers a failure from RAG colour; the producer uses red for staleness too"
    )


def test_the_stage_line_names_the_producers_record_and_never_a_colour_verdict():
    # BLOCK F2 at 9ff60477c: red is used for a stale claim as well as a CI failure, so the line must carry the
    # producer's own label and infer nothing from colour. This runs the real helper with both supported shapes.
    import shutil
    import subprocess
    node = shutil.which("node")
    assert node, "node is not on PATH: the wording behaviour cannot be verified (a skip would pass the gate)"
    test = Path(__file__).resolve().parents[1] / "apps/command-center-v3/src/lib/pipelineStageWords.test.mjs"
    assert test.is_file(), f"the wording test is missing: {test}"
    proc = subprocess.run([node, "--experimental-strip-types", str(test)], capture_output=True, text=True,
                          timeout=120, cwd=str(test.parents[3]),
                          env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"})
    assert proc.returncode == 0, f"the wording test failed:\n{proc.stdout}\n{proc.stderr}"
