"""AGENTS.md 12.0.0 (ACTIVE since 2026-10-15, MAJOR) — §23.25 n8n cutover directive (operator 2026-10-15).

Pins the record: header stays 11.0.0 ACTIVE until a ratifying edit; one 12.0.0 history row; the banner and §23.25
quote the operator; F07 and registry_systemd are deferred; §0/§2/§2A/§7A/§17/§22 are named unchanged; the state
checker passes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_12_0_0"


def _section() -> str:
    start = AGENTS.index("## 23.25 ")
    end = AGENTS.index("\n---\n", start)
    return AGENTS[start:end]


def test_one_row_and_state_checker_passes():
    assert len(re.findall(r"^\| 12\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_header_waits_for_ratification():
    m = re.search(r"^\| 12\.0\.0 \| 2026-10-15 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m
    if m.group(1) == "PROPOSED":
        assert "PENDING" in m.group(2) and f"{TOKEN} <pr_number> <head_sha>" in m.group(2)


def test_banner_and_section_quote_the_directive_and_scope():
    s = " ".join(_section().split())
    assert s.startswith("## 23.25 n8n cutover directive")
    for frag in ("F07", "registry_systemd", "not accepted as a blocker", "§23.14", "§24.1",
                 "§0, §2, §2A, §7A, §17 and §22 are byte-identical", "never holds a broker credential",
                 "independent host P1 backstop", "monitoring independence"):
        assert frag in s, frag
    start = AGENTS.index("**12.0.0 is ")
    banner = " ".join(AGENTS[start:AGENTS.index("\n\n**", start + 10)].split())
    # 2026-10-15 ratifying edit: ACTIVE, the operator's verbatim token (PR #1779 comment by PatsKiller).
    for frag in ("ACTIVE (MAJOR)", "not a discussion item", "F09", "F07w", f"{TOKEN} 1779 4aeb8cf4e",
                 "PatsKiller 2026-10-15T21:12:48Z", "set the header block to 12.0.0 ACTIVE"):
        assert frag in banner, frag
