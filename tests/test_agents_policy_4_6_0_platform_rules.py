"""AGENTS.md 4.6.0 (PROPOSED, MINOR) — §24 platform rules from the 2026-10-10 consolidation.

Backlog rows A3–A11 (``~/n8n-maturity-verification/DOCS_AND_AGENTS_UPDATE_BACKLOG.md``): notifications (n8n
orchestrates, the communications gateway sends, P1 independent of n8n), search source routing and the Brave dollar
budget, the data broker owner/consumer rule, other applications on the host, no push from scheduled jobs, test
isolation, no ``.env`` access, release grants bound to a SHA/PR, Supabase / n8n Cloud portability.

What this pins:
  * the header and the version row stay PROPOSED / PENDING with the §20 approval phrase until ratified;
  * the amendment adds rules without editing a rail: §0, §2, §2A, §7A, §17 and §23.14 are byte-identical to the
    digests the 4.4.0 test pins (measured at origin/main 7df77950a, AGENTS 4.4.0 ACTIVE);
  * §24 has subsections 24.1–24.9, each bullet citing its cause, and the numbers and names the rules rely on exist.

Numbering: 4.4.1 / 4.5.0 merged in PR #1666 (dd8f4cff1); 4.5.0 ratified (316700266), so Supersedes is 4.5.0.
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
TOKEN = "APPROVE_AGENTS_POLICY_4_6_0"

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
# Operator-requested amendment 5.0.0 (asked for as "4.7.0", 2026-10-10 ~21:50 ET; PROPOSED, pending
# APPROVE_AGENTS_POLICY_5_0_0): §0 rule 2 gains exactly this one sentence, pointing to §24.10. It is removed before
# hashing, so the digest below still proves every other byte of §0 is unchanged; the sentence itself is pinned by
# tests/test_agents_policy_5_0_0_execution_ops.py. Nothing else in §0 or §2 may move.
RULE_2_EXCEPTION_5_0_0 = (
    "\n   One operational exception, binding only once AGENTS.md 5.0.0 is ACTIVE: with an operator"
    "\n   `execution-ops` grant naming the unit, an agent may inspect, re-point, reload and restart that"
    "\n   broker-execution unit while markets are closed, and never touch its code, credentials, flags or"
    "\n   orders (AGENTS.md §24.10)."
)
# AGENTS.md 14.0.0 (ACTIVE 2026-10-16, ratified APPROVE_AGENTS_POLICY_14_0_0 1838 0d4940cda): §0 rule 2 gains this one
# sentence after the 5.0.0 one, pointing to §24.11. Stripped before hashing like the 5.0.0 sentence; the sentence and
# the full §0 digest are pinned by tests/test_agents_policy_14_0_0_broker_read.py.
RULE_2_EXCEPTION_14_0_0 = (
    "\n   One read-only exception, binding only once AGENTS.md 14.0.0 is ACTIVE: with an operator"
    "\n   `broker-read` grant, an agent may run `scripts/ops/broker_read_sync.sh` and no other broker"
    "\n   read; it never sees a credential value, re-authenticates, changes a flag or reaches an order"
    "\n   route (AGENTS.md §24.11)."
)
# AGENTS.md 15.0.0 (ACTIVE 2026-10-21, ratified APPROVE_AGENTS_POLICY_15_0_0 1852 fc5672896): §0 rule 6 gains this one
# sentence and §17 this one entry. Stripped before hashing like the 5.0.0 and 14.0.0 sentences; both and the new
# digests are pinned by tests/test_agents_policy_15_0_0_disk_hygiene.py.
RULE_6_EXCEPTION_15_0_0 = (
    "\n   One exception, binding only once AGENTS.md 15.0.0 is ACTIVE: the n8n lane `disk-hygiene` may"
    "\n   remove the reclaimable items its reviewed rules select (scripts/disk_hygiene.py,"
    "\n   config/disk_hygiene_rules.json), and nothing else (AGENTS.md §24.12)."
)
S17_ENTRY_15_0_0 = (
    " **changing the disk-hygiene rules or never-touch list** (§24.12 — a `config-write` grant and a reviewed PR) ·"
)
PINNED_SECTIONS = {
    "§0": (
        "# 0 · If you read nothing else",
        "# 1 · Identity and responsibilities",
        "61fe9dfbeaa3c61cf354e42ed1cdc6f7006a105b46d538cd79a74407f349af32",
    ),
    "§2": ("# 2 · Authority rails", "# 2A ·", "5fd247be2571bd2a8c75d4c789bf1f0b59a1068817ed8d541b852b24a512c2af"),
    "§2A": ("# 2A ·", "# 2B ·", "38c78841b9b7cc3bf8ef3dea6be825ad5f892a6d4c7c8209404e4ef3855b79bb"),
    "§7A": ("# 7A ·", "# 8 ·", "6d20888d1329397351c75a54a4c3e2e7978d5974cef6c3c306dc708580b5ca90"),
    "§17": (
        "# 17 · Operator-only decisions",
        "# 17A ·",
        "f61b30d248331b2ee11e950cc8f455a273608d52d1eba3de6fca191b98e5f2f5",
    ),
}


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
    block = block.replace(RULE_2_EXCEPTION_5_0_0, "")  # operator-requested amendment 5.0.0; see the constant
    block = block.replace(RULE_2_EXCEPTION_14_0_0, "")  # operator-requested amendment 14.0.0; see the constant
    block = block.replace(RULE_6_EXCEPTION_15_0_0, "").replace(S17_ENTRY_15_0_0, "")  # 15.0.0; see the constants
    # §7A embeds a GENERATED table (render_source_of_truth.py); mask it so only rule text is pinned — same mask as
    # the 4.1.0/4.3.0/4.4.0 pins (operator 2026-10-10 'Yes, from one to six', item 5; PR #1678).
    return re.sub(
        r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)",
        r"\1\n<generated>\n\2",
        block,
        flags=re.S,
    )


def _s24() -> str:
    m = re.search(r"^# 24 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§24 missing"
    return m.group(0)


def _row() -> re.Match:
    m = re.search(r"^\| 4\.6\.0 \| 2026-10-10 \| (PROPOSED|ACTIVE)[^|]* \| MINOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 4.6.0 | 2026-10-10 | PROPOSED|ACTIVE | MINOR |` version row"
    return m


# ---------------------------------------------------------------------------------------- header + row


def test_header_is_4_6_0_proposed_or_later():
    assert _version() >= (4, 6, 0)
    if _version() == (4, 6, 0) and _control("Status") == "PROPOSED":
        assert _control("Effective-Date") == "PENDING"
        assert "4.6.0 is PROPOSED (MINOR)" in _flat(AGENTS[:12000])


def test_version_row_waits_for_the_operator_with_the_exact_phrase():
    status, rest = _row().group(1), _row().group(2)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I), "a PROPOSED 4.6.0 must not claim a prior token"
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{7,40}}", rest), "ACTIVE 4.6.0 row must record token, PR and sha"


def test_banner_states_the_numbering_dependency_and_the_class_reasoning():
    start = AGENTS.index("**4.6.0 is ")  # PROPOSED until ratified; ACTIVE after (#1682, 694350602)
    f = _flat(AGENTS[start : AGENTS.index("**4.3.0 is ACTIVE", start)])
    # #1666 (4.4.1 + 4.5.0) merged as dd8f4cff1; the banner now names that merge instead of "renumbers to 4.5.0".
    assert "PR #1666" in f and "dd8f4cff1" in f and "settled at ratification" in f and "becomes 5.0.0" in f
    assert "316700266" in f
    # 4.6.0 supersedes 4.5.0; 5.0.0 (#1686) supersedes 4.6.0; 5.1.0 supersedes 5.0.0; 5.2.0 (PROPOSED) supersedes 5.1.0;
    # 10.0.0 (ACTIVE, ratified on #1736) supersedes 7.0.0; 14.0.0 (ratified on #1838) supersedes 12.0.0;
    # 15.0.0 (ratified on #1852) supersedes 14.0.0; 16.0.0 (PROPOSED, header block set by its patch) supersedes 15.0.0.
    supersedes = {(4, 6, 0): "4.5.0", (5, 0, 0): "4.6.0", (5, 1, 0): "5.0.0", (5, 2, 0): "5.1.0", (10, 0, 0): "7.0.0", (11, 0, 0): "10.0.0", (12, 0, 0): "11.0.0", (14, 0, 0): "12.0.0", (15, 0, 0): "14.0.0", (16, 0, 0): "15.0.0"}
    # 17.0.0 (PROPOSED, header block set by its patch) supersedes the last ACTIVE version: 15.0.0 while 16.0.0 is
    # PROPOSED, 16.0.0 once it is ratified.
    # 18.0.0 (PROPOSED, header block set by its operator-applied patch) supersedes 17.0.0 (ACTIVE, #1914).
    # 18.1.0 (PROPOSED MINOR, §7 time-settings trap, operator-applied patch) supersedes 18.0.0.
    allowed = {(17, 0, 0): {"15.0.0", "16.0.0"}, (18, 0, 0): {"17.0.0"}, (18, 1, 0): {"18.0.0"}}.get(
        _version(), {supersedes.get(_version(), "5.1.0")})
    assert _control("Supersedes") in allowed
    assert f"{TOKEN} <pr_number> <head_sha>" in f


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


# ------------------------------------------------------------------------- what must not move


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


def test_claude_md_adapter_restates_no_new_rule():
    # The adapter repeats §0 verbatim, so once 5.0.0 is ratified it carries the rule 2 sentence; not a new rule.
    text = (
        (ROOT / "CLAUDE.md").read_text(encoding="utf-8").replace(RULE_2_EXCEPTION_5_0_0, "").replace(RULE_2_EXCEPTION_14_0_0, "")
        .replace(RULE_6_EXCEPTION_15_0_0, "")
    )
    assert "n8n" not in text.lower() and "§24" not in text


# ------------------------------------------------------------------------------------------ §24


def test_24_has_nine_subsections_each_citing_its_cause():
    s = _s24()
    nums = re.findall(r"^## (24\.\d+) ", s, re.M)
    # 5.0.0 (PROPOSED, operator-requested 2026-10-10) appends §24.10; 14.0.0 (PROPOSED, operator-requested
    # 2026-10-16) appends §24.11; 15.0.0 (PROPOSED, operator-directed 2026-10-18) appends §24.12; 4.6.0 still owns
    # exactly 24.1–24.9.
    assert nums in [[f"24.{i}" for i in range(1, n)] for n in (10, 11, 12, 13)], nums
    for part in re.split(r"^## 24\.\d+ ", s, flags=re.M)[1:]:
        bullets = re.split(r"\n- ", part)[1:]
        assert bullets, part[:80]
        assert all("*Cause (§20):" in _flat(b) for b in bullets), part[:80]


def test_24_is_outside_the_n8n_carve_out_and_grants_nothing():
    head = _flat(_s24()[:1500])
    assert "not** part of the §23 n8n carve-out" in head
    assert "§0, §2, §2A, §7A, §17 and §23.14 are byte-identical" in head
    assert "grants n8n, a lane or an agent anything" in head


def test_24_carries_the_numbers_the_operator_ruled():
    f = _flat(_s24())
    for frag in (
        "$20/month",
        "$18",
        "$15",
        "$12",
        "scalp 50%",
        "23 requests a day",
        "2,357",
        "TRADE_AI_CI=1",
        "ReleaseGrantBinding@v1",
        "dof_app",
        "Supabase",
        "BrokerReadEnvelope@v1",
        "DIRECT_READ_ROSE",
        "The P1 path does not depend on n8n",
        "only sender",
    ):
        assert frag in f, frag


def test_braveapi_row_in_12_is_corrected():
    row = next(line for line in AGENTS.splitlines() if line.startswith("| `braveapi` |"))
    assert "2,357" in row and "§24.2" in row
    assert "the product this project pays for" not in row


def test_scripts_and_configs_the_rules_name_exist():
    for rel in (
        "scripts/lib/release_grant_binding.py",
        "scripts/check_comms_gateway_enforcement.py",
        "scripts/check_data_source_authority.py",
        "scripts/new-worktree.sh",
        "scripts/incident_notifier.py",
        "scripts/n8n_siem_bridge.py",
        "scripts/lib/data_broker/finviz_enrichment_snapshot.py",
        "config/comms_categories.yaml",
        "config/telegram_chokepoint_baseline.json",
        "config/provider_chokepoint_baseline.json",
        "docs/architecture/gateway-enforcement.md",
    ):
        assert (ROOT / rel).exists(), rel


def test_release_binding_refuses_a_generic_grant_as_24_8_says():
    from scripts.lib import release_grant_binding as RGB

    assert RGB.SCHEMA == "ReleaseGrantBinding@v1"
    act = RGB.ReleaseAction(action="promote", target_sha="e8a4a6815524d7466fc43a894e06b347e1ebc2c5")
    assert RGB._names_action("generic overnight release grant", act) == []
    assert RGB._names_action("Release main e8a4a6815524 (#1665 merge)", act)
