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
ONBOARDING = (ROOT / "docs" / "implementation" / "n8n-maturity" / "N8N_ONBOARDING_STANDARD.md").read_text(
    encoding="utf-8"
)
TOKEN = "APPROVE_AGENTS_POLICY_5_2_0"

# Same digests as tests/test_agents_policy_5_1_0_notification_intents.py (5.0.0 ACTIVE, 5.1.0 merged at 26cf80f60).
SECTION_0_SHA256 = "d7ce297890a85a125b2b0d7dc8234a0e4e679ffd6bae6d7820b2076a0267ec29"
SECTION_23_14_SHA256 = "bb8722f69b8e54a8582011bdbe266d55ea7c2c0c6b120d123a1d4e43394311e7"
PINNED_SECTIONS = {
    "§0": ("# 0 · If you read nothing else", "# 1 · Identity and responsibilities", SECTION_0_SHA256),
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"),
    "§17": (
        "# 17 · Operator-only decisions",
        "# 17A ·",
        "f61b30d248331b2ee11e950cc8f455a273608d52d1eba3de6fca191b98e5f2f5",
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


def _section(text: str, start: str, end: str) -> str:
    s = re.search(rf"^{re.escape(start)}", text, re.M)
    assert s, start
    e = re.search(rf"^{re.escape(end)}", text[s.start() + 1 :], re.M)
    assert e, end
    block = text[s.start() : s.start() + 1 + e.start()]
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
    block = m.group(0).rstrip("\n").rstrip("-").rstrip("\n")
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
        "step 8",
        "§23.12, last bullet",
        "`PAUSED` row's flip to `ACTIVE`",
        "three clean market days",
        "(§15)",
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
        "Prove the shadow fire** on the natural schedule",
        "Natural-schedule evidence after cutover",
        "monitored, not awaited",
    ):
        assert frag in f, frag
