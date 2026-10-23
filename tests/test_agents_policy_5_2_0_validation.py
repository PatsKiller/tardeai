"""AGENTS.md 5.2.0 (PROPOSED, MINOR) — §8.1: "working" means validated now; natural schedules are monitored, never awaited.

Cause: 2026-10-10/11, the C1 stage-runner manifest flips — the proof of flip 1 was deferred to its 10:50 ET natural
fire, flip 2 waited on it, and the grant expired first. Operator 2026-10-11 ~09:22 ET: "When a agent is developing and
building something out, it should do dry test and unit test and validate before it's deemed as working, and then the
natural schedules can run, but we do not wait for natural schedules."

What this pins:
  * the header and the version row stay PROPOSED / PENDING with the §20 approval phrase until ratified, and the
    banner states the class and the reasoning;
  * the rails do not move: §0 (with the 5.0.0 rule 2 sentence), §2, §2A, §7A (generated table masked), §17 and
    §23.14 hash to the digests the 4.6.0 / 5.0.0 / 5.1.0 pins hold, and the adapters carry nothing from 5.2.0;
  * §8.1 says what the operator asked: tests, dry run, forced run under the schedule's exact form, proven by a durable
    artifact dated after the trigger; natural fires monitored and never awaited; the four forced-run exceptions;
    grant, overlap and change-record bounds; no existing natural-evidence gate lifted;
  * the one-line pointers in §6, §8, §9.3, §16, §23.12 and §23.19, and the onboarding standard's restatement.

All tests are read-only. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_agents_policy_state as STATE  # noqa: E402

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
ONBOARDING = (ROOT / "docs" / "implementation" / "n8n-maturity" / "N8N_ONBOARDING_STANDARD.md").read_text(
    encoding="utf-8"
)
TOKEN = "APPROVE_AGENTS_POLICY_5_2_0"

# Same digests as tests/test_agents_policy_5_1_0_notification_intents.py (5.0.0 ACTIVE, 5.1.0 merged at 26cf80f60).
# AGENTS.md 14.0.0 ratified 2026-10-16: §0 rule 2 gained one sentence (pinned in
# tests/test_agents_policy_14_0_0_broker_read.py); before it, §0 hashed to d7ce297890a8….
# AGENTS.md 15.0.0 ratified 2026-10-21: §0 rule 6 gained one sentence and §17 one entry (pinned in
# tests/test_agents_policy_15_0_0_disk_hygiene.py); before it, §0 hashed to 86ab4957123f… and §17 to f61b30d24833….
SECTION_0_SHA256 = "d10461625959d3de2f520419dbb67c1763e46d6b5905784b6aa185795ac10549"
SECTION_23_14_SHA256 = "bb8722f69b8e54a8582011bdbe266d55ea7c2c0c6b120d123a1d4e43394311e7"
# AGENTS.md 16.0.0 (ACTIVE 2026-10-21, ratified APPROVE_AGENTS_POLICY_16_0_0 1911 527a9bdc1, PR #1911 comment
# 6331278599): the ratifying edit replaced one §23.14 clause (§23.21 replacement (2)). Reversed before hashing so
# SECTION_23_14_SHA256 keeps pinning the rest of §23.14; the post-edit digest is pinned by
# tests/test_agents_policy_16_0_0_cutover_standard.py.
CLAUSE_23_14_PRE_16_0_0 = "  fires it, and the cron line live as the fallback until 3 clean market days. The test checks those"
CLAUSE_23_14_16_0_0 = (
    "  fires it, and the cron line live as the fallback until the §23.21 cutover standard (16.0.0) is met. The\n"
    "  test checks those"
)
PINNED_SECTIONS = {
    "§0": ("# 0 · If you read nothing else", "# 1 · Identity and responsibilities", SECTION_0_SHA256),
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"),
    "§17": (
        "# 17 · Operator-only decisions",
        "# 17A ·",
        "2eeb550129d0054a2526907cd8fc5a482caf59ab03ac97cd51a60cdea90ea238",
    ),
}
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _version() -> tuple[int, ...]:
    return tuple(int(x) for x in _control("Policy-Version").split("."))


# AGENTS.md 17.0.0 (ACTIVE 2026-10-21, ratified APPROVE_AGENTS_POLICY_17_0_0 1914 aeb5e6fd7, PR #1914 comment
# 6331877455): §17 gained this one paragraph (§25.9 clause (1)). Stripped before hashing so the §17 digest keeps
# pinning the rest of §17; the paragraph and its SHA-256 are pinned by tests/test_agents_policy_17_0_0_release_train.py.
S17_ENTRY_17_0_0 = (
    "**Release train (17.0.0, §25):** arming, re-arming or revoking the standing release delegation, and\n"
    "creating or editing its host record · clearing a release STOP or resuming the release train · expanding the\n"
    "train's scope: a permitted class, an enabled window, a limit, a named service or the verification policy\n"
    "(narrowing it is the same act and the same proof) · custody of the release-train GitHub App: creating,\n"
    "installing, re-permissioning or suspending it, and placing, rotating or revoking its private key. Each is done\n"
    "by the operator at the host CLI (`scripts/release_control_cli.py`) or by a Telegram button confirmation\n"
    "(decision D3, 2026-10-21); an agent or the Command Center may only request STOP or pause.\n"
    "\n"
)


def _section(text: str, start: str, end: str) -> str:
    s = re.search(rf"^{re.escape(start)}", text, re.M)
    assert s, start
    e = re.search(rf"^{re.escape(end)}", text[s.start() + 1 :], re.M)
    assert e, end
    block = text[s.start() : s.start() + 1 + e.start()]
    block = block.replace(S17_ENTRY_17_0_0, "")  # 17.0.0's §17 paragraph; see the constant
    # Same §7A generated-table mask as the 4.1.0 … 5.1.0 pins (PR #1678).
    return re.sub(
        r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)",
        r"\1\n<generated>\n\2",
        block,
        flags=re.S,
    )


def _sub(start_re: str, end_re: str) -> str:
    m = re.search(rf"^{start_re}.*?(?=^{end_re})", AGENTS, re.M | re.S)
    assert m, start_re
    return _flat(m.group(0))


def _s81() -> str:
    return _sub(r"## 8\.1 ", r"## Verification traps specific to this system")


def _row() -> re.Match:
    m = re.search(r"^\| 5\.2\.0 \| 2026-10-11 \| (PROPOSED|ACTIVE)[^|]* \| MINOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 5.2.0 | 2026-10-11 | PROPOSED|ACTIVE | MINOR |` version row"
    return m


def _banner() -> str:
    start = AGENTS.index("**5.2.0 is ")
    return _flat(AGENTS[start : AGENTS.index("**4.5.0 is ACTIVE", start)])


# ---------------------------------------------------------------------------------------- header, row, banner


def test_header_is_5_2_0_proposed_or_later():
    assert _version() >= (5, 2, 0)
    if _version() == (5, 2, 0):
        assert _control("Supersedes") == "5.1.0"
        if _control("Status") == "PROPOSED":
            assert _control("Effective-Date") == "PENDING"
            assert "5.2.0 is PROPOSED (MINOR)" in _flat(AGENTS[:30000])


def test_version_row_is_minor_and_waits_for_the_operator_with_the_exact_phrase():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 5.2.0 must not claim a prior token"
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 5.2.0 row must record token, PR and sha"
    for frag in ("§8.1", "tests/test_agents_policy_5_2_0_validation.py", "6.0.0", "N8N_ONBOARDING_STANDARD.md"):
        assert frag in rest, frag


def test_banner_states_the_class_and_why_it_widens_nothing():
    f = _banner()
    for frag in (
        "Why MINOR",
        "adds a proof obligation and tightens evidence",
        "bounded by the grants and gates that already bind the job",
        "keeps that condition",
        "becomes 6.0.0",
        "Supersedes` is 5.1.0",
        "PR #1691",
        f"{TOKEN} <pr_number> <head_sha>",
    ):
        assert frag in f, frag


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


# ------------------------------------------------------------------------------------ what must not move


def test_rail_and_operator_only_sections_are_byte_identical():
    for name, (start, end, digest) in PINNED_SECTIONS.items():
        block = _section(AGENTS, start, end)
        assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"


def test_23_14_is_byte_identical():
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S)
    assert sec
    m = re.search(r"^## 23\.14 .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m
    block = m.group(0).rstrip("\n").rstrip("-").rstrip("\n").replace(CLAUSE_23_14_16_0_0, CLAUSE_23_14_PRE_16_0_0)  # 16.0.0 clause (2)
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_14_SHA256


def test_adapters_carry_nothing_from_5_2_0():
    for rel in ADAPTERS:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        assert "5.2.0" not in text and "forced run" not in text.lower(), rel


# --------------------------------------------------------------------------------------------------- §8.1


def test_8_1_lives_in_section_8_before_8a():
    s8 = AGENTS.index("# 8 · Validation and verification")
    s81 = AGENTS.index("## 8.1 Working means validated now")
    s8a = AGENTS.index("# 8A · Testing standards")
    assert s8 < s81 < s8a


def test_8_1_requires_tests_dry_run_and_forced_run_before_working():
    f = _s81()
    for frag in (
        'An agent may call a build, change or install "working" only after all three of these are quoted',
        'never "working", "live", "fixed" or "done"',
        "pass under `TRADE_AI_CI=1`",
        "A dry run of the changed path, output quoted (§0 rule 7, §6)",
        "triggered on demand exactly as its schedule would trigger it",
        "the same command, environment, cwd rule, wrappers and locks",
        "`coordination/run` (§23.3) in the mode its stage allows",
        "durable artifact dated after the trigger",
        "(§0 rule 8). An exit code is not the proof",
    ):
        assert frag in f, frag


def test_8_1_natural_fires_are_monitored_never_awaited_and_lift_no_gate():
    f = _s81()
    for frag in (
        "Natural schedules then run as normal operation and are monitored",
        "A natural fire is never the first proof",
        "nobody waits for one to declare success",
        "a dependent step may start on the forced-run proof",
        "a natural fire that fails makes the change not working again",
        "This lifts no gate this file or a standard already conditions on natural-schedule evidence",
        "§23.12, last bullet",
        "`PAUSED` row's flip to `ACTIVE`",
        "(§15)",
        # 16.0.0 (ratified 2026-10-21, #1911) dropped onboarding step 8 and the three clean market days from this
        # list (§23.21 replacement (3)): an n8n cutover's readiness is the §23.21 cutover standard.
        "An n8n cutover is the exception: its readiness is the §23.21 cutover standard (16.0.0)",
        "no natural shadow slot and no run of clean days",
    ):
        assert frag in f, frag


def test_8_1_bounds_grant_overlap_and_change_record():
    f = _s81()
    for frag in (
        "needs the grant the install needed, still unexpired",
        "This rule grants nothing",
        "skipped on the job's lock (`RUN_SKIPPED_LOCK`",
        "or ran harmlessly",
        "Record it in the change record",
        "the trigger command, the trigger time, the artifact with its path and timestamp",
    ):
        assert frag in f, frag


def test_8_1_exceptions_where_no_forced_run_is_allowed():
    f = _s81()
    for frag in (
        "Where a forced run is NOT allowed",
        "Broker, order, stop, session and 2FA paths",
        "§0 rule 2, §2, §22 or §24.10",
        "No agent triggers one on demand, under any grant",
        "Jobs whose effect depends on the clock",
        "scripts/run_with_deepseek_offpeak.sh --scheduled",
        "never sets `TRADEAI_ALLOW_SCHEDULED_PEAK=1`",
        "the deferral receipt is the forced run's proof",
        "Operator-only surfaces** (§17)",
        "Anything that would double-send to the operator",
        "through the router with dedupe on, or uses the sender's dry run",
        "its forced run is the dry run",
    ):
        assert frag in f, frag


def test_8_1_cites_its_cause():
    f = _s81()
    assert "Cause (§20)" in f and "10:50 ET" in f and "the grant expired" in f
    assert "but we do not wait for natural schedules" in f


# ------------------------------------------------------------------------------------------------ pointers


def test_pointers_in_6_8_9_3_16_23_12_and_23_19():
    s6 = _sub(r"# 6 · Dry runs", r"# 7 · ")
    assert "that effect is the forced run of §8.1 (5.2.0)" in s6
    s8 = _sub(r"## What counts as verified", r"## 8\.1 ")
    assert "A proof staged by hand does not satisfy a claim that something happens on schedule." in s8
    assert "A forced run (§8.1) is not that claim's proof" in s8
    s93 = _sub(r"## 9\.3 Scheduled jobs", r"## 9\.4 ")
    assert "a hand-run does not close it" in s93
    assert "proven working by a forced run under its schedule's exact form (§8.1, 5.2.0)" in s93
    s16 = _sub(r"# 16 · Not accepted as completion", r"# 17 · ")
    assert '"working" declared without the tests, dry run and forced run of §8.1' in s16
    s2312 = _sub(r"## 23\.12 ", r"## 23\.13 ")
    assert "After cutover each lane still owes durable evidence on its natural schedule (§9.3)" in s2312
    assert "A wave fire is a forced run (§8.1, 5.2.0)" in s2312
    s2319 = _sub(r"## 23\.19 ", r"# 24 · ")
    assert "The standard's proof steps restate §8.1 (5.2.0)" in s2319


def test_onboarding_standard_restates_8_1_and_keeps_its_natural_gates():
    f = _flat(ONBOARDING)
    for frag in (
        "AGENTS.md 5.2.0 §8.1",
        "forced",
        "Prove the shadow fire**",  # 16.0.0 (§23.21 (2)): a forced `dry_run` fire counts; no natural slot
        "no natural shadow slot",
        "Natural-schedule evidence after cutover",
        "monitored, not awaited",
    ):
        assert frag in f, frag
