"""docs/ops/OPERATING_PLAYBOOK.md: the versioned single source of the handoff's Section A and B0 (operator 2026-10-23:
"also add that the above should be part of the board"). Pins the section headings the B0 extractor and the Work
pipeline's Playbook anchors read, the AGENTS.md §14 header, and that no secret-looking value is in it. Hermetic."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import handoff_playbook as HP  # noqa: E402

DOC = ROOT / HP.PLAYBOOK_REL
TEXT = DOC.read_text(encoding="utf-8")


def test_header_block_per_agents_section_14():
    head = TEXT.split("```", 2)[1]
    for key in ("Status:", "as_of:", "Measured at:"):
        assert key in head


def test_section_headings_are_pinned_in_order():
    heads = [ln for ln in TEXT.split("\n") if ln.startswith("## ")]
    assert heads == list(HP.REQUIRED_HEADINGS)
    tops = [ln for ln in TEXT.split("\n") if ln.startswith("# ")]
    assert tops == [
        "# Operating playbook — how any agent or the operator picks up Trade AI work",
        "# Section A: how the system works and the rules",
        "# Section B0: the standard agent preamble",
    ]


def test_b0_preamble_is_extracted_with_the_rules():
    pb = HP.load_playbook()
    assert pb["ok"] and pb["path"] == HP.PLAYBOOK_REL and len(pb["sha256"]) == 64
    pre = pb["b0_preamble"]
    assert pre.startswith("You are a coding agent working on Trade AI")
    for must in ("Read `AGENTS.md` §0 and §28.3a.", "Never `pkill -f`.", "**Pushes:** at most 2 per branch",
                 "Never route around a denial"):  # fmt: skip
        assert must in pre
    assert not any(ln.startswith(">") for ln in pre.split("\n"))
    ids = [s["id"] for s in pb["sections"]]
    assert "a1-resume-procedure-any-agent-every-time" in ids and "a3-rules-never-skip" in ids


def test_full_prompt_prepends_the_preamble_once():
    pre = HP.load_playbook()["b0_preamble"]
    assert HP.full_prompt("Do X.", pre) == f"{pre}\n\n---\n\nDo X."
    assert HP.full_prompt(None, pre) is None and HP.full_prompt("Do X.", None) == "Do X."


def test_load_playbook_never_raises_and_caches(tmp_path):
    assert HP.load_playbook(tmp_path / "missing.md")["error"] == "playbook_missing"
    p = tmp_path / "pb.md"
    p.write_text("# T\n\n## B0. x\n\n> rule one\n> rule two\n\nafter\n", encoding="utf-8")
    a = HP.load_playbook(p)
    assert a["b0_preamble"] == "rule one\nrule two" and HP.load_playbook(p) is a
    big = tmp_path / "big.md"
    big.write_bytes(b"x" * (HP.MAX_PLAYBOOK_BYTES + 1))
    assert HP.load_playbook(big)["error"] == "playbook_too_large"


def test_no_secret_values():
    for pat in (r"(?i)password\s*[:=]\s*\S", r"gh[pousr]_[A-Za-z0-9]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY",
                r"(?i)api[_-]?key\s*[:=]\s*\S", r"sk-[A-Za-z0-9]{20,}"):  # fmt: skip
        assert not re.search(pat, TEXT), pat
