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


def test_the_phone_no_longer_hides_every_stage_label():
    block = _phone_block()
    assert not re.search(r"\.wp-cell-text \{ display: none; \}", block), "phone still hides every stage label"
    assert re.search(r'data-current="1"\]\s*\.wp-cell-text \{ display: inline', block), (
        "the current stage label is not shown on the phone"
    )
    assert re.search(r"\.wp-stages > div \{ height: 22px !important; \}", block), (
        "stage bars are not tall enough to carry a label"
    )


def test_the_current_stage_cell_is_marked_and_cells_keep_their_label():
    assert re.search(r'data-current=\{c\.stage === it\.stage \? "1" : undefined\}', SRC), (
        "the current stage cell is not marked"
    )
    assert re.search(r"aria-label=\{cellTitle\(c\)\}", SRC), "cells lost their accessible label"
