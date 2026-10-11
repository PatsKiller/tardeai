"""AGENTS.md 5.1.0 (PROPOSED, MINOR) — §9.1: operator-action messages are P1 notification intents with dedupe off.

Cause: PR #1685 (``n8nmat/bypass-senders-to-intents``, head 1d9eba216) moves 25 ``bypass_router=True`` senders to
notification intents (P1/P2), while §9.1 said anything the operator must act on is sent with ``bypass_router=True``.
§24.1 (4.6.0) already says senders emit notification intents. This amendment rewrites the §9.1 bullet, adds the
legacy-allowlist and P2-hold bullets, and points §8 and §24.1 at them.

What this pins:
  * the header and the version row stay PROPOSED / PENDING with the §20 approval phrase until ratified, and the
    banner states the class, the reasoning, the merge order and the open item for #1685;
  * the rails do not move: §0 (with the 5.0.0 rule 2 sentence), §2, §2A, §7A (generated table masked), §17 and
    §23.14 hash to the digests the 4.6.0 / 5.0.0 pins hold, and the adapters carry nothing from 5.1.0;
  * §9.1 says what the operator ruled: P1 with dedupe off, never capped, quiet-held, archived or suppressed; the
    bypass is legacy, allowlisted and shrink-only; the broker-execution senders keep it pending an
    ``execution-engineering`` grant; P2 holds 22:00–07:00 ET to the Reports archive and the advice digest;
  * once PR #1685 is on the branch, the code the rule names agrees with it (otherwise those checks skip — the banner
    makes #1685 the first to merge).

All tests are read-only. TRADE_AI_CI=1.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_5_1_0"
INTENTS_TEST = ROOT / "tests" / "test_notification_intents_20261010.py"

# Same digests as tests/test_agents_policy_5_0_0_execution_ops.py (measured at origin/main e24ccd6c5, 5.0.0 ACTIVE).
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
BROKER_SENDERS = (
    "scripts/alpaca_stop_manager.py",
    "scripts/defense_execution.py",
    "scripts/moomoo/opend_health.py",
)


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
    # Same §7A generated-table mask as the 4.1.0 / 4.3.0 / 4.4.0 / 4.6.0 / 5.0.0 pins (PR #1678).
    return re.sub(
        r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)",
        r"\1\n<generated>\n\2",
        block,
        flags=re.S,
    )


def _s91() -> str:
    m = re.search(r"^## 9\.1 Operator notifications.*?(?=^## 9\.2 )", AGENTS, re.M | re.S)
    assert m, "§9.1 missing"
    return m.group(0)


def _row() -> re.Match:
    m = re.search(r"^\| 5\.1\.0 \| 2026-10-11 \| (PROPOSED|ACTIVE)[^|]* \| MINOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 5.1.0 | 2026-10-11 | PROPOSED|ACTIVE | MINOR |` version row"
    return m


def _banner() -> str:
    start = AGENTS.index("**5.1.0 is ")
    return _flat(AGENTS[start : AGENTS.index("**4.5.0 is ACTIVE", start)])


# ---------------------------------------------------------------------------------------- header, row, banner


def test_header_is_5_1_0_proposed_or_later():
    assert _version() >= (5, 1, 0)
    if _version() == (5, 1, 0):
        assert _control("Supersedes") == "5.0.0"
        if _control("Status") == "PROPOSED":
            assert _control("Effective-Date") == "PENDING"
            assert "5.1.0 is PROPOSED (MINOR)" in _flat(AGENTS[:20000])


def test_version_row_is_minor_and_waits_for_the_operator_with_the_exact_phrase():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 5.1.0 must not claim a prior token"
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 5.1.0 row must record token, PR and sha"
    for frag in ("PR #1685", "tests/test_agents_policy_5_1_0_notification_intents.py", "6.0.0"):
        assert frag in rest, frag


def test_banner_states_the_class_reasoning_merge_order_and_open_item():
    f = _banner()
    for frag in (
        "Why MINOR",
        "replaces a mechanism and keeps the guarantee",
        "becomes 6.0.0",
        "Merge order:** PR #1685 first",
        "stop_decision_brief.py",
        "dedupe_minutes=0",
        "execution-engineering",
        "22:00–07:00 ET",
        "Supersedes` is 5.0.0",
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


def test_adapters_carry_nothing_from_5_1_0():
    for rel in ADAPTERS:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        assert "5.1.0" not in text and "notification intent" not in text.lower(), rel


# --------------------------------------------------------------------------------------------------- §9.1


def test_9_1_operator_action_is_p1_with_dedupe_off():
    f = _flat(_s91())
    assert "Anything the operator must act on bypasses the router" not in f
    for frag in (
        "Anything the operator must act on is sent as a P1 notification intent with dedupe off",
        'priority="P1", dedupe_minutes=0',
        "telegram_alert_router.route_intent",
        "approve, deny or decide",
        "never text-classified, capped, quiet-held, archived or suppressed",
        "declared window of 0",
        "NotificationIntentRoute@v1",
        "*accepted for interrupt delivery*, never *sent*",
    ):
        assert frag in f, frag


def test_9_1_bypass_is_legacy_allowlisted_shrink_only_and_broker_senders_wait_for_a_grant():
    f = _flat(_s91())
    for frag in (
        "`bypass_router=True` is legacy, allowlisted and shrink-only",
        "tests/test_notification_intents_20261010.py",
        "can only shrink",
        "execution-engineering",
        "scripts/guard_request_approval.py",
        "scripts/active_trader/momentum_alerts.py",
        *BROKER_SENDERS,
    ):
        assert frag in f, frag


def test_9_1_p2_holds_in_the_quiet_window_to_the_reports_archive_and_digest():
    f = _flat(_s91())
    for frag in (
        "22:00–07:00 America/New_York",
        "reports_archive",
        "notification_intent_p2",
        "advice digest",
        "a hold that cannot be archived is delivered instead",
        "Anything that must reach the operator inside the quiet window is P1",
    ):
        assert frag in f, frag


def test_8_and_24_1_point_at_9_1():
    assert "Under 5.1.0 that bypass is an allowlisted legacy site (§9.1)" in _flat(AGENTS)
    s241 = re.search(r"^## 24\.1 .*?(?=^## 24\.2 )", AGENTS, re.M | re.S)
    assert s241 and "allowlist are in §9.1 (5.1.0)" in _flat(s241.group(0))


# ------------------------------------------------------- the code the rule names (present once #1685 merges)


def _require_1685():
    if not INTENTS_TEST.exists():
        pytest.skip(
            "PR #1685 not on this branch: tests/test_notification_intents_20261010.py absent (merge #1685 first)"
        )


def test_allowlist_holds_the_broker_senders_and_the_guard_request():
    _require_1685()
    src = INTENTS_TEST.read_text(encoding="utf-8")
    m = re.search(r"^BYPASS_ALLOWLIST = \{(.*?)^\}", src, re.M | re.S)
    assert m, "BYPASS_ALLOWLIST missing"
    for rel in (*BROKER_SENDERS, "scripts/guard_request_approval.py"):
        assert f'"{rel}"' in m.group(1), rel
    assert "allowlist is shrink-only" in src


def test_router_window_and_hold_match_the_rule():
    _require_1685()
    import telegram_alert_router as TR

    if not hasattr(TR, "route_intent"):
        pytest.skip("telegram_alert_router.route_intent absent (PR #1685 not merged)")
    assert TR._QUIET_START_ENV[1] == "22:00" and TR._QUIET_END_ENV[1] == "07:00"
    assert TR._QUIET_TZ_ENV[1] == "America/New_York"
    assert TR.HELD_P2_REPORT_TYPE == "notification_intent_p2"
    assert TR.INTENT_RECEIPT_SCHEMA == "NotificationIntentRoute@v1"
    assert TR.route_intent("probe", "P1", dedupe_minutes=0)["window_minutes"] == 0


def test_approval_reminder_is_p1_with_dedupe_off():
    _require_1685()
    src = (ROOT / "scripts" / "approval_package_reminder.py").read_text(encoding="utf-8")
    assert 'priority="P1", dedupe_minutes=0' in src
