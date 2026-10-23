"""AGENTS.md 20.1.0 (PROPOSED, MINOR) — §28.8: agent UI and validation traffic never targets the live server during
market hours.

Shipped as an OPERATOR-COMMITTED package (agents never edit AGENTS.md or its pinning tests). Operator decision
2026-10-23 ~11:05 ET, "approved", after five portfolio-server SIGKILLs (09:14–10:24 ET) driven by agent crawls and
previews (PR #2012). Built on the 20.0.0-ACTIVE AGENTS.md (PR #2013, merged; origin/main 80e93c99f).

What this pins:
  * one 20.1.0 history row, PROPOSED with PENDING and the §20 phrase until ratified; while PROPOSED the header reads
    20.1.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` 20.0.0; the state checker passes on branch and main;
  * the banner states the class, why MINOR, the byte-identical promise and the phrase;
  * §28.8 states the window, the covered tools, the fixture rule, the after-close smoke limits, and each bullet
    cites its cause;
  * MINOR means nothing else moves: with the 20.1.0 header, banner, §28.8 and row taken out (`pre_20_1_0`), AGENTS.md
    is byte-identical to the 20.0.0-ACTIVE base, before and after ratification; the four adapters are unchanged;
  * this test is registered as a CI gate (config/ci_gates/agents_policy_20_1_0_live_server_market_hours.json).

Read-only: reads repository files. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_20_1_0"
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")

#: sha256 of AGENTS.md 20.0.0 ACTIVE (origin/main 80e93c99f, PR #2013 merged)
BASE_AGENTS_SHA256 = "e0e840b3be59d76bd3552650c736915889fb492631a30f875cdebf2c9367ba20"
ADAPTER_SHA256 = {
    'CLAUDE.md': '04df92d64e45d372d31963aa006c97d6b03770f1b081c60c69a211fdbaaa8880',
    '.cursor/rules/00-tradeai-work-policy.mdc': 'b7308162f626bdb78212c18112a94061cfc1a9afa25f675cc0413edba8214f7c',
    '.github/copilot-instructions.md': '1cfaa8fba009e5a142328ecdd9d30fe3bf0cc2d4861b6c35271e4d084b902a48',
    '.goosehints': 'ad79ef5fa172d34eaafad36392734aac0d4d37d7513529bef335b7de0dbec8df',
}
#: the header block of the 20.0.0-ACTIVE base, restored by pre_20_1_0()
BASE_HEADER = {"Policy-Version": "20.0.0", "Status": "ACTIVE", "Effective-Date": "2026-10-23",
               "Last-Reviewed": "2026-10-22T23:00:00-04:00", "Supersedes": "19.0.0"}


def h(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _row() -> re.Match:
    m = re.search(r"^\| 20\.1\.0 \| 2026-10-23 \| (PROPOSED|ACTIVE)[^|]* \| MINOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 20.1.0 | 2026-10-23 | PROPOSED|ACTIVE | MINOR |` row: the 20.1.0 patch is not applied"
    return m


def _s288(text: str = AGENTS) -> str:
    m = re.search(r"^## 28\.8 .*?(?=^---$|^## |^# )", text, re.M | re.S)
    assert m, "§28.8 missing: the 20.1.0 patch is not applied"
    return m.group(0)


def pre_20_1_0(text: str) -> str:
    """AGENTS.md with the 20.1.0 header values, banner, §28.8 and row taken out: the 20.0.0-ACTIVE text."""
    if not re.search(r"^\| 20\.1\.0 \|", text, re.M):
        return text
    b = text.index("**20.1.0 is ")
    text = text[:b] + text[text.index("**20.0.0 is ACTIVE", b):]
    s = text.index("\n## 28.8 ")
    text = text[:s] + text[text.index("\n---\n\n# Version history", s):]
    text = re.sub(r"^\| 20\.1\.0 \|.*\n", "", text, count=1, flags=re.M)
    for k, v in BASE_HEADER.items():
        text = re.sub(rf"^({re.escape(k)}:\s+).*$", lambda m, v=v: m.group(1) + v, text, count=1, flags=re.M)
    return text


# ------------------------------------------------------------------------------------- header, row, banner


def test_one_row_and_state_checker_passes():
    _row()
    assert len(re.findall(r"^\| 20\.1\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert re.search(r"^Policy-Version:\s+20\.1\.0$", AGENTS, re.M)
        assert re.search(r"^Status:\s+PROPOSED$", AGENTS, re.M) and re.search(r"^Effective-Date:\s+PENDING$", AGENTS, re.M)
        assert "(20.1.0, PROPOSED)" in _s288()
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{40}}", rest), "ACTIVE 20.1.0 row must record token, PR and sha"
        assert "(20.1.0, ACTIVE)" in _s288()
    assert re.search(r"^Supersedes:\s+20\.0\.0$", AGENTS, re.M)


def test_banner_explains_class_scope_and_phrase():
    start = AGENTS.index("**20.1.0 is ")
    banner = _flat(AGENTS[start: AGENTS.index("**20.0.0 is ACTIVE", start)])
    for frag in ("(MINOR)", "§28.8", "\"approved\"", "five portfolio-server SIGKILLs", "09:14 and 10:24 ET",
                 "PR #2012", "04:00 and 16:15", "`127.0.0.1:7777`", "Why MINOR:", "adds one restriction",
                 "removes none", "Byte-identical:", "`Supersedes` 20.0.0", f"{TOKEN} <pr_number> <head_sha>"):
        assert _flat(frag) in banner, frag


# --------------------------------------------------------------------------------------------------- §28.8


def test_section_28_8_states_the_rule():
    text = _flat(_s288())
    for frag in ("04:00 to 16:15 ET on a market day", "America/New_York", "NYSE holiday", "any vendor",
                 "`127.0.0.1:7777`", "served `/api`", "Playwright", "`tools/crawl.mjs`", "`vite preview`",
                 "dev server proxying", "curl or script loops", "treats it as live", "fixtures",
                 "mock or replay backend", "after the close", "at most 1 request per second", "GET only",
                 "never POST, PUT, PATCH or DELETE", "first 5xx or timeout", "`TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1`",
                 "never set inside the window", "not the operator's own browser",
                 "tests/test_agents_policy_20_1_0_live_server_market_hours.py"):
        assert _flat(frag) in text, frag


def test_every_section_28_8_bullet_cites_its_cause():
    bullets = re.split(r"\n(?=- \*\*)", _s288())[1:]
    assert len(bullets) == 4, len(bullets)
    for b in bullets:
        assert "*Cause (§20):" in b, b[:120]
    assert "PR #2012" in bullets[0] and "2026-10-23" in bullets[0]


# ---------------------------------------------------------------------------------- MINOR: nothing else moves


def test_everything_else_is_byte_identical_to_20_0_0():
    assert h(pre_20_1_0(AGENTS)) == BASE_AGENTS_SHA256


def test_adapters_are_unchanged():
    for a in ADAPTERS:
        assert h((ROOT / a).read_text(encoding="utf-8")) == ADAPTER_SHA256[a], a


def test_registered_as_a_ci_gate():
    gate = ROOT / "config" / "ci_gates" / "agents_policy_20_1_0_live_server_market_hours.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["files"] == ["tests/test_agents_policy_20_1_0_live_server_market_hours.py"]
    assert doc["anchor"] == "AGENTS_POLICY_20_1_0_LIVE_SERVER_MARKET_HOURS"
