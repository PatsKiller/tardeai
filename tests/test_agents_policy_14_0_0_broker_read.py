"""AGENTS.md 14.0.0 (PROPOSED, MAJOR) — §24.11 the read-only broker sync under a `broker-read` grant.

Operator request 2026-10-16, verbatim: "make that bash so agents can run, make amendment, not trading just reading,
update agents.md".

What this pins:
  * one 14.0.0 history row, PROPOSED with PENDING and the §20 phrase until ratified; the header stays the last
    ACTIVE version (12.0.0) and the state checker passes on a branch and on main;
  * while PROPOSED, §0 and its four adapter copies are byte-identical to the 5.0.0 digest and carry no
    `broker-read` text; once ratified, §0 rule 2 carries exactly the proposed sentence, directly after the 5.0.0
    sentence, and §0 minus it hashes to the same digest; §2, §2A, §7A and §17 are byte-identical either way;
  * the sentence quoted in §24.11 is exactly the one the ratifying edit inserts, and its post-insertion digest is
    pinned here so the 5.1.0 / 5.2.0 pins can take it;
  * §24.11 states every condition, each bullet cites its cause, and the refusal names it quotes exist in the code;
  * the guard scope (`bin/guard` ALL_TIERS + 4 h cap, `guard-lib.sh` scope text and classifier) is consistent.

Read-only: reads repository files; the guard tests use a tmp HOME and ledger. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_agents_policy_state as STATE  # noqa: E402
from scripts.lib import broker_read_sync_policy as POLICY  # noqa: E402
from tests import test_agents_policy_5_0_0_execution_ops as T5  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
# AGENTS.md 19.0.0 (§27.5): once 19.0.0 is ACTIVE its four clause edits in §17, §23.14 and §25.4 are undone before
# the pins below are checked; tests/test_agents_policy_19_0_0_broker_read_controls.py pins those edits and the
# post-ratification digests. While 19.0.0 is PROPOSED the text is unchanged.
from tests.test_agents_policy_19_0_0_broker_read_controls import pre_19_0_0  # noqa: E402

AGENTS = pre_19_0_0(AGENTS)
TOKEN = "APPROVE_AGENTS_POLICY_14_0_0"
SENTENCE_14_0_0 = (
    "\n   One read-only exception, binding only once AGENTS.md 14.0.0 is ACTIVE: with an operator"
    "\n   `broker-read` grant, an agent may run `scripts/ops/broker_read_sync.sh` and no other broker"
    "\n   read; it never sees a credential value, re-authenticates, changes a flag or reaches an order"
    "\n   route (AGENTS.md §24.11)."
)
#: §0 as it is on this branch and on origin/main 766914db2 (= the 5.0.0 "with sentence" digest).
SECTION_0_PROPOSED_SHA256 = T5.SECTION_0_WITH_SENTENCE_SHA256
#: §0 after the ratifying edit inserts SENTENCE_14_0_0 after the 5.0.0 sentence (computed by
#: test_ratified_digest_is_what_the_insertion_produces from the current §0; the 5.1.0/5.2.0 pins take it then).
SECTION_0_RATIFIED_SHA256 = "86ab4957123f59a846cdeab39dfda8b96f69950a9031ff870228aa9942de79f3"
ADAPTERS = T5.ADAPTERS


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _sec0() -> str:
    # 15.0.0 (ratified 2026-10-21) adds a rule 6 sentence, pinned by tests/test_agents_policy_15_0_0_disk_hygiene.py.
    sec0 = T5._section(AGENTS, "# 0 · If you read nothing else", "# 1 · Identity and responsibilities")
    return sec0.replace(T5.RULE_6_EXCEPTION_15_0_0, "")


def _row() -> re.Match:
    m = re.search(r"^\| 14\.0\.0 \| 2026-10-16 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 14.0.0 | 2026-10-16 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


def _ratified() -> bool:
    return _row().group(1) == "ACTIVE"


def _s2411() -> str:
    m = re.search(r"^## 24\.11 .*?(?=^## |^---$|^# |\Z)", AGENTS, re.M | re.S)
    assert m, "§24.11 missing"
    return m.group(0)


def _insert(sec0: str) -> str:
    anchor = T5.RULE_2_EXCEPTION_5_0_0
    assert sec0.count(anchor) == 1
    return sec0.replace(anchor, anchor + SENTENCE_14_0_0, 1)


# ------------------------------------------------------------------------------------- header, row, banner


def test_one_row_and_state_checker_passes():
    assert len(re.findall(r"^\| 14\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_row_waits_for_the_operator_or_records_the_token():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 14.0.0 must not ride a prior token"
        assert re.search(r"^Policy-Version:\s+12\.0\.0$", AGENTS, re.M), "header moves only at ratification"
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 14.0.0 row must record token, PR and sha"


def test_banner_explains_class_number_and_scope():
    start = AGENTS.index("**14.0.0 is ")
    banner = _flat(AGENTS[start : AGENTS.index("\n\n**", start + 10)])
    for frag in ("Why MAJOR:", "weakest guarantee", "12.1.0", "13.0.0", "PR #1830", "nightly cutover controller",
                 f"{TOKEN} <pr_number> <head_sha>", "`broker-read`", "scripts/ops/broker_read_sync.sh",
                 "make that bash so agents can run, make amendment, not trading just reading, update agents.md",
                 "trading lock is LOCKED", "`read_only`", "no order route is reachable", "byte-identical"):
        assert frag in banner, frag


# --------------------------------------------------------------------------------------- §0 and the adapters


def test_section_0_is_unchanged_until_ratified_then_gains_exactly_one_sentence():
    sec0 = _sec0()
    if not _ratified():
        assert SENTENCE_14_0_0 not in sec0 and "broker-read" not in sec0
        assert hashlib.sha256(sec0.encode("utf-8")).hexdigest() == SECTION_0_PROPOSED_SHA256
    else:
        assert sec0.count(SENTENCE_14_0_0) == 1
        assert T5.RULE_2_EXCEPTION_5_0_0 + SENTENCE_14_0_0 in sec0, "the sentence follows the 5.0.0 sentence"
        stripped = sec0.replace(SENTENCE_14_0_0, "")
        assert hashlib.sha256(stripped.encode("utf-8")).hexdigest() == SECTION_0_PROPOSED_SHA256


def test_ratified_digest_is_what_the_insertion_produces():
    sec0 = _sec0()
    base = sec0.replace(SENTENCE_14_0_0, "") if _ratified() else sec0
    got = hashlib.sha256(_insert(base).encode("utf-8")).hexdigest()
    assert got == SECTION_0_RATIFIED_SHA256, got


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_follow_section_0(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    if not _ratified():
        assert "broker-read" not in text and "broker_read_sync" not in text, f"{adapter} ahead of ratification"
    else:
        assert SENTENCE_14_0_0 in text, f"{adapter} paraphrases the 14.0.0 sentence instead of repeating it"


@pytest.mark.parametrize("name", list(T5.UNCHANGED_SECTIONS))
def test_other_rail_sections_are_byte_identical(name):
    start, end, digest = T5.UNCHANGED_SECTIONS[name]
    block = T5._section(AGENTS, start, end).replace(T5.S17_ENTRY_15_0_0, "")  # 15.0.0's §17 entry
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"


def test_proposed_sentence_is_quoted_verbatim_in_24_11():
    s = _s2411()
    m = re.search(r"\n  ```\n(.*?)\n  ```", s, re.S)
    assert m, "§24.11 carries no quoted sentence block"
    quoted = "\n" + "\n".join(line[2:] for line in m.group(1).split("\n"))
    assert quoted == SENTENCE_14_0_0


# --------------------------------------------------------------------------------------------------- §24.11


def test_24_11_is_proposed_and_every_bullet_cites_a_cause():
    s = _s2411()
    head = _flat(s[:900])
    if not _ratified():
        assert "PROPOSED (MAJOR)" in head and f"{TOKEN} <pr_number> <head_sha>" in _flat(s[:400])
        assert "Binds nothing" in head and "--plan" in head
    bullets = re.split(r"\n- ", s)[1:]
    assert len(bullets) >= 9
    assert all("*Cause (§20):" in _flat(b) for b in bullets)


def test_24_11_names_every_condition_and_the_code_that_enforces_it():
    f = _flat(_s2411())
    for frag in ("closed step list", "`broker-read`, at most 4 hours, one use per run", "bin/guard revoke broker-read",
                 "trading_lock_not_locked:<broker>", "broker_read_grant_missing", "schwab_access_mode_not_read_only",
                 "capability_found:<kind>:<module>", "not_served_release", "env_file_missing", "needs_operator_reauth",
                 "never opens `.env`", "scrubbed", "§24.7 is unchanged", "non-GET/HEAD", "`BrokerReadSyncReceipt@v1`",
                 "Stop managers, stop sync", "options lifecycle", "defense execution", "fails if any excluded family",
                 "tests/test_broker_read_sync_20261016.py", "about 1,145 modules", "Open gaps, stated",
                 "operator-only guard configuration"):
        assert frag in f, frag
    code = (ROOT / "scripts" / "ops" / "broker_read_sync.py").read_text(encoding="utf-8")
    for name in ("broker_read_grant_missing", "trading_lock_not_locked:", "schwab_access_mode_not_read_only",
                 "capability_found:", "not_served_release", "env_file_missing", "needs_operator_reauth"):
        assert name in code, name


def test_24_11_step_list_matches_the_code():
    f = _flat(_s2411())
    for step in POLICY.STEPS:
        assert f"`{Path(step.script).name}" in f, step.script
    assert POLICY.GRANT_TIER == "broker-read" and POLICY.POLICY_TOKEN == TOKEN and POLICY.POLICY_VERSION == "14.0.0"
    assert POLICY.GRANT_MAX_SECONDS == 4 * 3600


# -------------------------------------------------------------------------------------------------- guard

GUARD = ROOT / "bin" / "guard"
GUARD_LIB = ROOT / ".cursor" / "hooks" / "guard-lib.sh"


def test_guard_scope_is_defined_consistently():
    g = GUARD.read_text(encoding="utf-8")
    lib = GUARD_LIB.read_text(encoding="utf-8")
    assert re.search(r'^ALL_TIERS="[^"]*\bbroker-read\b', g, re.M)
    assert "14400" in g and "AGENTS.md 14.0.0 §24.11" in g
    assert "broker-read)" in lib and "AGENTS.md 14.0.0 §24.11" in lib
    from scripts.lib import guard_remote_approval as gra

    assert "broker-read" not in gra.REMOTE_FORBIDDEN_SCOPES  # remotely grantable, like execution-ops
    assert gra.MAX_GRANT_SECONDS >= POLICY.GRANT_MAX_SECONDS


@pytest.mark.parametrize(
    "cmd,tier",
    [
        ("scripts/ops/broker_read_sync.sh", "broker-read"),
        ("scripts/ops/broker_read_sync.sh --apply", "broker-read"),
        ("python3 scripts/ops/broker_read_sync.py --apply", "broker-read"),
        ("python3 scripts/ops/broker_read_sync_child.py schwab_positions apply", "broker-read"),
        ("scripts/ops/broker_read_sync.sh --plan", "none"),
        ("scripts/ops/broker_read_sync.sh --plan; scripts/ops/broker_read_sync.sh --apply", "broker-read"),
    ],
)
def test_guard_classifier_routes_the_sync_to_broker_read(cmd, tier):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    out = subprocess.run([bash, "-c", f'source "{GUARD_LIB}"; classify_cmd "$1"', "_", cmd],
                         capture_output=True, text=True, timeout=20, check=False)
    assert out.stdout.strip() == tier, (cmd, out.stdout, out.stderr)


@pytest.mark.parametrize("window,ok", [("4h", True), ("5h", False)])
def test_bin_guard_caps_broker_read_at_4h(tmp_path, window, ok):
    if not (shutil.which("bash") and shutil.which("jq")):
        pytest.skip("bash/jq unavailable")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRADE_AI_CI": "1",
           "GUARD_APPROVALS_DIR": str(tmp_path / "approvals"), "GUARD_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    out = subprocess.run([str(GUARD), "grant", "broker-read", "--for", window, "--uses", "2", "--reason", "test", "--yes"],
                         capture_output=True, text=True, timeout=30, check=False, env=env)
    assert (out.returncode == 0) is ok, (out.stdout, out.stderr)
    if not ok:
        assert "capped at 4h" in out.stdout
