"""The policy files as they were before AGENTS.md 25.0.0, for the older AGENTS policy tests.

25.0.0 consolidated AGENTS.md (version banners moved to the appendix, the release train removed, §25.10 rewritten)
and changed §0 rules 3 and 4 in every adapter and AI_WORK_POLICY.md §28. The tests for 17.0.0–24.0.0 pin the text of
their own version; from 25.0.0 on they read these frozen copies (byte-identical to origin/main 9ac4c88b2, sha256
pinned below), and the 25.0.0 pins live in tests/test_agents_policy_25_0_0.py. Hermetic: no git, no network.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN_DIR = ROOT / "tests" / "fixtures" / "agents_pre_25_0_0"

#: repo path -> (fixture name, sha256 of the 24.0.0-era bytes)
FROZEN = {
    "AGENTS.md": ("AGENTS.md", "33a8b2e9b0f9253dc718ce96b01a0230736803f2b8feb39c18bc47ed999358c7"),
    "AI_WORK_POLICY.md": ("AI_WORK_POLICY.md", "49147afd9b26f200be4a8b4a7a522438216b43ce35c8e4230e2ee096c15ba456"),
    "CLAUDE.md": ("CLAUDE.md", "04df92d64e45d372d31963aa006c97d6b03770f1b081c60c69a211fdbaaa8880"),
    ".cursor/rules/00-tradeai-work-policy.mdc": (
        "00-tradeai-work-policy.mdc", "b7308162f626bdb78212c18112a94061cfc1a9afa25f675cc0413edba8214f7c"),
    ".github/copilot-instructions.md": (
        "copilot-instructions.md", "1cfaa8fba009e5a142328ecdd9d30fe3bf0cc2d4861b6c35271e4d084b902a48"),
    ".goosehints": ("goosehints", "ad79ef5fa172d34eaafad36392734aac0d4d37d7513529bef335b7de0dbec8df"),
}


def live_major() -> int:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    m = re.search(r"^Policy-Version:\s+(\d+)\.", text, re.M)
    return int(m.group(1)) if m else 0


def read_pre_25(rel: str | Path) -> str:
    """The file at ``rel`` as the pre-25.0.0 tests knew it: the frozen copy once the live file is 25.0.0 or later."""
    key = str(rel)
    if key in FROZEN and live_major() >= 25:
        name, digest = FROZEN[key]
        data = (FROZEN_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, f"frozen {key} changed"
        return data.decode("utf-8")
    return (ROOT / key).read_text(encoding="utf-8")


# ── 26.0.0 consolidation ─────────────────────────────────────────────────────────────────────────────────────────────
# 26.0.0 rewrote AGENTS.md to the binding rules only (history, lessons and open gaps moved to docs/governance/), changed
# §0 rules 2, 4 and 6 in every adapter, and aligned AI_WORK_POLICY.md and the governance docs with §25.10. Tests that pin
# the text of 25.x or earlier read these frozen copies once the live file is 26.0.0 or later (byte-identical to
# origin/main 274e531f5, AGENTS.md 25.0.1; sha256 pinned below). The 26.0.0 pins live in tests/test_agents_policy_26_0_0.py.
FROZEN_26_DIR = ROOT / "tests" / "fixtures" / "agents_pre_26_0_0"

FROZEN_26 = {
    "AGENTS.md": ("AGENTS.md", "ebfd707bc86eed080795332425c57b6d28fe0214e6706342d8382f2176883e2b"),
    "AI_WORK_POLICY.md": ("AI_WORK_POLICY.md", "948c4cf981ff47666326e4f91038a4447bed332a55990bd5e94fe373dfd2b0a9"),
    "CLAUDE.md": ("CLAUDE.md", "eeb593c9e930ec2d0a22e685869c62c6fbb9d419629309176ec78e559b48b22a"),
    ".cursor/rules/00-tradeai-work-policy.mdc": (
        "00-tradeai-work-policy.mdc", "1e711153b8a17f8dff5eb6c370135e9935b74b5c5398c9569a3147af9a897538"),
    ".github/copilot-instructions.md": (
        "copilot-instructions.md", "940e32031273140ceefbb1ab1e9972b08d08ebacd4dccce469f60c80cd88ae1e"),
    ".goosehints": ("goosehints", "ad137ccf744a238ea72bd0aa0a08b93477eab7ccfd1f0f3ff2aa589b62167505"),
    "docs/governance/agent-standards/AUTHORITY_AMENDMENT_1_3_0.md": (
        "AUTHORITY_AMENDMENT_1_3_0.md", "4f3b0923ca4cf6168d2861679a9c6d883a30190597129c1e102638c516881252"),
    "docs/governance/ENGINEERING_STANDARD.md": (
        "ENGINEERING_STANDARD.md", "c85f9e573a0e5e07da01f6080e8748d3dd0ef959337cfeddfb7672c674b9a83b"),
    "docs/governance/NEW_AGENT_STARTS_HERE.md": (
        "NEW_AGENT_STARTS_HERE.md", "46a6da8e23f4bba4551d628149347e9afa61d39d6b0b27369408242c615af628"),
    "docs/governance/agent-standards/AGENT_OPERATING_STANDARDS_v1.md": (
        "AGENT_OPERATING_STANDARDS_v1.md", "607b53ab566b2f89d8a7a6381ae0cd5aa640b06a9ae44a29fa7440fdafa08a89"),
}


def read_pre_26(rel: str | Path) -> str:
    """The file at ``rel`` as the 25.x tests knew it: the frozen 25.0.1 copy once the live file is 26.0.0 or later.

    Chains to ``read_pre_25`` for files 25.0.0 also froze, so a test that pins 24.0.0-era text and already calls
    ``read_pre_25`` keeps reading the 24.0.0 copy; call this one from tests that pinned 25.x text or live text that
    26.0.0 moved out.
    """
    key = str(rel)
    if key in FROZEN_26 and live_major() >= 26:
        name, digest = FROZEN_26[key]
        data = (FROZEN_26_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, f"frozen-26 {key} changed"
        return data.decode("utf-8")
    return (ROOT / key).read_text(encoding="utf-8")
