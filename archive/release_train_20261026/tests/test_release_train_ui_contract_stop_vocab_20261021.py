"""Release train arming finding 10 (ANCHOR RELEASE_TRAIN_UI_CONTRACT_STOP_VOCAB_20261021): the UI contract's item 5
names the STOP vocabulary the code serves (ABSENT / SET / UNREADABLE), not the retired CLEAR / LATCHED.

Hermetic: reads committed files only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import release_train_view as V  # noqa: E402

DOC = ROOT / "docs/ops/RELEASE_TRAIN_UI_CONTRACT.md"


def _item5() -> str:
    text = DOC.read_text(encoding="utf-8")
    m = re.search(r"^5\. \*\*Two STOP reads.*?(?=^6\. )", text, re.S | re.M)
    assert m, "item 5 missing"
    return m.group(0)


def test_item_5_uses_the_served_vocabulary():
    item = _item5()
    for s in V.LATCH_STATES:
        assert f"`{s}`" in item
    assert V.LATCH_STATES == ("ABSENT", "SET", "UNREADABLE")
    assert "`summary.stop` (`CLEAR`" not in item and "replaced" in item


def test_no_live_reference_to_the_old_summary_vocabulary():
    text = DOC.read_text(encoding="utf-8")
    assert "summary.stop` (`CLEAR` / `LATCHED`" not in text


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_ui_contract_stop_vocab_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_UI_CONTRACT_STOP_VOCAB_20261021"
    assert "tests/test_release_train_ui_contract_stop_vocab_20261021.py" in doc["files"]
