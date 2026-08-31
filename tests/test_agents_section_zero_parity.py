"""The ten rules in AGENTS.md section 0 are duplicated into three adapters.

Four copies of one block is the shape that drifts. Adapters exist because no
instruction-file name is guaranteed across AI products, and an agent that reads
fifteen lines and stops must still know the rules that prevent irreversible
harm. That only holds while the copies agree.

This asserts they are byte-identical, and is mutation-tested below so it cannot
go vacuous.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "AGENTS.md"
ADAPTERS = (
    ROOT / "CLAUDE.md",
    ROOT / ".cursor" / "rules" / "00-tradeai-work-policy.mdc",
    ROOT / ".github" / "copilot-instructions.md",
)
MARKER = "## The ten rules, verbatim from `AGENTS.md` §0\n\n"


def _hub_section_zero() -> str:
    text = HUB.read_text(encoding="utf-8")
    start = text.index("# 0 · If you read nothing else")
    end = text.index("\n---\n", start)
    return text[start:end].split("\n", 1)[1].strip("\n")


def _adapter_section_zero(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert MARKER in text, f"{path.name} carries no section-0 block"
    return text.split(MARKER, 1)[1].strip("\n")


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda p: p.name)
def test_adapter_section_zero_matches_the_hub(adapter):
    assert _adapter_section_zero(adapter) == _hub_section_zero(), (
        f"{adapter.name} has drifted from AGENTS.md section 0. Regenerate it from "
        "the hub rather than editing the copy."
    )


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda p: p.name)
def test_the_guard_can_detect_drift(adapter, tmp_path):
    """Guard the guard: a mutated copy must fail the comparison."""
    mutated = _adapter_section_zero(adapter).replace("MBI_BEHAVIOR = 0", "MBI_BEHAVIOR = 1", 1)
    assert mutated != _adapter_section_zero(adapter), "mutation did not apply"
    assert mutated != _hub_section_zero()


def test_the_rail_shorthand_is_disclaimed_everywhere():
    """MBI_BEHAVIOR names nothing in code. A reader stopping at section 0 must know.

    Verified 2026-08-30: zero env reads; the rail is an unconditional raise at
    scripts/lib/cio_instrument_record.py:343.
    """
    for path in (HUB,) + ADAPTERS:
        assert "shorthand, not a variable" in path.read_text(encoding="utf-8"), path.name
