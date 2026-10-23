"""AGENTS.md 16.0.0 (ACTIVE, MAJOR) — §23.21 the n8n cutover standard; multi-day soaks removed.

Ratified 2026-10-21 by the operator (APPROVE_AGENTS_POLICY_16_0_0 1911 527a9bdc1416ab9f240a69def0523dd125afbc18,
PR #1911 comment 6331278599); the ratifying edit flipped header, banner, §23.21 and the row and replaced the five
clauses. Both states are still accepted by these pins.

Rebuilt 2026-10-21 from 8.0.0 (PR #1727, closed unratified; its test was tests/test_agents_policy_8_0_0_cutover_standard.py)
on the operator's word "yes rebuild 1727". Operator ruling 2026-10-14 ~11:05 ET, verbatim: "new standards apply when i
say so fix and dry and regression testing, yes it should run live successful to many road blocks to testing".

Same pattern as 14.0.0 and 15.0.0 (tests/test_agents_policy_15_0_0_disk_hygiene.py), on the 15.0.0 ACTIVE base
(origin/main 4104effb9): the operator-applied patch adds a banner, §23.21 and a PENDING row and sets the header block to
16.0.0 PROPOSED; the clauses it replaces stay byte-identical until the ratifying edit, and the exact replacement text is
quoted in §23.21 and pinned here by SHA-256. Pins, all hermetic (source text only):

* the record: one 16.0.0 row, PROPOSED with PENDING and the §20 phrase until ratified; while PROPOSED the header block
  reads 16.0.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` 15.0.0 (or a later PROPOSED version stacked on it,
  e.g. 17.0.0); the state checker passes on a branch and on main;
* §23.21: the four criteria, where the live run comes from (dispatcher slot or operator-forced in window, never an
  agent-forced F09 run), the cutover factory and comment-not-delete fallback, removed soaks, waivers, unchanged rails;
* the five replacements: before ratification each OLD clause is on main exactly once and its NEW text is absent;
  after, the reverse; each NEW text is quoted verbatim in §23.21 with its digest, and the post-edit §23.14 and §23.23
  digests are computed here so the older pins can take them;
* §0, §2, §2A, §7A, §17, §22 and the four adapters carry nothing from 16.0.0;
* main's dependents (§23.23, §23.25, scripts/n8n_cutover_wave.py) cite the §23.21 this adds.

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
from tests import test_agents_policy_11_0_0_workflow_framework as T11  # noqa: E402
from tests.test_agents_policy_5_2_0_validation import SECTION_23_14_SHA256  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
# AGENTS.md 20.0.0 (§28.7): once 20.0.0 is ACTIVE its eight clause edits are undone before the pins below are
# checked (and before any 19.0.0 undo); tests/test_agents_policy_20_0_0_agent_operations.py pins those edits and
# the post-ratification digests. While 20.0.0 is PROPOSED the text is unchanged.
from tests.test_agents_policy_20_0_0_agent_operations import pre_20_0_0  # noqa: E402

AGENTS = pre_20_0_0(AGENTS)
# AGENTS.md 19.0.0 (§27.5): once 19.0.0 is ACTIVE its four clause edits in §17, §23.14 and §25.4 are undone before
# the pins below are checked; tests/test_agents_policy_19_0_0_broker_read_controls.py pins those edits and the
# post-ratification digests. While 19.0.0 is PROPOSED the text is unchanged.
from tests.test_agents_policy_19_0_0_broker_read_controls import pre_19_0_0  # noqa: E402

AGENTS = pre_19_0_0(AGENTS)
TOKEN = "APPROVE_AGENTS_POLICY_16_0_0"
REBUILD_WORD = "yes rebuild 1727"
OPERATOR_WORDS = (
    "new standards apply when i say so fix and dry and regression testing, yes it should run live successful to many "
    "road blocks to testing"
)

#: (section, OLD clause on main today, NEW clause the ratifying edit writes, sha256(NEW)).
REPLACEMENTS = [
    (
        "23.3",
        "  (grant naming the workflow id). The cron line stays live as the fallback until n8n has 3 market days\n"
        "  of `RUN_DONE` with no `trade-ai-scalp-live:STALLED` finding; it is then retired as",
        "  (grant naming the workflow id). The cron line stays live as the fallback until the lane meets the\n"
        "  §23.21 cutover standard (16.0.0): one successful in-window `live` n8n run with the cron line present\n"
        "  under that lock; it is then retired as",
        "82e4012f9e6a2d6728e8a6456e15743e92647905c4f904806a21ce29bf435ff1",
    ),
    (
        "23.14",
        "  fires it, and the cron line live as the fallback until 3 clean market days. The test checks those",
        "  fires it, and the cron line live as the fallback until the §23.21 cutover standard (16.0.0) is met. The\n"
        "  test checks those",
        "c2738d78d2b3580857cf54a9682d6140223d85b4d347b0018d791cc0dd97a961",
    ),
    (
        "8.1",
        "natural-schedule evidence**, which keeps its condition: the lane-specific shadow fire on the natural schedule\n"
        "(`N8N_ONBOARDING_STANDARD.md` step 8), natural-schedule evidence after a cutover (§23.12, last bullet), a\n"
        "registry `PAUSED` row's flip to `ACTIVE` after its natural-slot verification, `trade-ai-scalp-live`'s three\n"
        "clean market days with cron as fallback (§23.3), and the maturity proofs (§15).",
        "natural-schedule evidence**, which keeps its condition: natural-schedule evidence after a cutover (§23.12, last\n"
        "bullet), a registry `PAUSED` row's flip to `ACTIVE` after its natural-slot verification, and the maturity proofs\n"
        "(§15). An n8n cutover is the exception: its readiness is the §23.21 cutover standard (16.0.0), which needs no\n"
        "natural shadow slot and no run of clean days.",
        "20fd2f9c80fa13b331b09152658bb73c854987fdbd5b7435457725b2b8ee283a",
    ),
    (
        "23.12",
        "- **Cutover is per wave, under one `cron` grant whose reason names every lane id in the wave.**\n",
        "- **Cutover is per wave, under one `cron` grant whose reason names every lane id in the wave.** A lane joins\n"
        "  the cutover when it meets the §23.21 cutover standard (16.0.0); no soak precedes it.\n",
        "05cb9d12012d6348a47500ca9d872ddefe5e9842b909300930b3225302831ec5",
    ),
    (
        "23.23",
        "  folded on the host first, then moved as one process. (4) A cutover keeps the §23.21 cutover standard (8.0.0, PR\n"
        "  #1727; until it is ACTIVE, the cutover rules then in force) plus a fenced single-owner switch: one recorded act",
        "  folded on the host first, then moved as one process. (4) A cutover keeps the §23.21 cutover standard (16.0.0,\n"
        "  rebuilt from PR #1727) plus a fenced single-owner switch: one recorded act",
        "baccf84bff2129f0f112b9dd979bb12658e08a8ce898d62c4578937a57721681",
    ),
]
#: §23.14 (block as the 4.x/5.x pins cut it) after the ratifying edit's replacement (2). The older pins reverse
#: CLAUSE_23_14_16_0_0 -> CLAUSE_23_14_PRE_16_0_0 before hashing to keep SECTION_23_14_SHA256.
CLAUSE_23_14_PRE_16_0_0, CLAUSE_23_14_16_0_0 = REPLACEMENTS[1][1], REPLACEMENTS[1][2]
SECTION_23_14_16_0_0_SHA256 = "891c55a5be08630952c61300f95bcb5442f1ef6b37fb5cb5018e72f843a9043f"
#: §23.23 (T10._sub23("23.23").rstrip(), as the 11.0.0 pin cuts it) after replacement (5).
SECTION_23_23_16_0_0_SHA256 = "5ef9f1ddfdab293144f58dbcbf3d9ae0a7d8dbdc4ed11d21e2e53faf39273cfa"

ADAPTERS = T5.ADAPTERS


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _row() -> re.Match:
    m = re.search(r"^\| 16\.0\.0 \| 2026-10-21 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 16.0.0 | 2026-10-21 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


def _ratified() -> bool:
    return _row().group(1) == "ACTIVE"


def _sub23(num: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S)
    assert sec
    m = re.search(rf"^## {re.escape(num)} .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m, num
    return m.group(0)


def _scope(num: str) -> str:
    if num == "8.1":
        return AGENTS[AGENTS.index("## 8.1 Working means validated now") : AGENTS.index("# 8A · Testing standards")]
    return _sub23(num)


def _s2321() -> str:
    return _sub23("23.21")


def _quoted_blocks() -> list[str]:
    return ["\n".join(line[2:] for line in b.split("\n")) for b in re.findall(r"\n  ```\n(.*?)\n  ```", _s2321(), re.S)]


def _block_23_14(text: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", text, re.M | re.S)
    m = re.search(r"^## 23\.14 .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    return m.group(0).rstrip("\n").rstrip("-").rstrip("\n")


def _block_23_23(text: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", text, re.M | re.S)
    m = re.search(r"^## 23\.23 .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    return m.group(0).rstrip()


# ------------------------------------------------------------------------------------------ the record


def test_one_row_and_state_checker_passes():
    assert len(re.findall(r"^\| 16\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().groups()
    for frag in (
        OPERATOR_WORDS,
        REBUILD_WORD,
        "§23.21",
        "PR #1727",
        "tests/test_agents_policy_16_0_0_cutover_standard.py",
        "`OPERATOR_FORCED_LIVE`",
        "scripts/n8n_cutover_wave.py",
        "§0, §2, §2A, §7A, §17, §22 and the adapters",
    ):
        assert frag in rest, frag
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 16.0.0 must not ride a prior token"
        version = tuple(int(x) for x in _control("Policy-Version").split("."))
        assert version >= (16, 0, 0), "a PROPOSED 16.0.0 sets the header block to 16.0.0 PROPOSED"
        assert _control("Status") == "PROPOSED" and _control("Effective-Date") == "PENDING"
        if version == (16, 0, 0):
            assert _control("Supersedes") == "15.0.0", "Supersedes is the last ACTIVE version, 15.0.0"
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 16.0.0 row must record token, PR and sha"
        assert re.search(r"^Policy-Version:\s+(1[6-9]|[2-9]\d)\.\d+\.\d+$", AGENTS, re.M)


def test_banner_explains_class_number_pattern_and_dependents():
    start = AGENTS.index("**16.0.0 is ")
    banner = _flat(AGENTS[start : AGENTS.index("\n\n**", start + 10)])
    for frag in (
        OPERATOR_WORDS,
        REBUILD_WORD,
        "Why MAJOR:",
        "weakest guarantee",
        "It grants nothing",
        "§23.14 changes by one clause at ratification",
        "2026-10-12T23:59:59-04:00",
        "PR #1727, closed unratified",
        "PR #1852",
        "§23.23 (4) and §23.25",
        "scripts/n8n_cutover_wave.py",
        "byte-identical",
        f"{TOKEN} <pr_number> <head_sha>",
    ):
        assert frag in banner, frag
    if _ratified():
        # Ratified 2026-10-21 (APPROVE_AGENTS_POLICY_16_0_0 1911 527a9bdc1, PR #1911 comment 6331278599).
        assert "ACTIVE (MAJOR)" in banner and "set the header block to 16.0.0 PROPOSED" in banner
        assert "`Supersedes` is the last ACTIVE version, 15.0.0" in banner
        assert re.search(rf"{TOKEN} 1911 [0-9a-f]{{7,40}}", banner) and "6331278599" in banner
    else:
        assert "PROPOSED (MAJOR)" in banner and "sets the header block to 16.0.0 PROPOSED" in banner
        assert "`Supersedes` will be the last ACTIVE version, 15.0.0" in banner


# ------------------------------------------------------------------------------------------------- §23.21


def test_23_21_is_proposed_until_ratified_and_every_bullet_cites_a_cause():
    s = _s2321()
    head = _flat(s[:700])
    assert s.startswith("## 23.21 The cutover standard — fixed, dry run, regression tests, one live run (16.0.0, ")
    if not _ratified():
        assert "PROPOSED (MAJOR)" in head and f"{TOKEN} <pr_number> <head_sha>" in head and "Binds nothing" in head
    bullets = re.split(r"\n- ", s)[1:]
    assert len(bullets) >= 8
    assert all("*Cause (§20):" in _flat(b) for b in bullets)


@pytest.mark.parametrize(
    "frag",
    [
        OPERATOR_WORDS,
        # the four criteria
        "(1) **Defect fixed.**",
        "merged and served from CURRENT",
        "(2) **n8n dry run passes.**",
        "A forced `dry_run` fire through `coordination/run` counts (§8.1); no natural shadow slot",
        "(3) **Lane regression tests pass** under `TRADE_AI_CI=1`",
        "(4) **At least one successful `live` n8n run with the cron line still present under the shared lock.**",
        "the allowlist lock equal to the cron line's lock",
        "A `RUN_SKIPPED_LOCK` is not this run",
        # where the live run comes from
        "the dispatcher's next slot",
        "`run_key_namespace_refused`",
        "A live fire the operator forces also counts",
        "never with the gate overridden",
        "`OPERATOR_FORCED_LIVE`",
        "`window_gate_overridden` false",
        "An agent never forces a live run of an F09",
        "(§23.25)",
        # the factory and the fallback
        "`scripts/n8n_cutover_wave.py`",
        "`comment-cron`",
        "`CRON_PRESENT_WHILE_SCHEDULER_N8N`",
        "`CUTOVER_CRON_LINE_ACTIVE`",
        "`# RETIRED <date> n8n-cutover <lane> <original line>`",
        "never deletes it (§0 rule 6)",
        "that commented line is the fallback",
        "comment out whats working now this can be a fallback",
        # soaks and waivers
        "No multi-day soak is a cutover condition.",
        "3 market days of `RUN_DONE` with no `trade-ai-scalp-live:STALLED` finding",
        "step 8",
        "N clean days",
        "`canary.operator_waiver`",
        "push live now",
        "A waiver never covers (1), (3), the shared lock or comment-not-delete",
        # unchanged rails
        "broker, order, secret and daemon lanes are never dispatcher-eligible",
        "One `cron` grant per wave",
        "rollback per line",
        "monitored, not awaited",
        # class, gaps, ratification
        "the program window ended 2026-10-12T23:59:59-04:00",
        "Open gaps, stated",
        "Ratifying edit",
        "§0, §17 and the adapters do not change",
    ],
)
def test_23_21_states_every_obligation(frag):
    assert frag in _flat(_s2321()), frag


# ----------------------------------------------------------------------------------- the five replacements


def test_replacements_are_quoted_verbatim_with_their_digests():
    blocks = _quoted_blocks()
    assert len(blocks) == len(REPLACEMENTS), "§23.21 must quote each replacement clause once"
    flat = _flat(_s2321())
    for block, (name, _old, new, digest) in zip(blocks, REPLACEMENTS):
        assert block == new.rstrip("\n"), name
        assert _sha(new) == digest, (name, _sha(new))
        assert f"sha256 `{digest}`" in flat, name


@pytest.mark.parametrize("name,old,new,digest", REPLACEMENTS, ids=[r[0] for r in REPLACEMENTS])
def test_each_clause_is_unchanged_until_ratified_then_replaced(name, old, new, digest):
    scope = _scope(name)
    if not _ratified():
        assert scope.count(old) == 1, f"{name}: the clause the ratifying edit replaces is not on main once"
        assert new not in AGENTS, f"{name}: replacement text ahead of ratification"
    else:
        assert scope.count(new) == 1 and old not in scope, name


def test_post_edit_section_23_14_digest_and_reversibility():
    block = _block_23_14(AGENTS)
    if not _ratified():
        assert _sha(block) == SECTION_23_14_SHA256, "§23.14 must stay byte-identical while 16.0.0 is PROPOSED"
        edited = block.replace(CLAUSE_23_14_PRE_16_0_0, CLAUSE_23_14_16_0_0)
    else:
        edited = block
    assert edited.count(CLAUSE_23_14_16_0_0) == 1
    assert _sha(edited) == SECTION_23_14_16_0_0_SHA256, _sha(edited)
    assert _sha(edited.replace(CLAUSE_23_14_16_0_0, CLAUSE_23_14_PRE_16_0_0)) == SECTION_23_14_SHA256
    f = _flat(edited)
    for frag in (
        "**Broker, order, secret and daemon lanes are never dispatcher-eligible.**",
        "No other ingest writer or sender becomes dispatcher-eligible by analogy",
        "No amendment made inside a program window can change this; it needs a new MAJOR.",
    ):
        assert frag in f, frag


def test_post_edit_section_23_23_digest():
    _name, old, new, _d = REPLACEMENTS[4]
    block = _block_23_23(AGENTS)
    if not _ratified():
        assert _sha(block) == T11.SECTION_23_23_PRE_16_0_0_SHA256, "§23.23 must stay byte-identical while 16.0.0 is PROPOSED"
        block = block.replace(old, new)
    assert _sha(block) == SECTION_23_23_16_0_0_SHA256, _sha(block)


# ------------------------------------------------------------------------------- rails, adapters, dependents


@pytest.mark.parametrize("name", list(T5.UNCHANGED_SECTIONS))
def test_rail_sections_are_byte_identical(name):
    start, end, digest = T5.UNCHANGED_SECTIONS[name]
    sec = T5._section(AGENTS, start, end).replace(T5.S17_ENTRY_15_0_0, "")  # 15.0.0's §17 entry, pinned by its test
    assert _sha(sec) == digest, f"{name} changed"
    assert "16.0.0" not in sec and "§23.21" not in sec, name


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_carry_nothing_from_16_0_0(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    assert "16.0.0" not in text and "§23.21" not in text and "OPERATOR_FORCED_LIVE" not in text, adapter


def test_main_dependents_cite_the_standard_this_adds():
    assert "§23.21 cutover standard" in _flat(_sub23("23.23"))
    assert "§23.21 cutover standard" in _flat(_sub23("23.25"))
    wave = (ROOT / "scripts" / "n8n_cutover_wave.py").read_text(encoding="utf-8")
    assert "AGENTS.md §23.21 cutover standard" in _flat(wave) and "No soaks" in wave


def test_checklist_carries_the_forced_live_evidence_class():
    from scripts import n8n_cutover_checklist as cl

    assert "OPERATOR_FORCED_LIVE" in cl.EVIDENCE_CLASSES and "OPERATOR_FORCED_LIVE" in cl.CANARY_CLASSES
