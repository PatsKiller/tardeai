"""AGENTS.md 5.0.0 (PROPOSED, MAJOR) — §24.10 broker-adjacent daemon operations under an `execution-ops` grant.

The operator asked for "4.7.0 (MINOR)" on 2026-10-10 ~21:50 ET. The version policy classifies a change that narrows an
authority rail (§0 rule 2, broker access) as MAJOR, so this is numbered 5.0.0 (see the banner).

What this pins:
  * the header and version row stay PROPOSED / PENDING with the §20 approval phrase until ratified;
  * §0 changes by exactly one sentence inside rule 2 (with it removed, §0 hashes to the digest pinned since 4.1.0),
    and §2, §2A, §7A, §17 and §23.14 are byte-identical;
  * §24.10 carries every operator condition: reach (broker-execution user units only; OpenD, `--mode live`, system
    units and root out), a per-incident `execution-ops` grant of at most 6 h that is remotely grantable, the permitted
    actions, the market calendar failing closed, the preflight, proof, rollback by restoring the archived drop-in,
    and the never-list;
  * the code facts §24.10 relies on hold (the calendar's CLOSED state, the remote forbidden-scope list, the tests the
    preflight names);
  * once the operator has run the packet installer, the guard carries the scope, the 6 h cap and the classifier.

All tests are read-only: they read repository files and call a pure calendar function. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_5_0_0"
ET = ZoneInfo("America/New_York")

RULE_2_EXCEPTION_5_0_0 = (
    "\n   One operational exception, binding only once AGENTS.md 5.0.0 is ACTIVE: with an operator"
    "\n   `execution-ops` grant naming the unit, an agent may inspect, re-point, reload and restart that"
    "\n   broker-execution unit while markets are closed, and never touch its code, credentials, flags or"
    "\n   orders (AGENTS.md §24.10)."
)
SECTION_0_WITHOUT_SENTENCE_SHA256 = "61fe9dfbeaa3c61cf354e42ed1cdc6f7006a105b46d538cd79a74407f349af32"
SECTION_0_WITH_SENTENCE_SHA256 = "d7ce297890a85a125b2b0d7dc8234a0e4e679ffd6bae6d7820b2076a0267ec29"
SECTION_23_14_SHA256 = "bb8722f69b8e54a8582011bdbe266d55ea7c2c0c6b120d123a1d4e43394311e7"
UNCHANGED_SECTIONS = {
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"),
    "§17": ("# 17 · Operator-only decisions", "# 17A ·", "f61b30d248331b2ee11e950cc8f455a273608d52d1eba3de6fca191b98e5f2f5"),
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
    # Same §7A generated-table mask as the 4.1.0/4.3.0/4.4.0/4.6.0 pins (PR #1678).
    return re.sub(r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)", r"\1\n<generated>\n\2", block, flags=re.S)


def _s2410() -> str:
    m = re.search(r"^## 24\.10 .*?(?=^## |^---$|^# |\Z)", AGENTS, re.M | re.S)
    assert m, "§24.10 missing"
    return m.group(0)


def _row() -> re.Match:
    m = re.search(r"^\| 5\.0\.0 \| 2026-10-10 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 5.0.0 | 2026-10-10 | PROPOSED|ACTIVE | MAJOR |` version row"
    return m


# ---------------------------------------------------------------------------------------- header, row, banner


def test_header_is_5_0_0_proposed_or_later():
    assert _version() >= (5, 0, 0)
    if _version() == (5, 0, 0) and _control("Status") == "PROPOSED":
        assert _control("Effective-Date") == "PENDING"
        assert _control("Supersedes") in ("4.4.0", "4.4.1", "4.5.0", "4.6.0")


def test_version_row_is_major_and_waits_for_the_operator():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 5.0.0 must not claim a prior token"
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 5.0.0 row must record token, PR and sha"
    assert "4.7.0" in rest, "the row must say it was requested as 4.7.0 and renumbered"


def test_banner_explains_the_class_and_the_number():
    start = AGENTS.index("**5.0.0 is PROPOSED (MAJOR)")
    f = _flat(AGENTS[start : AGENTS.index("**4.3.0 is ACTIVE", start)])
    for frag in ("Why MAJOR", "4.7.0", "weakest guarantee", "PR #1682", "PR #1666", "does not ratify 4.6.0",
                 f"{TOKEN} <pr_number> <head_sha>", "execution-ops", "≤ 6 h"):
        assert frag in f, frag


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


# ------------------------------------------------------------------------------- §0 / §2 — one sentence only


def test_section_0_changes_by_exactly_one_sentence_inside_rule_2():
    sec0 = _section(AGENTS, "# 0 · If you read nothing else", "# 1 · Identity and responsibilities")
    assert sec0.count(RULE_2_EXCEPTION_5_0_0) == 1
    rule2 = sec0[sec0.index("2. **Broker code is buildable") : sec0.index("3. **Never route")]
    assert RULE_2_EXCEPTION_5_0_0 in rule2
    assert hashlib.sha256(sec0.encode("utf-8")).hexdigest() == SECTION_0_WITH_SENTENCE_SHA256
    stripped = sec0.replace(RULE_2_EXCEPTION_5_0_0, "")
    assert hashlib.sha256(stripped.encode("utf-8")).hexdigest() == SECTION_0_WITHOUT_SENTENCE_SHA256


def test_rule_2_still_forbids_everything_else():
    sec0 = _flat(_section(AGENTS, "# 0 · If you read nothing else", "# 1 · Identity and responsibilities"))
    for frag in ("Without one, the broker execution subsystem is out of scope", "No agent ever calls a live broker",
                 "reads a live credential", "sets a live flag", "calls `place_order`", "binding only once AGENTS.md 5.0.0 is ACTIVE",
                 "never touch its code, credentials, flags or orders"):
        assert frag in sec0, frag


@pytest.mark.parametrize("name", list(UNCHANGED_SECTIONS))
def test_other_rail_sections_are_byte_identical(name):
    start, end, digest = UNCHANGED_SECTIONS[name]
    assert hashlib.sha256(_section(AGENTS, start, end).encode("utf-8")).hexdigest() == digest, f"{name} changed"


def test_23_14_is_byte_identical():
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S)
    assert sec
    m = re.search(r"^## 23\.14 .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m
    block = m.group(0).rstrip("\n").rstrip("-").rstrip("\n")
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_14_SHA256


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_adapters_carry_rule_2_and_at_most_the_exact_sentence(adapter):
    text = (ROOT / adapter).read_text(encoding="utf-8")
    assert "Without one, the broker execution subsystem is out of scope" in text
    if "execution-ops" in text:
        assert RULE_2_EXCEPTION_5_0_0 in text, f"{adapter} paraphrases the 5.0.0 sentence instead of repeating it"


# -------------------------------------------------------------------------------------------------- §24.10


def test_24_10_is_proposed_with_its_own_token_and_every_bullet_cites_a_cause():
    s = _s2410()
    head = _flat(s[:700])
    if _control("Status") == "PROPOSED":
        assert "PROPOSED (MAJOR)" in head and f"{TOKEN} <pr_number> <head_sha>" in head
        assert "binds nothing" in head
    bullets = re.split(r"\n- ", s)[1:]
    assert len(bullets) >= 8
    assert all("*Cause (§20):" in _flat(b) for b in bullets)


def test_24_10_reach_is_broker_execution_user_units_only():
    f = _flat(_s2410())
    for frag in ("`scripts/active_trader/**`", "`scripts/brokers/**`", "`tradeai-active-trader-motion.service`",
                 "-m active_trader.motion_runtime", "`trade-ai-lab-moomoo-opend`", "`--mode live`", "every system unit",
                 "anything that needs root"):
        assert frag in f, frag


def test_24_10_grant_is_per_incident_capped_and_remotely_grantable():
    f = _flat(_s2410())
    for frag in ("`execution-ops`, per incident, at most 6 hours", "bin/guard request execution-ops",
                 "`/approve <CODE>`", "remotely grantable", "refuses a window over 6 h",
                 "never reused for another", "binds the scope, not the unit", "§0 rule 3",
                 "I need a way to grant exceptions for rule number two"):
        assert frag in f, frag


def test_remote_approval_does_not_forbid_the_scope_and_its_ceiling_is_at_least_6h():
    from scripts.lib import guard_remote_approval as gra

    assert "execution-ops" not in gra.REMOTE_FORBIDDEN_SCOPES
    assert "guard-config" in gra.REMOTE_FORBIDDEN_SCOPES  # a phone still cannot widen what a phone may do
    assert gra.MAX_GRANT_SECONDS >= 6 * 3600


def test_24_10_permitted_actions_are_the_operator_list_and_nothing_else():
    f = _flat(_s2410())
    for frag in ("`journalctl --user -u <unit>`", "readlink /proc/<MainPID>/cwd", "Never `Environment`",
                 # Host prefix elided on purpose (scripts/check_test_host_paths.py, baseline 0): the
                 # suffix still pins the operator release root named in §24.10.
                 "`95-code-root-current.conf`", "/trade-ai-releases/portfolio-server/CURRENT",
                 "archived by rename", "never deleted", "`systemctl --user daemon-reload` chained with that unit's restart",
                 "`systemctl --user restart <unit>`", "under the operator's home", "stays operator-only",
                 "/etc/tardeai/enable-active-trader-motion"):
        assert frag in f, frag
    for verb in ("`stop`", "`kill`", "`enable`", "`disable`", "`mask`", "`edit`", "`set-property`", "`sudo`"):
        assert verb in f[f.index("Not under this grant") :], verb
    assert "A `service` grant is never authority over a broker-execution unit" in f


def test_24_10_market_gate_uses_the_calendar_and_fails_closed():
    f = _flat(_s2410())
    assert 'cio_market_session.market_session()["state"]` is `"CLOSED"`' in f
    assert "Pre-market and post-market count as open" in f
    assert "A calendar error refuses the action" in f and "fails open" in f


@pytest.mark.parametrize(
    "when,state",
    [
        (datetime(2026, 10, 10, 21, 55, tzinfo=ET), "CLOSED"),  # Saturday
        (datetime(2026, 10, 12, 21, 0, tzinfo=ET), "CLOSED"),  # Monday after post-market
        (datetime(2026, 10, 13, 3, 30, tzinfo=ET), "CLOSED"),  # before pre-market
        (datetime(2026, 10, 13, 5, 0, tzinfo=ET), "PRE"),  # open for §24.10
        (datetime(2026, 10, 13, 10, 0, tzinfo=ET), "RTH"),
        (datetime(2026, 10, 13, 17, 0, tzinfo=ET), "POST"),  # open for §24.10
        (datetime(2026, 12, 25, 12, 0, tzinfo=ET), "CLOSED"),  # NYSE holiday
    ],
)
def test_calendar_states_match_what_24_10_says(when, state):
    from scripts.lib import cio_market_session as MS

    assert MS.market_session(when, service=MS.NYSESessionService())["state"] == state


def test_24_10_preflight_names_tests_that_exist_and_the_store_check():
    f = _flat(_s2410())
    for rel in ("tests/test_active_trader_motion_runtime.py", "tests/test_active_trader_motion_host_proof.py"):
        assert f"`{rel}`" in f and (ROOT / rel).is_file(), rel
    for frag in ("`TRADE_AI_CI=1`", "Any failure stops the procedure", "`STORE_RISK`", "`SIGNAL_MOVES`", "§0 rule 5",
                 "systemd-analyze --user verify", "A dry run prints", "§0 rule 7"):
        assert frag in f, frag


def test_24_10_proof_and_rollback():
    f = _flat(_s2410())
    for frag in ("`ActiveState=active`", "resolves to the CURRENT release directory", "receipt",
                 "restores the archived one by rename", "then stops and reports", "§0 rule 8"):
        assert frag in f, frag


def test_24_10_never_list():
    f = _flat(_s2410())
    for frag in ("Never read, copy or print a credential or env file", "live/paper flag or mode",
                 "whose last journal start line shows a live mode", "live activation (A4, §17)",
                 "order, stop, session-grant or 2FA path", "`scripts/active_trader/**`, `scripts/brokers/**` or `scripts/moomoo/**`",
                 "never call a broker"):
        assert frag in f, frag


def test_24_10_states_its_open_gaps():
    f = _flat(_s2410())
    for frag in ("Three gaps stay open", "binds the scope and not the unit", "still classify as `service`",
                 "PreToolUse hook is not installed", "release that runs the callback poller",
                 "install_execution_ops_scope.py", "`broker.execution_ops`"):
        assert frag in f, frag


# ------------------------------------------------------------- guard, once the operator has run the installer

GUARD = ROOT / "bin" / "guard"
GUARD_LIB = ROOT / ".cursor" / "hooks" / "guard-lib.sh"


def _installed() -> bool:
    return "execution-ops" in GUARD.read_text(encoding="utf-8")


def test_guard_scope_installed_consistently_or_not_at_all():
    lib = GUARD_LIB.read_text(encoding="utf-8")
    if not _installed():
        assert "execution-ops" not in lib, "guard-lib.sh has the scope but bin/guard does not (partial install)"
        pytest.skip("execution-ops not installed yet (operator-run packet installer)")
    g = GUARD.read_text(encoding="utf-8")
    assert re.search(r'^ALL_TIERS="[^"]*\bexecution-ops\b', g, re.M)
    assert "21600" in g, "bin/guard must cap execution-ops grants at 6 h"
    assert "execution-ops)" in lib and "AGENTS.md 5.0.0 §24.10" in lib


@pytest.mark.parametrize(
    "cmd,tier",
    [
        ("systemctl --user restart tradeai-active-trader-motion.service", "execution-ops"),
        ("systemctl --user daemon-reload && systemctl --user restart tradeai-active-trader-motion.service", "execution-ops"),
        ("mv ~/.config/systemd/user/tradeai-active-trader-motion.service.d/95-code-root-current.conf /tmp/x", "execution-ops"),
        ("systemctl --user stop tradeai-active-trader-motion.service", "service"),
        ("systemctl --user restart tradeai-active-trader-motion.service portfolio-server.service", "service"),
        ("systemctl --user daemon-reload", "service"),
        ("rm ~/.config/systemd/user/tradeai-active-trader-motion.service.d/95-code-root-current.conf", "destructive"),
        ("systemctl --user restart portfolio-server.service", "service"),
        ("sudo systemctl restart tradeai-active-trader-motion.service", "sudo"),
        ("systemctl --user status tradeai-active-trader-motion.service", "none"),
        ("journalctl --user -u tradeai-active-trader-motion.service -n 50", "none"),
    ],
)
def test_guard_classifier_routes_broker_unit_operations(cmd, tier):
    if not _installed():
        pytest.skip("execution-ops not installed yet (operator-run packet installer)")
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    script = f'source "{GUARD_LIB}"; classify_cmd "$1"'
    out = subprocess.run([bash, "-c", script, "_", cmd], capture_output=True, text=True, timeout=20, check=False)
    assert out.stdout.strip() == tier, (cmd, out.stdout, out.stderr)


@pytest.mark.parametrize("window,ok", [("6h", True), ("7h", False)])
def test_bin_guard_caps_execution_ops_at_6h(tmp_path, window, ok):
    if not _installed():
        pytest.skip("execution-ops not installed yet (operator-run packet installer)")
    if not (shutil.which("bash") and shutil.which("jq")):
        pytest.skip("bash/jq unavailable")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRADE_AI_CI": "1",
           "GUARD_APPROVALS_DIR": str(tmp_path / "approvals"), "GUARD_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    out = subprocess.run([str(GUARD), "grant", "execution-ops", "--for", window, "--uses", "3", "--reason", "test", "--yes"],
                         capture_output=True, text=True, timeout=30, check=False, env=env)
    assert (out.returncode == 0) is ok, (out.stdout, out.stderr)
    if not ok:
        assert "capped at 6h" in out.stdout


HOOK = ROOT / "scripts" / "hooks" / "agents_guard_pretooluse.py"
HOOK_RULES = ROOT / "config" / "agents_guard_hook_rules.json"


@pytest.mark.parametrize(
    "grant,cmd,denied",
    [
        ("service", "systemctl --user restart tradeai-active-trader-motion.service", True),
        ("execution-ops", "systemctl --user restart tradeai-active-trader-motion.service", False),
        ("execution-ops", "systemctl --user stop tradeai-active-trader-motion.service", True),
        ("execution-ops", "systemctl --user daemon-reload", False),
        ("service", "systemctl --user restart portfolio-server.service", False),
    ],
)
def test_claude_hook_routes_broker_unit_restart_to_execution_ops(tmp_path, monkeypatch, grant, cmd, denied):
    """Hermetic (HOME, state root and ledger in tmp). Runs only once the installer has patched the hook."""
    if "broker.execution_ops" not in HOOK_RULES.read_text(encoding="utf-8"):
        pytest.skip("execution-ops hook rule not installed yet (operator-run packet installer)")
    import importlib.util
    import json
    import time

    monkeypatch.setenv("HOME", str(Path("/nonexistent-eo-home") / tmp_path.name))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path / "approvals"))
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_RULES", str(HOOK_RULES))
    monkeypatch.setenv("TRADEAI_AGENTS_GUARD_MODE", "deny")
    (tmp_path / "approvals").mkdir()
    (tmp_path / "approvals" / "grants.json").write_text(
        json.dumps({grant: {"expires": int(time.time()) + 1800, "uses": 5, "reason": "test"}})
    )
    spec = importlib.util.spec_from_file_location("agents_guard_pretooluse_eo", HOOK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    payload = {"session_id": "s", "cwd": f"{tmp_path}/wt", "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": cmd}, "transcript_path": "/dev/null"}
    _out, records, _ = mod.run(json.dumps(payload))
    assert any(r["would_deny"] for r in records) is denied, records
