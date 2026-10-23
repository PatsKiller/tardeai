"""AGENTS.md 17.0.0 (PROPOSED, MAJOR) — §25 the release train, plus AI_WORK_POLICY.md §28.

RED UNTIL THE OPERATOR APPLIES THE PATCH. Agents never edit AGENTS.md or AI_WORK_POLICY.md; the amendment ships as
two operator-applied patches (scratchpad `agents-16-17/agents-17.0.0-proposed.patch` and
`agents-16-17/ai-work-policy-17.0.0-proposed.patch`), built on origin/main 4104effb9 (15.0.0 ACTIVE) plus the refreshed
16.0.0 PROPOSED patch. This test is committed on `agents/release-train-17-0-0-20261021` (based on the 16.0.0 branch)
ahead of them, by design.

Operator approval 2026-10-21: operator-forced OFF-WINDOW canary runs (TTY plus phrase, canary phase only, every other
gate still enforced); §25.3 states it and §25.8 states that it is not built yet.

Operator directive 2026-10-21 (plan record): agents queue PRs only; a scheduled train integrates, releases and
reports at 00:00, 06:00, 08:00 and 18:00 ET. Decisions 2026-10-21: D1 standing revocable delegation; D2 GitHub App
with 1-hour tokens; D3 resume / scope changes only via host CLI or Telegram button confirmation.

What this pins:
  * one 17.0.0 history row, PROPOSED with PENDING and the §20 phrase until ratified; while PROPOSED the header block
    reads 17.0.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` the last ACTIVE version; the state checker passes;
  * the banner and §25 state every rule the brief names, and every §25 bullet cites its cause;
  * §0, §2, §2A, §7A, §22 and §23.14 are byte-identical to origin/main 7faa8cddf (or to the 15.0.0-ratified §0, if
    #1852 lands first), and so are the four adapters;
  * while PROPOSED, §17, §24.5 and §24.8 are byte-identical; once ratified, each gains exactly the clause quoted in
    §25.9, whose SHA-256 is pinned here, and minus that clause is byte-identical again;
  * AI_WORK_POLICY.md sections 1-27 are byte-identical and §28 is binding only once 17.0.0 is ACTIVE;
  * the code §25 names exists and agrees with it.

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
AWP = (ROOT / "AI_WORK_POLICY.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_17_0_0"
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")


def h(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# Measured on origin/main 7faa8cddf (14.0.0 ACTIVE), identical with the 16.0.0 patch and with the 17.0.0 patch applied.
RAILS = {
    "§0": ("# 0 · If you read nothing else", "# 1 · Identity and responsibilities",
           {"86ab4957123f59a846cdeab39dfda8b96f69950a9031ff870228aa9942de79f3",
            # 15.0.0-ratified §0 (#1852 adds the disk-hygiene sentence to rule 6); not changed by 17.0.0.
            "d10461625959d3de2f520419dbb67c1763e46d6b5905784b6aa185795ac10549"}),
    "§2": ("# 2 · Authority rails", "# 2A ·", {"5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"}),
    "§2A": ("# 2A ·", "# 2B ·", {"38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"}),
    "§7A": ("# 7A ·", "# 8 ·", {"6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"}),
    "§22": ("# 22 · ", "# 23 · ", {"81f1646a64e38047882c7375ab18739111ba8349471fbaa0351fc1069f9717e9"}),
}
SECTION_23_14_SHA256 = {
    "bb8722f69b8e54a8582011bdbe266d55ea7c2c0c6b120d123a1d4e43394311e7",
    # after the 16.0.0 ratifying edit (its clause (2)); pinned as SECTION_23_14_16_0_0_SHA256 by
    # tests/test_agents_policy_16_0_0_cutover_standard.py. 17.0.0 itself never changes §23.14.
    "891c55a5be08630952c61300f95bcb5442f1ef6b37fb5cb5018e72f843a9043f",
}
SECTION_17_SHA256 = {"f61b30d248331b2ee11e950cc8f455a273608d52d1eba3de6fca191b98e5f2f5",
                     # 15.0.0-ratified §17 (#1852 adds the disk-hygiene item)
                     "2eeb550129d0054a2526907cd8fc5a482caf59ab03ac97cd51a60cdea90ea238"}
SECTION_24_5_SHA256 = "01186281f84060666ac7de6045201aeed88b477f8aa0cf35404a5270d520785d"
SECTION_24_8_SHA256 = "eea733900bb49f71a45049034415b2cc134679f0a8418248c4bf4fc797043413"
#: AI_WORK_POLICY.md §§1-27 on origin/main after the operator-applied guard patches (ced99617e, PR #1912: push budget
#: per git common dir + branch) and before §28; was 7faa8cddf (de347f28…) when 17.0.0 was drafted. The patch only appends §28.
AWP_MAIN_SHA256 = "f2ad84aecbb16ed97a1d7709a59cec83004bf96a6f4cc354d55f4f97c14e17a2"

# The three clauses the ratifying edit inserts (quoted in §25.9).
S17_ANCHOR = ("monitoring. **If the deferred list grows during a wave, that is a finding about how the wave was\n"
              "run.**\n\n")
S17_ADDITION = (
    "**Release train (17.0.0, §25):** arming, re-arming or revoking the standing release delegation, and\n"
    "creating or editing its host record · clearing a release STOP or resuming the release train · expanding the\n"
    "train's scope: a permitted class, an enabled window, a limit, a named service or the verification policy\n"
    "(narrowing it is the same act and the same proof) · custody of the release-train GitHub App: creating,\n"
    "installing, re-permissioning or suspending it, and placing, rotating or revoking its private key. Each is done\n"
    "by the operator at the host CLI (`scripts/release_control_cli.py`) or by a Telegram button confirmation\n"
    "(decision D3, 2026-10-21); an agent or the Command Center may only request STOP or pause.\n"
    "\n"
)
R245_ANCHOR = "  backup (§0 rule 8).*\n"
R245_INS = (
    "- **One exception (17.0.0, §25): the release service.** Once the standing delegation is armed, the host release\n"
    "  service (never an agent, a lane script or an n8n workflow) may push `refs/heads/train/<train_id>`, open the\n"
    "  train's batch PR and merge it, each only inside a reservation of a ReleaseCapability@v1 for that train and\n"
    "  phase and with a GitHub App installation token minted for that reservation. Nothing else scheduled pushes.\n"
    "  *Cause (§20): operator directive 2026-10-21 (§25.1); decisions D1 and D2.*\n"
)
R248_ANCHOR = "  promoted under another campaign's grant.*\n"
R248_INS = (
    "- **Under the release train (17.0.0, §25) the capability is the binding.** A train merge or promotion is\n"
    "  authorized by a ReleaseCapability@v1 that binds the exact base, candidate and artifact, the ordered PR heads\n"
    "  and the qualifying CI evidence; it is issued per train and phase, never per day. A `release-write` grant naming\n"
    "  the SHA or PR stays the binding for the manual and emergency paths. *Cause (§20): decision D1 2026-10-21 —\n"
    "  standing authorization replaces daily and 7-day grants; the enhanced design §3 requires the full binding.*\n"
)
CLAUSE_SHA256 = {
    "S17": "8a40ded03c14814d0f5b769c00f6730b4d82b85f3172cbe9a12e3f756bc2c035",
    "R245": "39c0ff5332ce2063adc4d09fbba2a6d5e8504c04741131345fa9cd704a5d5877",
    "R248": "c84f81587f1596e950ec46e23b7e13314ee35b37c7e33c784b0adefd8fbec98e",
}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _section(text: str, start: str, end: str) -> str:
    s = re.search(rf"^{re.escape(start)}", text, re.M)
    assert s, start
    e = re.search(rf"^{re.escape(end)}", text[s.start() + 1:], re.M)
    assert e, end
    block = text[s.start(): s.start() + 1 + e.start()]
    return re.sub(r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)",
                  r"\1\n<generated>\n\2", block, flags=re.S)


def _sub(text: str, num: str) -> str:
    m = re.search(rf"^## {re.escape(num)} .*?(?=^## |^---$|^# |\Z)", text, re.M | re.S)
    assert m, f"§{num} missing"
    return m.group(0).rstrip("\n").rstrip("-").rstrip("\n")


def _row() -> re.Match:
    m = re.search(r"^\| 17\.0\.0 \| 2026-10-21 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 17.0.0 | 2026-10-21 | PROPOSED|ACTIVE | MAJOR |` row: the 17.0.0 patch is not applied"
    return m


def _ratified() -> bool:
    return _row().group(1) == "ACTIVE"


def _s25() -> str:
    m = re.search(r"^# 25 · Release train.*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§25 missing: the 17.0.0 patch is not applied"
    return m.group(0)


# ------------------------------------------------------------------------------------- header, row, banner


def test_one_row_and_state_checker_passes():
    _row()
    assert len(re.findall(r"^\| 17\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 17.0.0 must not ride a prior token"
        assert re.search(r"^Policy-Version:\s+17\.0\.0$", AGENTS, re.M), "the patch sets the header to 17.0.0"
        assert re.search(r"^Status:\s+PROPOSED$", AGENTS, re.M) and re.search(r"^Effective-Date:\s+PENDING$", AGENTS, re.M)
        # the last ACTIVE version: 15.0.0 while 16.0.0 is PROPOSED, 16.0.0 once it is ratified
        assert re.search(r"^Supersedes:\s+1[56]\.0\.0$", AGENTS, re.M)
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 17.0.0 row must record token, PR and sha"


def test_banner_explains_class_number_scope_and_decisions():
    start = AGENTS.index("**17.0.0 is ")
    banner = _flat(AGENTS[start: AGENTS.index("\n\n**", start + 10)])
    for frag in ("Why MAJOR:", "weakest guarantee", "never merge, push `main` or `train/*`", "standing revocable",
                 "00:00, 06:00, 08:00 and 18:00 ET", "merge freeze", "STOP", "§17", "only automated remote sync",
                 "D1", "D2", "D3", "TOTP declined", "15.0.0", "16.0.0", f"{TOKEN} <pr_number> <head_sha>",
                 "Byte-identical:", "arms nothing", "operator-forced off-window canary runs",
                 "TTY plus phrase, canary phase only", "no multi-day waits"):
        assert frag in banner, frag


# --------------------------------------------------------------------------------------------------- §25


@pytest.mark.parametrize("sub,frags", [
    ("25.1", ("never merges a PR", "`train/*`", "never prepares", "last remote act is a PR",
              "Until the first arming the manual process is unchanged", "never authorize",
              "TRADEAI_RELEASE_TRAIN_SHA")),
    ("25.2", ("no daily or 7-day renewal", "ReleaseDelegation@v1", "~/.config/tradeai/release_train/delegation.json",
              "never inside the repository", "`ACTIVE`, `PAUSED`, `REVOKED`", "fail closed", "accepts its digest",
              "ReleaseCapability@v1", "cannot merge or promote", "rollback target", "exactly `success`",
              "`ci-gate`", "one global release lock", "consumes nothing", "UNCERTAIN", "reconciled",
              "never over 3600 s")),
    ("25.3", ("18:00, 00:00, 06:00 and 08:00", "DST-aware", "no catch-up", "canary", "macro", "Merge freeze",
              "train reaches a terminal state", "One train per window",
              # operator approval 2026-10-21: operator-forced off-window canary runs, canary phase only
              "operator-forced off-window canary runs, canary phase only", "stdin is a TTY",
              "re-types the exact phrase", "never accepted from n8n, the Command Center, Telegram, an agent",
              "an agent never forces one", "Only the window check is waived", "Every other gate still holds",
              "never starts during regular market hours", "counts toward the canary proofs",
              "with no minimum wait between windows",
              "Outside the canary phase an off-window request stays shadow")),
    ("25.4", ("separate from the trading kill switch", "requested → acknowledged → settling → stopped",
              "increments the", "Fail closed", "ABSENT, SET, UNREADABLE", "may only request STOP or pause",
              "host CLI", "Telegram button confirmation", "new epoch", "never delete", "Pause after current",
              "Revoke")),
    ("25.5", ("GitHub App", "PatsKiller/tardeai", "1-hour installation token", "mode 600", "cannot be limited to a "
              "branch or a path", "ruleset", "docs/ops/RELEASE_TRAIN_GITHUB_APP.md", "Workflows write withheld")),
    ("25.6", ("only automated remote sync", "AI_WORK_POLICY.md` §28")),
    # operator (owner) 2026-10-21: no multi-day waits; each phase ends when its proofs pass
    ("25.7", ("each ends when its proofs pass, with no minimum number of days or windows", "18:00 canary",
              "crash recovery", "counts toward these proofs", "may come in consecutive windows",
              "No document, packet or runbook may add a multi-day wait",
              "I just only asked you to remove the three-day wait requirement")),
    ("25.8", ("libraries only", "stub", "log mode", "BUILD_ONLY", "`REFUSED_OFF_WINDOW`",
              "the exception authorizes nothing in code")),
    ("25.9", ("three clauses", "§17", "§24.5", "§24.8")),
])
def test_section_25_states_every_rule(sub, frags):
    text = _flat(_sub(_s25(), sub))
    for frag in frags:
        assert _flat(frag) in text, f"§{sub}: {frag!r}"


def test_no_minimum_day_count_in_section_25():
    # operator (owner) 2026-10-21: the three-day waits are removed; only the verbatim quote of that ruling may say it
    text = _flat(_s25()).replace("remove the three-day wait requirement", "").replace("the three-day waits are removed", "")
    for frag in ("three shadow days", "three market days", "market days of 18:00 canary", "at least three",
                 "three-day"):
        assert frag not in text, frag


def test_every_section_25_bullet_cites_its_cause():
    bullets = re.split(r"\n(?=- \*\*)", _s25())[1:]
    assert len(bullets) >= 20, len(bullets)
    for b in bullets:
        assert "*Cause (§20):" in b, b[:120]


# ---------------------------------------------------------------------------------- byte-identical rails


@pytest.mark.parametrize("name", list(RAILS))
def test_rail_sections_are_byte_identical(name):
    start, end, digests = RAILS[name]
    assert h(_section(AGENTS, start, end)) in digests, f"{name} changed"


def test_23_14_is_byte_identical():
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S)
    assert sec
    assert h(_sub(sec.group(0), "23.14")) in SECTION_23_14_SHA256


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_carry_nothing_from_17_0_0(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    for frag in ("17.0.0", "release train", "train/*", "ReleaseDelegation", "release_control"):
        assert frag not in text, f"{adapter} carries {frag!r}"


@pytest.mark.parametrize("key,section,anchor,clause,digest_pin", [
    ("S17", lambda t: _section(t, "# 17 · Operator-only decisions", "# 17A ·"), S17_ANCHOR, S17_ADDITION,
     SECTION_17_SHA256),
    ("R245", lambda t: _sub(t, "24.5"), R245_ANCHOR, R245_INS, {SECTION_24_5_SHA256}),
    ("R248", lambda t: _sub(t, "24.8"), R248_ANCHOR, R248_INS, {SECTION_24_8_SHA256}),
])
def test_ratifying_clauses(key, section, anchor, clause, digest_pin):
    assert h(clause) == CLAUSE_SHA256[key]
    block = section(AGENTS)
    if not _ratified():
        assert clause not in AGENTS, f"{key} is in force before ratification"
        assert h(block) in digest_pin, f"{key}: section changed while PROPOSED"
        assert AGENTS.count(anchor) == 1, f"{key}: insertion anchor not unique"
    else:
        # _sub() drops the subsection's trailing newline; restore it so a clause inserted as the last bullet matches.
        tail = "" if block.endswith("\n") else "\n"
        full = block + tail
        assert full.count(clause) == 1 and (anchor + clause) in AGENTS, f"{key} not inserted after its anchor"
        rest = full.replace(clause, "", 1)
        rest = rest[: len(rest) - len(tail)]
        assert h(rest) in digest_pin, f"{key}: more than the clause changed"


def test_section_25_9_quotes_the_clauses_verbatim_with_their_digests():
    s259 = _sub(_s25(), "25.9")
    for key, clause in (("S17", S17_ADDITION), ("R245", R245_INS), ("R248", R248_INS)):
        quoted = "\n".join(("  " + line) if line else "" for line in clause.rstrip("\n").split("\n"))
        assert "  ```\n" + quoted + "\n  ```" in s259, f"{key} is not quoted verbatim in §25.9"
        assert f"sha256 `{CLAUSE_SHA256[key]}`" in s259, f"{key} digest not stated in §25.9"


# ---------------------------------------------------------------------------------------- AI_WORK_POLICY


def test_ai_work_policy_only_appends_section_28():
    i = AWP.find("---\n\n# 28. RELEASE TRAIN PUSHES")
    assert i > 0, "AI_WORK_POLICY.md §28 missing: the 17.0.0 AI_WORK_POLICY patch is not applied"
    assert h(AWP[:i]) == AWP_MAIN_SHA256, "AI_WORK_POLICY.md sections 1-27 changed"
    s28 = _flat(AWP[i:])
    # while PROPOSED §28 is binding only once 17.0.0 is ACTIVE and the delegation is armed; the ratifying edit marks
    # 17.0.0 ACTIVE there and leaves the arming condition
    gate = (("(AGENTS.md 17.0.0, ACTIVE)", "AGENTS.md 17.0.0 is ACTIVE (ratified 2026-10-21, PR #1914)",
             "Binding only once the operator has also armed the standing release delegation at the host")
            if _ratified() else ("(AGENTS.md 17.0.0, PROPOSED)", "Binding only once AGENTS.md 17.0.0 is ACTIVE"))
    for frag in gate + ("only automated remote synchronization",
                 "refs/heads/train/<train_id>", "ReleaseCapability@v1", "GitHub App installation", "not counted against",
                 "never pushes `main` or any `train/*` ref, never merges", "never deploy by themselves",
                 "operator-only"):
        assert _flat(frag) in s28, frag


# ---------------------------------------------------------------------------------------- code agrees


def test_code_named_in_section_25_exists_and_agrees():
    from scripts import release_window as RW
    from scripts.lib import release_capability as CAP
    from scripts.lib import release_control as RC
    from scripts.lib import release_delegation as RD

    s25 = _s25()
    for path in ("scripts/lib/release_delegation.py", "scripts/lib/release_capability.py",
                 "scripts/lib/release_control.py", "scripts/release_control_cli.py",
                 "config/release_train_delegation.example.json", "config/schemas/release_delegation_v1.schema.json",
                 "docs/ops/RELEASE_TRAIN_GITHUB_APP.md", "tests/test_release_train_authority_20261021.py"):
        assert (ROOT / path).exists(), path
        assert path.split("/")[-1] in s25 or path.startswith("config/schemas"), path
    assert set(RD.WINDOW_IDS) == {"0000", "0600", "0800", "1800"}
    assert RD.HARD_MAX_TTL_S == 3600 and RD.HARD_MAX_ATTEMPTS == 3
    assert not str(RD.DEFAULT_PATH).startswith(str(ROOT))
    assert not (CAP.PHASE_ACTIONS[CAP.PHASE_BUILD] & (CAP.PHASE_ACTIONS[CAP.PHASE_MERGE]
                                                      | CAP.PHASE_ACTIONS[CAP.PHASE_PROMOTE]))
    assert RC.OPERATOR_KINDS == frozenset({"host_cli", "telegram"}) and "cc" not in RC.OPERATOR_KINDS
    assert "cc" in RC.REQUEST_KINDS
    assert list(RC.STOP_PHASE.values()) == ["requested", "acknowledged", "settling", "stopped"]
    assert RC.GLOBAL_LOCK_NAME == ".lock" and RC.LATCH_NAME == RW.State(Path("/nonexistent")).latch.name
    assert RD.REQUIRED_CHECKS_FLOOR == {"cio-hardening", "agent-governance", "release-readiness"}
