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

Numbering: 4.4.1 / 4.5.0 are in open PR #1666. If this renumbers to 4.5.0, rename TOKEN and this file.
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


def _section(text: str, start: str, end: str) -> str:
    s = re.search(rf"^{re.escape(start)}", text, re.M)
    assert s, start
    e = re.search(rf"^{re.escape(end)}", text[s.start() + 1 :], re.M)
    assert e, end
    block = text[s.start() : s.start() + 1 + e.start()]
    block = block.replace(RULE_2_EXCEPTION_5_0_0, "")  # operator-requested amendment 5.0.0; see the constant
    # §7A embeds a GENERATED table (render_source_of_truth.py); mask it so only rule text is pinned — same mask as
    # the 4.1.0/4.3.0/4.4.0 pins (operator 2026-10-10 'Yes, from one to six', item 5; PR #1678).
    return re.sub(r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)", r"\1\n<generated>\n\2", block, flags=re.S)


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
    start = AGENTS.index("**4.6.0 is PROPOSED (MINOR)")
    f = _flat(AGENTS[start : AGENTS.index("**4.3.0 is ACTIVE", start)])
    assert "PR #1666" in f and "renumbers to 4.5.0" in f and "becomes 5.0.0" in f
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
    block = m.group(0).rstrip("\n").rstrip("-").rstrip("\n")
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_14_SHA256


def test_claude_md_adapter_restates_no_new_rule():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "n8n" not in text.lower() and "§24" not in text


# ------------------------------------------------------------------------------------------ §24


def test_24_has_nine_subsections_each_citing_its_cause():
    s = _s24()
    nums = re.findall(r"^## (24\.\d+) ", s, re.M)
    # 5.0.0 (PROPOSED, operator-requested 2026-10-10) appends §24.10; 4.6.0 still owns exactly 24.1–24.9.
    assert nums in ([f"24.{i}" for i in range(1, 10)], [f"24.{i}" for i in range(1, 11)]), nums
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
