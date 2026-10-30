"""AGENTS.md 26.0.0 (MAJOR) — consolidation: every true rule stated once; history, lessons and gaps moved out.

Pins, read hermetically from the repository text (no network, no live store):
  * header 26.0.x, PROPOSED with Effective-Date PENDING until the operator's token, then ACTIVE (ratifying commit);
  * §0 rules 2 and 6 carry no dead "binding only once" clause; rule 4 matches the pre-push hook; every adapter agrees;
  * the binding text carries no stale status lines, no release train and no "binding only once";
  * the "What never goes in this file" rule and its three homes exist, and every LESSONS id AGENTS.md cites resolves;
  * the runtime gates that read AGENTS.md (Ops Controls, the sudo window, the claim board, broker reads, R1) still find
    their rows and anchor headings — dropping a history row silently switches a surface off;
  * the generated §7A table is unchanged in shape, the strings older tests and tools pin survive, and the file stays
    small (the 25.0.1 file was 7,401 lines, about 31% binding rules — LESSONS L0-03);
  * check_agents_policy_state.py accepts this bump against the frozen 25.0.1 text.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support.agents_policy_frozen import FROZEN_26, FROZEN_26_DIR  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ADAPTERS = [ROOT / "CLAUDE.md", ROOT / ".cursor/rules/00-tradeai-work-policy.mdc",
            ROOT / ".github/copilot-instructions.md", ROOT / ".goosehints"]
GOV = ROOT / "docs" / "governance"
VH = AGENTS.index("\n# Version history")
BINDING = AGENTS[:VH]
#: Binding-text ceiling. 26.0.0 measured well under it; raising it is a PR that says why (version policy).
MAX_BINDING_LINES = 2600


def _control() -> dict[str, str]:
    m = re.search(r"```\n(Policy-Version:.*?)```", AGENTS, re.DOTALL)
    assert m
    return {k.strip(): v.strip() for k, v in (ln.split(":", 1) for ln in m.group(1).splitlines() if ":" in ln)}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _section0() -> str:
    start = AGENTS.index("# 0 · If you read nothing else")
    return AGENTS[start:AGENTS.index("\n---\n", start)]


def _checker():
    spec = importlib.util.spec_from_file_location("aps26", ROOT / "scripts/check_agents_policy_state.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _rows() -> dict[str, str]:
    return {v: s.strip() for v, s in re.findall(r"^\|\s*(\d+\.\d+\.\d+)\s*\|[^|]*\|\s*([^|]*)\|", AGENTS, re.M)}


# ---------------------------------------------------------------------------------------------- header / banner
def test_header_is_26_0_x_proposed_or_active():
    cb = _control()
    assert re.fullmatch(r"27\.\d+\.\d+", cb["Policy-Version"]), cb["Policy-Version"]
    if cb["Policy-Version"] == "26.0.0":
        assert cb["Supersedes"] == "25.0.1"
    elif cb["Policy-Version"] == "26.1.0":
        assert cb["Supersedes"] == "26.0.0"
    elif cb["Policy-Version"] in ("27.0.0", "27.0.1"):  # 27.0.0 was never ratified; 27.0.1 replaces it
        assert cb["Supersedes"] == "26.2.2"
    assert cb["Approval-Class"] == "OPERATOR_REQUIRED_FOR_SECTIONS_0_2_17_AND_ROLE_AUTHORITY"
    assert cb["Status"] in {"PROPOSED", "ACTIVE"}
    if cb["Status"] == "PROPOSED":
        assert cb["Effective-Date"] == "PENDING"
    else:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cb["Effective-Date"]), cb["Effective-Date"]
    row = _rows()[cb["Policy-Version"]]
    assert row.upper().startswith(cb["Status"]), (row, cb["Status"])


def test_banner_matches_header_and_section_0_comes_first():
    status = _control()["Status"]
    ver = _control()["Policy-Version"]
    # The banner names version + status + change class; the class is whatever the current version's
    # row declares (MAJOR for 26.0.x/26.1.0, PATCH for a 26.2.1 ratification), never a hardcoded MAJOR.
    assert f"**{ver} is {status} (" in AGENTS[:6000]
    s0 = AGENTS.index("# 0 · If you read nothing else")
    assert s0 < 6000
    assert s0 < AGENTS.index("# Document version policy") < AGENTS.index("# 1 · Identity and responsibilities")


# ---------------------------------------------------------------------------------------------- §0 and adapters
def test_section_0_has_no_dead_conditions():
    s0 = _section0()
    assert "binding only once" not in s0
    assert "One operational exception: with an operator `execution-ops` grant" in s0
    assert "One read-only exception: with an operator `broker-read` grant" in s0
    assert "Three exceptions, and nothing else" in s0
    assert "`MBI_BEHAVIOR = 0`" in s0 and "shorthand, not a variable" in s0


def test_rule_4_defers_the_number_to_the_hook():
    s0 = _flat(_section0())
    assert "within the per-branch budget the pre-push hook enforces (`AI_WORK_POLICY.md` §3)" in s0
    assert "Never push `main` or `release/*`, force-push, rewrite pushed history or delete a remote branch." in s0
    assert not re.search(r"budget of \d|\b\d+ pushes\b", s0), "rule 4 must not hard-code the budget"
    hook = (ROOT / "scripts/lib/tradeai_push_budget.py").read_text(encoding="utf-8")
    assert re.search(r"^MAX_WITHOUT_OVERRIDE\s*=\s*\d+", hook, re.M), "the number rule 4 points at lives in the hook"
    assert "MAX_WITHOUT_OVERRIDE" in (ROOT / "AI_WORK_POLICY.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda p: p.name)
def test_adapters_carry_the_26_0_0_section_0(adapter):
    text = adapter.read_text(encoding="utf-8")
    assert "binding only once" not in text, adapter.name
    body = _section0().split("\n", 1)[1].strip("\n")
    assert body in text, f"{adapter.name}: regenerate §0 from AGENTS.md"


# ---------------------------------------------------------------------------------------------- binding text is current
def test_binding_text_has_no_stale_status_or_dead_conditions():
    for gone in ("binding only once", "PROPOSED in 25.0.0", "Status: PROPOSED in", "until the PR lands",
                 "**17.0.0 is ACTIVE (MAJOR)", "**22.0.0 is ACTIVE (MAJOR)"):
        assert gone not in BINDING, gone
    # Only the version being proposed may say PROPOSED in a Status line (the ratifying-edit rule).
    for m in re.finditer(r"\*\*Status: (PROPOSED[^*]*)\*\*", BINDING):
        assert "26.0.0" in m.group(1), m.group(0)


def test_release_train_is_gone_from_binding_text():
    for gone in ("Run now", "release_train_policy.json", "train window", "train_merge", "release train is"):
        assert gone not in BINDING, gone


def test_binding_text_stays_small():
    n = BINDING.count("\n")
    assert n <= MAX_BINDING_LINES, f"binding text is {n} lines; history, lessons and gaps belong in docs/governance/"


# ---------------------------------------------------------------------------------------------- where things go
def test_what_never_goes_in_this_file_and_its_homes():
    flat = _flat(BINDING)
    assert "**What never goes in this file.**" in flat
    for home in ("docs/governance/LESSONS_LEARNED.md", "docs/governance/OPEN_ITEMS.md",
                 "docs/governance/AGENTS_HISTORY.md"):
        assert home in flat, home
        assert (ROOT / home).is_file(), home
    assert "## Where the 25.0.1 text went" in (GOV / "AGENTS_HISTORY.md").read_text(encoding="utf-8")


def test_every_cited_lesson_exists():
    lessons = (GOV / "LESSONS_LEARNED.md").read_text(encoding="utf-8")
    have = set(re.findall(r"^### (L[0-9A-Z]+-\d+) ·", lessons, re.M))
    cited = set(re.findall(r"LESSONS (L[0-9A-Z]+-\d+)", AGENTS))
    missing = sorted(cited - have)
    assert not missing, f"AGENTS.md cites lessons LESSONS_LEARNED.md does not define: {missing[:20]}"


def test_frozen_25_0_1_text_is_preserved():
    import hashlib

    name, digest = FROZEN_26["AGENTS.md"]
    data = (FROZEN_26_DIR / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    assert b"Policy-Version:      25.0.1" in data


# ---------------------------------------------------------------------------------------------- runtime gates
def test_runtime_gates_still_find_their_rows_and_anchors():
    from scripts.lib import ops_controls_core as occ

    agents = ROOT / "AGENTS.md"
    assert occ.policy_state(agents)["state"] == occ.POLICY_ACTIVE  # Ops Controls: 19.0.0 + §27.3
    sudo = occ.policy_state(agents, required="20.0.0", anchor="## 28.5 The Ops → Controls sudo window", or_later=True)
    assert sudo["state"] == occ.POLICY_ACTIVE
    rows = _rows()
    for v in ("4.3.0", "4.4.0", "14.0.0", "15.0.0", "19.0.0", "20.0.0", "25.0.0"):
        assert rows.get(v, "").upper().startswith("ACTIVE"), (v, rows.get(v))
    assert re.search(r"^\| 14\.0\.0 \| [^|]+\| ACTIVE", AGENTS, re.M), "broker_read_sync.policy_status reads this"
    for v, status in (("17.0.0", "RETIRED"), ("22.0.0", "RETIRED"), ("5.2.0", "WITHDRAWN"),
                      ("23.0.0", "RATIFIED")):
        assert rows.get(v, "").upper().startswith(status), (v, rows.get(v))


def test_every_version_has_exactly_one_row():
    found = re.findall(r"^\|\s*(\d+\.\d+\.\d+)\s*\|", AGENTS[VH:], re.M)
    dupes = sorted({v for v in found if found.count(v) > 1})
    assert not dupes, dupes
    for gap in ("4.2.0", "6.0.0", "8.0.0", "9.0.0", "12.1.0", "13.0.0", "20.4.0", "23.0.0"):
        assert gap in found, f"{gap} has no row (every version keeps one, LESSONS L0-16)"


# ---------------------------------------------------------------------------------------------- pinned strings
PINNED = (
    "MBI_BEHAVIOR", "BehaviorWriteRefused", "Never route around a permission denial", "Never delete.",
    "LLM_GLOBAL_DAILY_USD_CAP = 2.00", "ratified by the operator", "not a universally enforced control", "named debt",
    "Free-first is not advice, it is the order of operations", "WAVE_<n>_<slug>", "never behavioural rules",
    "Never sync `.env`, keys, or credentials", "check_no_secrets.py", "before rebuilding something that seems absent",
    "indexed by the generator, not by hand", "single source of truth for how agents work", "never duplicates it",
    "## 27.3 Safe direction one click; risky direction a passkey and a typed phrase",
    "## 28.5 The Ops → Controls sudo window",
    "<!-- SOURCE_OF_TRUTH_TABLE_START -->", "<!-- SOURCE_OF_TRUTH_TABLE_END -->",
)


@pytest.mark.parametrize("frag", PINNED)
def test_pinned_strings_survive(frag):
    assert frag in AGENTS, frag


def test_section_17_is_the_one_list_and_names_the_retired_channel():
    s17 = _flat(AGENTS[AGENTS.index("# 17 · Operator-only decisions"):AGENTS.index("# 17A · ")])
    assert "This is the one complete list" in s17
    assert "live broker authority (A4/A5)" in s17
    assert "never by Telegram `/approve`" in s17


def test_section_2a_treats_every_commit_as_public():
    s2a = _flat(AGENTS[AGENTS.index("# 2A · "):AGENTS.index("# 2B · ")])
    assert "Treat every commit as public" in s2a
    assert "sanitise_for_external" in s2a


# ---------------------------------------------------------------------------------------------- checker
def test_checker_accepts_this_bump_against_25_0_1():
    mod = _checker()
    base = (FROZEN_26_DIR / "AGENTS.md").read_text(encoding="utf-8")
    assert mod.check_bump(AGENTS, base) == []
    assert mod.check(AGENTS, on_main=False) == []


def test_rulebook_projection_renders_every_numbered_section():
    from scripts.lib import operator_approvals as core

    proj = core.policy_projection(AGENTS, source_sha="0" * 40)
    assert re.fullmatch(r"27\.\d+\.\d+", proj["policy_version"])
    headings = [ln[2:].strip() for ln in BINDING.splitlines()
                if re.match(r"^# (\d+[A-Z]? ·|Document version policy|Multi-Agent SOP)", ln)]
    missing = [h for h in headings if h not in proj["section_counts"]]
    assert not missing, missing
    assert not any(r["section"] == "Version history" for r in proj["rules"])
