"""v1.2.3 P0-2 — semantic comparator fixture matrix: every meaning-bearing
difference the old alphanumeric hash missed must now be DETECTED."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from drive_semantic_compare import compare, semantic_hash, alnum_hash_weakness_demo

BASE = """# Title
Risk gate: value > 5% triggers review.
- item one
- item two
Gain was 1% on `A && B` logic.
```
code fence
```
See https://example.com/a and placeholder <account>.
| col1 | col2 |
| ---- | ---- |
| a | b |
Loss of -3.2% recorded.
## Section Two
text
"""


def _mut(old, new):
    assert old in BASE
    return BASE.replace(old, new)


def test_gt_vs_lt_detected():
    assert compare(BASE, _mut("value > 5%", "value < 5%")) != "SEMANTIC_PARITY"


def test_1pct_vs_10pct_detected():
    assert compare(BASE, _mut("Gain was 1%", "Gain was 10%")) != "SEMANTIC_PARITY"


def test_and_vs_or_detected():
    assert compare(BASE, _mut("`A && B`", "`A || B`")) != "SEMANTIC_PARITY"


def test_deleted_code_fence_detected():
    assert compare(BASE, BASE.replace("```\ncode fence\n```\n", "")) == "STRUCTURAL_DRIFT"


def test_reordered_sections_detected():
    # move Section Two to the TOP — same content, different order
    reordered = "## Section Two\ntext\n" + BASE.replace("## Section Two\ntext\n", "")
    r = compare(BASE, reordered)
    assert r != "SEMANTIC_PARITY"


def test_changed_link_detected():
    assert compare(BASE, _mut("https://example.com/a", "https://example.com/b")) != "SEMANTIC_PARITY"


def test_changed_table_cell_detected():
    assert compare(BASE, _mut("| a | b |", "| a | c |")) != "SEMANTIC_PARITY"


def test_removed_minus_sign_detected():
    assert compare(BASE, _mut("-3.2%", "3.2%")) != "SEMANTIC_PARITY"


def test_altered_placeholder_detected():
    assert compare(BASE, _mut("<account>", "<order>")) != "SEMANTIC_PARITY"


def test_punctuation_only_change_detected():
    assert compare(BASE, _mut("triggers review.", "triggers review?")) != "SEMANTIC_PARITY"


def test_identical_is_parity_and_hash_stable():
    assert compare(BASE, BASE) == "SEMANTIC_PARITY"
    assert semantic_hash(BASE) == semantic_hash(BASE)


def test_whitespace_only_is_parity():
    assert compare(BASE, BASE.replace("item one", "item   one")) == "SEMANTIC_PARITY"


def test_alnum_hash_weakness_demonstrated():
    demo = alnum_hash_weakness_demo()
    # at least one meaning-changing pair COLLIDES under alnum-only but is
    # detected semantically — the documented reason the old approach was dropped
    assert any(v["alnum_collides"] and v["semantic_detects"] for v in demo.values()), demo
