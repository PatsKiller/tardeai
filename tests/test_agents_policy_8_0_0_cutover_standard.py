"""AGENTS.md 8.0.0 (PROPOSED, MAJOR) — §23.21 the n8n cutover standard; multi-day soaks removed.

Operator 2026-10-14 ~11:05 ET, verbatim: "new standards apply when i say so fix and dry and regression testing, yes it
should run live successful to many road blocks to testing". Pins, all hermetic (source text only):

* the policy record: header 8.0.0 PROPOSED / PENDING, one version row awaiting APPROVE_AGENTS_POLICY_8_0_0, the
  banner and §23.21 with its four criteria, the forced-live-fire window rule, the removed soaks and the unchanged rails;
* §23.3 and §23.14: the trade-ai-scalp-live "3 market days" fallback is replaced in place by a pointer to §23.21, and
  §23.14 differs from its 4.1.0 text by exactly that one clause (new digest pinned here; the older tests reverse the
  clause and keep the 4.1.0 digest);
* §8.1 no longer lists onboarding step 8 or the scalp soak among natural-evidence gates; §23.12 points at §23.21;
* §0, §2, §2A, §7A and §17 are byte-identical to the 5.2.0 pins; the state checker passes on a branch and on main.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_agents_policy_state as STATE  # noqa: E402
from tests.test_agents_policy_5_2_0_validation import (  # noqa: E402
    CLAUSE_23_14_8_0_0,
    CLAUSE_23_14_PRE_8_0_0,
    PINNED_SECTIONS,
    SECTION_23_14_SHA256,
    _section,
)

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_8_0_0"
OPERATOR_WORDS = (
    "new standards apply when i say so fix and dry and regression testing, yes it should run live successful to many "
    "road blocks to testing"
)
#: §23.14 after 8.0.0: the 4.1.0 text with exactly CLAUSE_23_14_PRE_8_0_0 → CLAUSE_23_14_8_0_0.
SECTION_23_14_8_0_0_SHA256 = "cf01f406204865c06a6afc128e5a727cc7d07d5fbd1820b0fb0c42935b1590dd"


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _row() -> re.Match:
    m = re.search(r"^\| 8\.0\.0 \| 2026-10-14 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 8.0.0 | 2026-10-14 | PROPOSED|ACTIVE | MAJOR |` row"
    return m


def _sub(num: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S)
    assert sec
    m = re.search(rf"^## {re.escape(num)} .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m, num
    return m.group(0)


def _s81() -> str:
    return _flat(AGENTS[AGENTS.index("## 8.1 Working means validated now"): AGENTS.index("# 8A · Testing standards")])


# ------------------------------------------------------------------------------------------------ the record


def test_header_and_row_agree_and_wait_for_the_operator():
    status, rest = _row().groups()
    if _control("Policy-Version") == "8.0.0":
        assert _control("Status") == status
        if status == "PROPOSED":
            assert _control("Effective-Date") == "PENDING"
            assert _control("Supersedes") in ("5.1.0", "7.0.0")
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I)
    for frag in ("Operator-directed 2026-10-14", "§23.21", "tests/test_agents_policy_8_0_0_cutover_standard.py",
                 "§0, §2, §2A, §7A, §17 byte-identical", "§23.14 changes by exactly one clause"):
        assert frag in rest, frag


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_banner_quotes_the_operator_and_states_the_class():
    banner = _flat(AGENTS[AGENTS.index("**8.0.0 is "): AGENTS.index("**7.0.0 is ")])
    for frag in ("PROPOSED (MAJOR)", OPERATOR_WORDS, "Why MAJOR", "removes a restriction", "It grants nothing",
                 "§23.14 changes by one clause", "2026-10-12T23:59:59-04:00", "#1697", "#1725",
                 f"{TOKEN} <pr_number> <head_sha>"):
        assert frag in banner, frag


# ------------------------------------------------------------------------------------------------- §23.21


def test_23_21_states_the_four_criteria():
    s = _flat(_sub("23.21"))
    assert OPERATOR_WORDS in s
    for frag in (
        "(1) **Defect fixed.**",
        "merged and served from CURRENT",
        "(2) **n8n dry run passes.**",
        "A forced `dry_run` fire through `coordination/run` counts (§8.1); no natural shadow slot is required",
        "(3) **Lane regression tests pass** under `TRADE_AI_CI=1`",
        "(4) **At least one successful `live` n8n run with the cron line still present under the shared lock.**",
        "the allowlist lock equal to the cron line's lock",
        "A `RUN_SKIPPED_LOCK` is not this run",
        "A forced `live` relay fire counts when the lane's window allows it",
        "never with the gate overridden",
    ):
        assert frag in s, frag


def test_23_21_removes_soaks_and_keeps_the_rails():
    s = _flat(_sub("23.21"))
    for frag in (
        "No multi-day soak is a cutover condition.",
        "3 market days of `RUN_DONE` with no `trade-ai-scalp-live:STALLED` finding",
        "step 8",
        "N clean days",
        "§23.14 — broker, order, secret and daemon lanes are never dispatcher-eligible",
        "never deletes it (§0 rail 6, §23.2)",
        "one `cron` grant per wave naming every lane id",
        "rollback per line",
        "monitored, not awaited",
        "the program window ended 2026-10-12T23:59:59-04:00",
    ):
        assert frag in s, frag


# ------------------------------------------------------------------------------ the in-place replacements


def test_23_3_scalp_fallback_points_at_23_21():
    s = _flat(_sub("23.3"))
    assert "3 market days" not in s
    assert ("The cron line stays live as the fallback until the lane meets the §23.21 cutover standard (8.0.0) — one "
            "successful in-window `live` n8n run with the cron line present under that lock") in s


def test_23_14_differs_from_4_1_0_by_exactly_one_clause():
    block = _sub("23.14").rstrip("\n").rstrip("-").rstrip("\n")
    assert block.count(CLAUSE_23_14_8_0_0) == 1 and CLAUSE_23_14_PRE_8_0_0 not in block
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_14_8_0_0_SHA256
    reverted = block.replace(CLAUSE_23_14_8_0_0, CLAUSE_23_14_PRE_8_0_0)
    assert hashlib.sha256(reverted.encode("utf-8")).hexdigest() == SECTION_23_14_SHA256
    f = _flat(block)
    for frag in ("**Broker, order, secret and daemon lanes are never dispatcher-eligible.**",
                 "No other ingest writer or sender becomes dispatcher-eligible by analogy",
                 "No amendment made inside a program window can change this; it needs a new MAJOR."):
        assert frag in f, frag


def test_8_1_and_23_12_point_at_23_21():
    f = _s81()
    assert "three clean market days" not in f and "step 8" not in f
    assert "its readiness is the §23.21 cutover standard (8.0.0)" in f
    assert "§23.12, last bullet" in f
    s = _flat(_sub("23.12"))
    assert "A lane joins the cutover when it meets the §23.21 cutover standard (8.0.0, PROPOSED); no soak precedes it." in s


def test_rails_are_byte_identical():
    for name, (start, end, digest) in PINNED_SECTIONS.items():
        block = _section(AGENTS, start, end)
        assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"


def test_no_rule_text_outside_history_still_states_the_scalp_soak():
    # Banners and version-history rows are records of earlier versions and keep their words; rule text may not.
    body = AGENTS[AGENTS.index("# 0 · If you read nothing else"): AGENTS.index("# Version history")]
    rules = _flat(body)
    assert "until 3 clean market days" not in rules
    assert "until n8n has 3 market days" not in rules
    assert "three clean market days with cron as fallback" not in rules


def test_adapters_carry_nothing_from_8_0_0():
    for rel in ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints"):
        p = ROOT / rel
        if p.exists():
            text = p.read_text(encoding="utf-8")
            assert "8.0.0" not in text and "§23.21" not in text, rel
