"""AGENTS.md 15.0.0 (PROPOSED, MAJOR) — §24.12 disk hygiene, the only automated deletion.

Operator directive 2026-10-18, verbatim: "i approve automatic deletion would need an AGENTS.md amendment".

What this pins (same shape as tests/test_agents_policy_14_0_0_broker_read.py):
  * one 15.0.0 history row, PROPOSED with PENDING and the §20 phrase until ratified; the header stays the last
    ACTIVE version (14.0.0) and the state checker passes on a branch and on main;
  * while PROPOSED, §0, §17 and the four §0 adapter copies are byte-identical to today and carry no `disk-hygiene`
    text; once ratified, §0 rule 6 carries exactly the proposed sentence directly after "Never delete. Archive with a
    tripwire ...", §17 carries exactly the proposed entry directly after "deleting anything ·", and each with its
    insertion removed hashes to today's digest; §2, §2A and §7A are byte-identical either way;
  * the sentence and the §17 entry quoted in §24.12 are exactly what the ratifying edit inserts, and the
    post-insertion digests are pinned here so the older pins can take them;
  * §24.12 states every obligation (scope, eligibility, never-touch list in code, operator-only rule changes, fresh
    manifest + re-validation + caps + receipt, operator-reviewed first apply, kill switch, out-of-scope data, retire
    path) and each bullet cites its cause;
  * "Never delete" still governs everything else, in AGENTS.md and every adapter.

Read-only: reads repository files. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_agents_policy_state as STATE  # noqa: E402
from tests import test_agents_policy_5_0_0_execution_ops as T5  # noqa: E402
from tests import test_agents_policy_14_0_0_broker_read as T14  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_15_0_0"
DIRECTIVE = "i approve automatic deletion would need an AGENTS.md amendment"

RULE_6 = "6. **Never delete.** Archive with a tripwire that fires if anything reads the archived path."
SENTENCE_15_0_0 = (
    "\n   One exception, binding only once AGENTS.md 15.0.0 is ACTIVE: the n8n lane `disk-hygiene` may"
    "\n   remove the reclaimable items its reviewed rules select (scripts/disk_hygiene.py,"
    "\n   config/disk_hygiene_rules.json), and nothing else (AGENTS.md §24.12)."
)
S17_ANCHOR = "deleting anything ·"
S17_ENTRY = (
    " **changing the disk-hygiene rules or never-touch list** (§24.12 — a `config-write` grant and a reviewed PR) ·"
)

#: §0 as it is on this branch and on origin/main a2aef7b4d (= the 14.0.0 ratified digest).
SECTION_0_PROPOSED_SHA256 = T14.SECTION_0_RATIFIED_SHA256
#: §0 after the ratifying edit inserts SENTENCE_15_0_0 after rule 6's first sentence.
SECTION_0_RATIFIED_SHA256 = "d10461625959d3de2f520419dbb67c1763e46d6b5905784b6aa185795ac10549"
#: §17 as it is today (pinned since 4.1.0) and after the ratifying edit inserts S17_ENTRY.
SECTION_17_PROPOSED_SHA256 = T5.UNCHANGED_SECTIONS["§17"][2]
SECTION_17_RATIFIED_SHA256 = "2eeb550129d0054a2526907cd8fc5a482caf59ab03ac97cd51a60cdea90ea238"
S17_BOUNDS = T5.UNCHANGED_SECTIONS["§17"][:2]
ADAPTERS = T5.ADAPTERS


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sec0() -> str:
    return T5._section(AGENTS, "# 0 · If you read nothing else", "# 1 · Identity and responsibilities")


def _sec17() -> str:
    return T5._section(AGENTS, *S17_BOUNDS)


def _row() -> re.Match:
    m = re.search(r"^\| 15\.0\.0 \| 2026-10-18 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 15.0.0 | 2026-10-18 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


def _ratified() -> bool:
    return _row().group(1) == "ACTIVE"


def _s2412() -> str:
    m = re.search(r"^## 24\.12 .*?(?=^## |^---$|^# |\Z)", AGENTS, re.M | re.S)
    assert m, "§24.12 missing"
    return m.group(0)


def _insert0(sec0: str) -> str:
    assert sec0.count(RULE_6) == 1
    return sec0.replace(RULE_6, RULE_6 + SENTENCE_15_0_0, 1)


def _insert17(sec17: str) -> str:
    assert sec17.count(S17_ANCHOR) == 1
    return sec17.replace(S17_ANCHOR, S17_ANCHOR + S17_ENTRY, 1)


def _quoted_blocks() -> list[str]:
    return ["\n" + "\n".join(line[2:] for line in b.split("\n")) for b in re.findall(r"\n  ```\n(.*?)\n  ```", _s2412(), re.S)]


# ------------------------------------------------------------------------------------- header, row, banner


def test_one_row_and_state_checker_passes():
    assert len(re.findall(r"^\| 15\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().group(1), _row().group(2)
    assert DIRECTIVE in rest
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 15.0.0 must not ride a prior token"
        assert re.search(r"^Policy-Version:\s+14\.0\.0$", AGENTS, re.M), "header moves only at ratification"
        assert re.search(r"^Status:\s+ACTIVE$", AGENTS, re.M)
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 15.0.0 row must record token, PR and sha"
        assert re.search(r"^Policy-Version:\s+(1[5-9]|[2-9]\d)\.\d+\.\d+$", AGENTS, re.M)


def test_banner_explains_class_number_and_scope():
    start = AGENTS.index("**15.0.0 is ")
    banner = _flat(AGENTS[start : AGENTS.index("\n\n**", start + 10)])
    for frag in ("Why MAJOR:", "weakest guarantee", "14.0.0", "12.1.0", "13.0.0", DIRECTIVE,
                 f"{TOKEN} <pr_number> <head_sha>", "`disk-hygiene`", "scripts/disk_hygiene.py",
                 "config/disk_hygiene_rules.json", "feat/disk-hygiene-n8n-20261018", "89%", "byte-identical",
                 "it is not the §20 token", "Supersedes` will be the last ACTIVE version, 14.0.0"):
        assert frag in banner, frag


# --------------------------------------------------------------------------------------- §0, §17, adapters


def test_section_0_is_unchanged_until_ratified_then_gains_exactly_one_sentence():
    sec0 = _sec0()
    if not _ratified():
        assert SENTENCE_15_0_0 not in sec0 and "disk-hygiene" not in sec0 and "§24.12" not in sec0
        assert _sha(sec0) == SECTION_0_PROPOSED_SHA256
    else:
        assert sec0.count(SENTENCE_15_0_0) == 1
        assert RULE_6 + SENTENCE_15_0_0 in sec0, "the sentence directly follows rule 6's first sentence"
        assert _sha(sec0.replace(SENTENCE_15_0_0, "")) == SECTION_0_PROPOSED_SHA256


def test_ratified_section_0_digest_is_what_the_insertion_produces():
    sec0 = _sec0()
    base = sec0.replace(SENTENCE_15_0_0, "") if _ratified() else sec0
    got = _sha(_insert0(base))
    assert got == SECTION_0_RATIFIED_SHA256, got


def test_section_17_is_unchanged_until_ratified_then_gains_exactly_one_entry():
    sec17 = _sec17()
    if not _ratified():
        assert "disk-hygiene" not in sec17
        assert _sha(sec17) == SECTION_17_PROPOSED_SHA256
    else:
        assert sec17.count(S17_ENTRY) == 1 and S17_ANCHOR + S17_ENTRY in sec17
        assert _sha(sec17.replace(S17_ENTRY, "")) == SECTION_17_PROPOSED_SHA256
    assert "deleting anything" in sec17, "§17 keeps deletion operator-only"


def test_ratified_section_17_digest_is_what_the_insertion_produces():
    sec17 = _sec17()
    base = sec17.replace(S17_ENTRY, "") if _ratified() else sec17
    got = _sha(_insert17(base))
    assert got == SECTION_17_RATIFIED_SHA256, got


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_follow_section_0(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    assert RULE_6 in text, f"{adapter} lost rule 6"
    if not _ratified():
        assert "disk-hygiene" not in text and "disk_hygiene" not in text and "§24.12" not in text, (
            f"{adapter} ahead of ratification")
    else:
        assert RULE_6 + SENTENCE_15_0_0 in text, f"{adapter} paraphrases the 15.0.0 sentence instead of repeating it"


@pytest.mark.parametrize("name", [n for n in T5.UNCHANGED_SECTIONS if n != "§17"])
def test_other_rail_sections_are_byte_identical(name):
    start, end, digest = T5.UNCHANGED_SECTIONS[name]
    assert _sha(T5._section(AGENTS, start, end)) == digest, f"{name} changed"


def test_never_delete_still_governs_everything_else():
    sec0 = _sec0()
    assert sec0.count("**Never delete.**") == 1 and RULE_6 in sec0
    f = _flat(_s2412())
    for frag in ("Data files, stores, backups, database rows, archives, logs, credentials",
                 "are never in scope", '"Never delete. Archive with a tripwire"', "No agent deletes by hand",
                 "No other deletion code is covered by analogy", "only automated deletion this file permits"):
        assert frag in f, frag


def test_proposed_text_is_quoted_verbatim_in_24_12():
    blocks = _quoted_blocks()
    assert len(blocks) == 2, "§24.12 must quote the §0 sentence and the §17 entry"
    assert blocks[0] == SENTENCE_15_0_0
    assert blocks[1] == "\n" + S17_ENTRY


# --------------------------------------------------------------------------------------------------- §24.12


def test_24_12_is_proposed_and_every_bullet_cites_a_cause():
    s = _s2412()
    head = _flat(s[:900])
    if not _ratified():
        assert "PROPOSED (MAJOR)" in head and f"{TOKEN} <pr_number> <head_sha>" in _flat(s[:400])
        assert "Binds nothing" in head and "dry run only" in head
    bullets = re.split(r"\n- ", s)[1:]
    assert len(bullets) >= 10
    assert all("*Cause (§20):" in _flat(b) for b in bullets)


@pytest.mark.parametrize(
    "frag",
    [
        # scope
        "Only `scripts/disk_hygiene.py`", "`config/disk_hygiene_rules.json`", "n8n lane `disk-hygiene`",
        "the operator runs it from the CLI", "no agent runs its apply mode outside the lane",
        # eligibility
        "working tree is clean", "no untracked files", "no commit unpushed", "merged into `origin/main`",
        "the served `CURRENT` release, a systemd unit, a crontab line", "no running process has its cwd inside it",
        "idle for more than the rule's day count", "keeping `CURRENT`, the previous release and the newest N",
        "makes the item ineligible, never eligible",
        # never-touch
        "enforced in code", "`db_backups`", "`persistent-state`", "`models`", "credential, cookie or token path",
        "`~/.ssh`", "`~/.config`", "Docker and n8n volumes", "a rule cannot widen",
        # operator-only rule changes
        "operator-approved config change", "a reviewed PR and a `config-write` grant",
        # every apply
        "fresh manifest", "never a stale manifest", "re-runs every eligibility and never-touch check",
        "per-run byte and item caps", "`LaneRunReceipt@v2`", "each removed path with its size, the rule that selected it",
        # first live apply
        "The first live apply is reviewed by the operator", "`live_arg`",
        # kill switch
        "Kill switch", "`TRADEAI_N8N_RELAY_LIVE_LANES`", "`auto_apply` to `false`",
        # gaps + retire
        "Open gaps, stated", "scripts/disk_hygiene_enforcer.py", "Retire path", "Ratifying edit",
        "`Supersedes` 14.0.0",
    ],
)
def test_24_12_states_every_obligation(frag):
    assert frag in _flat(_s2412()), frag


def test_24_12_open_gap_facts_hold():
    enforcer = (ROOT / "scripts" / "disk_hygiene_enforcer.py").read_text(encoding="utf-8")
    assert "--backups-only" in enforcer and "--releases-only" in enforcer and "rmtree" in enforcer
    assert "disk_hygiene_enforcer.py --apply" in (ROOT / "config" / "health_agent_policy.json").read_text(encoding="utf-8")
