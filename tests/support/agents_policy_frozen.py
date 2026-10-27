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
