"""AGENTS.md 6.0.0 (PROPOSED, MAJOR) — onboarding step 8 accepts a forced shadow fire (§8.1, §23.19).

Cause: operator 2026-10-11, "Onboarding step 8, can we do it now and dry test it?" — 5.2.0 §8.1 kept step 8's shadow
fire natural, so a lane already proven by a forced fire still waited for its dispatcher slot before canary.

What this pins:
  * the header and the version row stay PROPOSED / PENDING with the §20 approval phrase until ratified; the banner
    states MAJOR, why, the 5.3.0 alternative, the 7.0.0 renumbering case and the dependency on 5.2.0 (#1693);
  * the rails do not move: §0, §2, §2A, §7A (generated table masked), §17 and §23.14 hash to the same digests as the
    5.2.0 pin, and the adapters carry nothing from 6.0.0;
  * §8.1 lifts exactly one natural gate — step 8 — and keeps §23.12's post-cutover evidence, PAUSED -> ACTIVE,
    §23.3's three clean market days and §15 natural;
  * the forced fire's terms: same row and path, dry_run, a non-slot key, the stage clamp (no double run), RUN_DONE
    evidence from relay log + ledger + receipt, never an n8n execution status, the compute_due sweep, the record, and
    that an agent never issues it through the relay (the bearer is a credential, §24.7);
  * canary keeps every other condition; §23.19 and the onboarding standard restate it;
  * the code facts the text relies on: no natural-fire count in the ladder code, the executor's stage clamp keeps a
    shadow lane dry_run whatever is requested, the gateway refuses an invented slot key and accepts the f: key shape.

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
from scripts.lib import lane_stage_clamp as CLAMP  # noqa: E402
from scripts.lib.n8n_coordination_gateway import RUN_ID_RE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ONBOARDING = (ROOT / "docs" / "implementation" / "n8n-maturity" / "N8N_ONBOARDING_STANDARD.md").read_text(
    encoding="utf-8"
)
TOKEN = "APPROVE_AGENTS_POLICY_6_0_0"

# Same digests as tests/test_agents_policy_5_2_0_validation.py: 6.0.0 moves none of these.
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


def _step8_block() -> str:
    f = _s81()
    start = f.index("**Onboarding step 8 accepts a forced shadow fire (6.0.0).**")
    return f[start:]


def _row() -> re.Match:
    m = re.search(r"^\| 6\.0\.0 \| 2026-10-11 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 6.0.0 | 2026-10-11 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


def _banner() -> str:
    start = AGENTS.index("**6.0.0 is ")
    return _flat(AGENTS[start : AGENTS.index("**5.2.0 is ", start)])


# ---------------------------------------------------------------------------------------- header, row, banner


def test_header_is_6_0_0_proposed_or_later():
    assert _version() >= (6, 0, 0)
    if _version() == (6, 0, 0):
        assert _control("Supersedes") == "5.2.0"
        if _control("Status") == "PROPOSED":
            assert _control("Effective-Date") == "PENDING"
            assert "6.0.0 is PROPOSED (MAJOR)" in _flat(AGENTS[:40000])


def test_version_row_is_major_first_and_waits_for_the_operator():
    m = _row()
    status, rest = m.group(1), m.group(2)
    table = AGENTS[AGENTS.index("| Version | Date | Status | Change class | Summary | Approval |") :]
    assert table.index("| 6.0.0 |") < table.index("| 5.2.0 |"), "6.0.0 row must sit above 5.2.0"
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 6.0.0 must not claim a prior token"
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 6.0.0 row must record token, PR and sha"
    for frag in (
        "step 8",
        "tests/test_agents_policy_6_0_0_step8.py",
        "5.3.0",
        "7.0.0",
        "Supersedes 5.2.0",
        "#1693",
        "N8N_ONBOARDING_STANDARD.md",
        "§24.7",
    ):
        assert frag in rest, frag


def test_banner_states_major_and_why_and_the_alternatives():
    f = _banner()
    for frag in (
        "6.0.0 is PROPOSED (MAJOR)",
        "Onboarding step 8, can we do it now and dry test it?",
        "Why MAJOR",
        "removes that condition",
        "adding a rule is not a MINOR if it removes a restriction elsewhere",
        "first n8n-initiated `live` fire",
        "the number becomes 5.3.0",
        "this becomes 7.0.0",
        "PR #1693",
        "`Supersedes` is 5.2.0",
        "Merge #1693 first",
        "no code changes",
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


def test_adapters_carry_nothing_from_6_0_0():
    for rel in ADAPTERS:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        assert "6.0.0" not in text and "forced shadow fire" not in text.lower(), rel


# --------------------------------------------------------------------------------------------------- §8.1


def test_8_1_lifts_only_step_8_and_keeps_the_other_natural_gates():
    f = _s81()
    head = f[: f.index("**Onboarding step 8 accepts a forced shadow fire (6.0.0).**")]
    assert "except onboarding step 8 (6.0.0, below)" in head
    for frag in (
        "natural-schedule evidence after a cutover (§23.12, last bullet)",
        "`PAUSED` row's flip to `ACTIVE`",
        "three clean market days with cron as fallback (§23.3)",
        "the maturity proofs (§15)",
    ):
        assert frag in head, frag
    # the 5.2.0 wording that kept step 8 natural is gone
    assert "the lane-specific shadow fire on the natural schedule" not in f
    blk = _step8_block()
    assert "The exception is step 8's alone" in blk
    assert "does not reach §23.12's post-cutover evidence, a `PAUSED` → `ACTIVE` flip, §23.3's three clean" in blk


def test_8_1_forced_fire_terms():
    f = _step8_block()
    for frag in (
        "Same row, same path.",
        '`scheduler.stage = "shadow"`, `dispatch.mode = "dry_run"`',
        "`live_arg` null",
        "relay → gateway → executor (§23.3)",
        "in mode `dry_run` with a non-slot idempotency key",
        "`f:<lane_id>:dry_run:<UTC YYYYMMDDTHHMMSS>`",
        "the gateway refuses an invented one (`run_slot_not_due`)",
        "It cannot double-run the job.",
        "At shadow the executor clamps every request to `dry_run` (`scripts/lib/lane_stage_clamp.py`)",
        "the dry run is write-free",
        "meets the same lock and shows `RUN_SKIPPED_LOCK`",
        "The evidence is `RUN_DONE` in mode `dry_run`, dated after the trigger:",
        "the relay log line, the coordination ledger row and its `RunReceipt`",
        "`output_signal_mtime_before == after`",
        "`RUN_SKIPPED_LOCK`, `RUN_FAILED`, `RUN_REFUSED`, `RUN_TIMEOUT` or a moved output_signal is not the evidence",
        "an n8n execution status never is",
        "`compute_due` week sweep",
        "Recorded",
    ):
        assert frag in f, frag


def test_8_1_agent_never_issues_it_through_the_relay():
    f = _step8_block()
    assert "The relay takes a bearer that is a credential, and an agent never reads one (§24.7)" in f
    assert "an agent never issues the forced fire through the relay itself" in f
    assert "The operator issues it, or a workflow change brings it under the `cron` grant" in f


def test_8_1_canary_keeps_every_other_condition():
    f = _step8_block()
    for frag in (
        "Canary still needs every other condition",
        "health contract `REVIEWED` (step 3)",
        "the allowlist (step 5)",
        "reviewed registry PR (step 6, §23.11)",
        "the lock equal to the cron line's (step 9)",
        "the R1 admission and the grants each step names",
        "first natural shadow or canary fire is still checked",
        "it leaves the wave and stays on cron (§23.12)",
    ):
        assert frag in f, frag
    assert "Cause (§20)" in f


def test_23_19_pointer():
    s2319 = _sub(r"## 23\.19 ", r"# 24 · ")
    assert "except step 8, whose shadow fire may be a forced `dry_run` fire on the terms of §8.1 (6.0.0)" in s2319


# ---------------------------------------------------------------------------------------- onboarding standard


def test_onboarding_step_8_and_proof_note_restate_6_0_0():
    f = _flat(ONBOARDING)
    for frag in (
        "AGENTS.md 6.0.0 §8.1 (PROPOSED",
        "Prove the shadow fire** — natural or forced (AGENTS.md 6.0.0 §8.1, PROPOSED)",
        "(step 12, a `PAUSED` monitor's flip to `ACTIVE`), that condition stays",
        "Step 8 is the exception (AGENTS.md 6.0.0 §8.1, PROPOSED)",
        "Natural-schedule evidence after cutover",
        "`f:<lane_id>:dry_run:<UTC YYYYMMDDTHHMMSS>`",
        "An agent never issues it through the relay (the bearer is a credential, AGENTS.md §24.7)",
        "none for a natural fire; a forced fire is the operator's (relay bearer)",
    ):
        assert frag in f, frag
    assert "this natural fire is the schedule proof and stays the gate" not in f


def test_onboarding_forced_fire_procedure():
    m = re.search(r"^### 1\.1 Forced shadow fire for step 8.*?(?=^---$|^## )", ONBOARDING, re.M | re.S)
    assert m, "§1.1 procedure missing"
    f = _flat(m.group(0))
    for frag in (
        "Binding only once 6.0.0 is ACTIVE",
        "**the operator**",
        "it never sources or opens the file that holds the bearer",
        "No grant",
        "Dry run of the trigger (agent)",
        '"mode": "dry_run"',
        "Leave `workflow_id` out",
        '`requested_by: "n8n:relay"`',
        "POST http://172.19.0.1:18092/run",
        "relay_log.jsonl",
        "n8n_coordination_ledger.sqlite`, opened `mode=ro`",
        "`stage_clamp.effective_mode` `dry_run`",
        "Never an n8n execution status",
    ):
        assert frag in f, frag
    # the procedure never names a live request
    assert '"mode": "live"' not in f


# ------------------------------------------------------------------------------------- code facts relied upon


def test_no_ladder_code_counts_natural_fires_at_shadow():
    for rel in (
        "scripts/lib/lane_dispatch.py",
        "scripts/pipelines/cutover/_cutover.py",
        "scripts/check_lane_registry.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert "natural" not in text, f"{rel} now mentions natural fires; re-check 6.0.0's 'no code changes' claim"
    checklist = (ROOT / "scripts" / "n8n_cutover_checklist.py").read_text(encoding="utf-8")
    # its only natural item is the post-cutover acceptance fire, which 6.0.0 keeps
    assert checklist.lower().count('"step": "natural_fire"') == 1
    assert "Post-cutover natural fire" in checklist


def test_stage_clamp_keeps_a_shadow_lane_dry_run_whatever_is_requested():
    rows = [{"lane_id": "x-lane", "scheduler": {"kind": "cron", "stage": "shadow"}}]
    live = CLAMP.clamp_mode("x-lane", "live", rows)
    assert live["effective_mode"] == "dry_run" and live["clamped"] is True and live["reason"] == "stage_shadow"
    dry = CLAMP.clamp_mode("x-lane", "dry_run", rows)
    assert dry["effective_mode"] == "dry_run" and dry["clamped"] is False


def test_forced_key_shape_is_accepted_and_is_not_a_slot_key():
    key = "f:hermes-topic-monitor-bridge:dry_run:20261011T153000"
    assert RUN_ID_RE.fullmatch(key)
    assert key[:2].lower() not in ("d:", "e:", "g:")
