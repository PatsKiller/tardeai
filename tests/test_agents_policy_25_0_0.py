"""AGENTS.md 25.0.0 (MAJOR) — consolidation: owner clause, one-tap digest, deploy delegation, no self-review.

Pins, read hermetically from the repository text (no network, no live store):
  * header 25.0.0, PROPOSED with Effective-Date PENDING until the operator's token, then ACTIVE (ratifying commit);
  * §0 comes first after the header and banner; earlier banners live in the Version history appendix;
  * §0 rule 3 (canonical checkout, hooks) and rule 4 (non-main pushes) in AGENTS.md and every adapter;
  * §20 owner clause and the MAJOR/role-authority approval rule; the Command Center ratification path;
  * §25.10 digest "Approve all" bound to head SHAs, held classes, deploy without a per-SHA grant, SOFT refused,
    stuck deploys page, coordinator emergency only on the operator's own instruction;
  * the release train is gone from the binding text (operator 2026-10-27);
  * §23.19 / §28.15 item 10 no self-review; §29 paid and LLM run discipline;
  * check_agents_policy_state.py fails an AGENTS.md change without a version bump (rule 5);
  * the Rulebook projection renders every numbered section, and the stale 5.2.0 / 4.2.0 citations are fixed.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
AIWP = (ROOT / "AI_WORK_POLICY.md").read_text(encoding="utf-8")
ADAPTERS = [ROOT / "CLAUDE.md", ROOT / ".cursor/rules/00-tradeai-work-policy.mdc",
            ROOT / ".github/copilot-instructions.md", ROOT / ".goosehints"]
VH = AGENTS.index("\n# Version history")
BINDING = AGENTS[:VH]


def _control() -> dict[str, str]:
    m = re.search(r"```\n(Policy-Version:.*?)```", AGENTS, re.DOTALL)
    assert m
    return {k.strip(): v.strip() for k, v in (ln.split(":", 1) for ln in m.group(1).splitlines() if ":" in ln)}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _section(start: str, end: str) -> str:
    """The section text with line wraps flattened, so pins survive re-wrapping."""
    a = AGENTS.index(start)
    return _flat(AGENTS[a:AGENTS.index(end, a + len(start))])


def _checker():
    spec = importlib.util.spec_from_file_location("aps25", ROOT / "scripts/check_agents_policy_state.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------------------------- header / layout
def test_header_is_25_0_0_proposed_or_active():
    cb = _control()
    # 25.0.x PATCHes (e.g. 25.0.1, the generated §7A table refresh) keep the 25.0.0 rules.
    assert re.fullmatch(r"25\.0\.\d+", cb["Policy-Version"]), cb["Policy-Version"]
    assert cb["Supersedes"] in {"24.0.0"} | {f"25.0.{n}" for n in range(int(cb["Policy-Version"].rsplit(".", 1)[1]))}
    assert cb["Last-Reviewed"].startswith("2026-10-27")
    row = re.search(r"^\| 25\.0\.0 \| 2026-10-2\d \| (PROPOSED|ACTIVE)[^|]*\| MAJOR \|(.*)$", AGENTS, re.M)
    assert row, "no 25.0.0 MAJOR history row"
    assert cb["Status"] == row.group(1)
    if cb["Status"] == "PROPOSED":
        assert cb["Effective-Date"] == "PENDING"
        assert "25.0.0 is PROPOSED (MAJOR)" in AGENTS[:6000]
        assert "PENDING" in row.group(2) and "APPROVE_AGENTS_POLICY_25_0_0" in row.group(2)
    else:
        assert re.fullmatch(r"2026-1\d-\d\d", cb["Effective-Date"])
        assert "25.0.0 is ACTIVE (MAJOR)" in AGENTS[:6000]


def test_section_0_comes_first_and_banners_are_in_the_appendix():
    s0 = AGENTS.index("# 0 · If you read nothing else")
    assert s0 < 6000, "§0 must follow the header and the current banner"
    assert s0 < AGENTS.index("# Document version policy") < AGENTS.index("# 1 · Identity and responsibilities")
    for banner in ("**24.0.0 is ACTIVE (MAJOR)", "**21.0.0 is ACTIVE (MAJOR)", "**4.4.0 is ACTIVE (MAJOR)",
                   "**1.3.0 is ACTIVE from 2026-09-27"):
        assert AGENTS.index(banner) > VH, banner
    assert "## Version banners (moved here from the top of the file by 25.0.0; history, not binding)" in AGENTS
    for gone in ("**17.0.0 is ACTIVE (MAJOR)", "**22.0.0 is ACTIVE (MAJOR)"):
        assert gone not in AGENTS


# ---------------------------------------------------------------------------------------------- §0 and adapters
RULE3_ADD = "Never skip a hook: no `--no-verify`, no `core.hooksPath` or other hook-disabling override."
RULE3_TREE = "Never edit, stage or commit in the canonical checkout the host runs from"
RULE4_ADD = "non-`main` branches within the push budget (AGENTS.md §28.15 item 8); `main` never."


def test_section_0_rules_3_and_4():
    s0 = _section("# 0 · If you read nothing else", "# Document version policy")
    for frag in (RULE3_ADD, RULE3_TREE, "saves stray edits there to a patch", RULE4_ADD, "`MBI_BEHAVIOR = 0`"):
        assert frag in s0, frag


def test_adapters_carry_rules_3_and_4():
    for adapter in ADAPTERS:
        text = adapter.read_text(encoding="utf-8")
        for frag in (RULE3_ADD, RULE3_TREE, RULE4_ADD):
            assert frag in text, f"{adapter.name}: {frag}"


# ---------------------------------------------------------------------------------------------- §20
def test_owner_clause_and_approval_rule():
    s20 = _section("# 20 · Amending this file", "# 21 · Working style")
    assert "The operator owns this file and may direct any agent (25.0.0)." in s20
    assert "except the §0 rules on orders, stops and sizing (rule 1), broker writes (rule 2) and secrets" in s20
    assert "records the instruction verbatim" in s20
    assert "every MAJOR change and any change to §0, §2 (authority rails), §17 (operator-only) or" in s20
    assert "the role authority profiles" in s20
    assert "Everything else is a normal PR." not in s20
    assert "`policy:<PR>`" in s20 and "STORE_APPROVAL_PENDING" not in s20
    assert "posts the token as a PR comment" in s20


def test_version_policy_requires_a_bump():
    dvp = _section("# Document version policy", "# 1 · Identity and responsibilities")
    assert "Every change to this file bumps the version, and CI checks it (25.0.0)." in dvp
    assert "scripts/check_agents_policy_state.py --base origin/main" in dvp


# ---------------------------------------------------------------------------------------------- §25.10
def test_25_10_one_tap_digest_and_held_classes():
    s = _section("## 25.10 Mergify merges, the host promotes (25.0.0)", "# 26 · Data foundation")
    for frag in ('"Approve all" in the digest is the operator\'s merge approval.',
                 "each bound to the head SHA the digest showed",
                 "returns in the next digest",
                 "Held classes are never in \"Approve all\".",
                 "`config/merge_hold_paths.json`",
                 "`AGENTS.md`, `AI_WORK_POLICY.md`",
                 "`bin/guard`",
                 "`.mergify.yml`, `.github/`",
                 "no merge Monday to Friday 09:30–16:15 ET",
                 "`PR_MERGE_BOOTSTRAP_GH_MERGE` path is retired",
                 "#2208"):
        assert frag in s, frag


def test_25_10_deploy_delegation_soft_stuck_and_emergency():
    s = _section("## 25.10 Mergify merges, the host promotes (25.0.0)", "# 26 · Data foundation")
    for frag in ("with no SHA-named `release-write` grant",
                 "`TRADEAI_DEPLOY_DELEGATION_SOFT=1` is refused unless `TRADE_AI_CI=1`",
                 "stuck with `main` ahead of CURRENT",
                 "pages P1",
                 "`STOP.json` latch and `GlobalReleaseLock`",
                 "A coordinator agent may run it only on the operator's explicit instruction given in that "
                 "coordinator's own session (§28.4), quoted verbatim in the receipt"):
        assert frag in s, frag
    s248 = _section("## 24.8 A release grant names", "## 24.9 Portability")
    assert "The deploy poller needs no grant; the emergency path does (25.0.0, §25.10)." in s248


def test_release_train_is_gone_from_binding_text():
    for gone in ("## 25.1 ", "## 25.2 ", "## 25.9 ", "release_train.run_now", "ReleaseCapability@v1",
                 "refs/heads/train/", "Release train (17.0.0, §25):", "Release train Run now (22.0.0",
                 "solo train", "train_self", "TRAIN_CONTROLLER"):
        assert gone not in BINDING, gone
    assert "| 17.0.0 | 2026-10-21 | RETIRED 2026-10-27 |" in AGENTS
    assert "| 22.0.0 | 2026-10-25 | RETIRED 2026-10-27 |" in AGENTS
    assert "Release train retired 2026-10-27 by operator; replaced by §25.10." in AGENTS
    assert "RELEASE TRAIN PUSHES" not in AIWP and "train/<train_id>" not in AIWP


# ---------------------------------------------------------------------------------------------- self-review, §29
def test_no_self_review():
    s2319 = _section("## 23.19 Every n8n addition", "## 23.20 ")
    assert "by a reviewer whose id differs from the author" in s2319
    assert "a team label is not a reviewer" in s2319
    s2815 = _section("## 28.15 Hands-off delivery", "# 29 · Paid and LLM run discipline")
    assert "- **10 No self-review (25.0.0).**" in s2815
    assert "the operator's own merge; reviews alone never merge them" in s2815
    assert "The coordinator push override (item 1) never applies to a held-class PR." in s2815


def test_section_29_run_discipline():
    s29 = _section("# 29 · Paid and LLM run discipline (25.0.0)", "# Version history")
    for frag in ("Preflight every limit before a long paid or LLM job.", "credit journal", "database spend backstop",
                 "process cost cap", "daily call cap", "global daily provider cap", "search budget",
                 "A data-quality gate runs before any model call.", "ticker-collision checks"):
        assert frag in s29, frag


def test_stale_proposed_citations_fixed():
    assert "(§8.1, 5.2.0)" not in BINDING and "§8.1 (5.2.0)" not in BINDING
    assert "reserved for 4.2.0" not in BINDING
    assert re.search(r"^\| 5\.2\.0 \| 2026-10-11 \| WITHDRAWN", AGENTS, re.M)


# ---------------------------------------------------------------------------------------------- checker rule 5
def test_checker_fails_a_change_without_a_bump():
    mod = _checker()
    base = AGENTS
    edited = AGENTS.replace("# 21 · Working style", "# 21 · Working style\n\nAn unversioned edit.", 1)
    errors = mod.check_bump(edited, base)
    assert any("Policy-Version is still" in e for e in errors)
    assert any("Last-Reviewed did not" in e for e in errors)
    assert mod.check_bump(AGENTS, AGENTS) == []
    assert mod.check_bump(AGENTS, None) == []


def test_checker_accepts_this_bump_against_24_0_0():
    mod = _checker()
    base = re.sub(r"^Policy-Version:.*$", "Policy-Version:      24.0.0", AGENTS, count=1, flags=re.M)
    base = re.sub(r"^Last-Reviewed:.*$", "Last-Reviewed:       2026-10-26T10:25:00-04:00", base, count=1, flags=re.M)
    assert mod.check_bump(AGENTS, base) == []
    assert mod.check(AGENTS, on_main=False) == []


# ---------------------------------------------------------------------------------------------- Rulebook
def test_rulebook_projection_renders_every_numbered_section():
    sys.path.insert(0, str(ROOT))
    from scripts.lib import operator_approvals as core

    proj = core.policy_projection(AGENTS, source_sha="0" * 40)
    assert re.fullmatch(r"25\.0\.\d+", proj["policy_version"])
    headings = [ln[2:].strip() for ln in BINDING.splitlines()
                if re.match(r"^# (\d+[A-Z]? ·|Document version policy|Multi-Agent SOP)", ln)]
    missing = [h for h in headings if h not in proj["section_counts"]]
    assert not missing, missing
    assert proj["sections"][0].startswith("0 ·")
    assert all(r["text"].strip() for r in proj["rules"])
    assert not any(r["section"] == "Version history" for r in proj["rules"])


def test_adapters_repeat_section_0_rules_verbatim():
    """§0 says its rules are repeated verbatim in every adapter; 25.0.0 changed rules 3 and 4, so check all eleven."""
    s0 = AGENTS[AGENTS.index("# 0 · If you read nothing else"):AGENTS.index("# Document version policy")]
    rules = s0[s0.index("1. **`MBI_BEHAVIOR = 0`.**"):].rstrip().rstrip("-").rstrip()
    for adapter in ADAPTERS:
        assert rules in adapter.read_text(encoding="utf-8"), adapter.name


def test_28_16_incidents_no_silent_drop():
    s = _section("## 28.16 Incidents: no silent drop (25.0.0)", "# 29 · Paid and LLM run discipline")
    for frag in ("`data/coordination/incidents/`", "`IncidentRecord@v1`", "(`open`, `fixing`, `fixed` or `blocked`)",
                 "never ends a task with it `open`", "sets `blocked` with the reason and a handoff",
                 "Host watchers open incidents automatically", "a dirty canonical checkout",
                 "It never merges, promotes or touches a §0 or held class.", "Ops → Incidents",
                 "daily one-line Telegram summary", "Items 1 and 2 bind every agent on ratification",
                 "being built, PR to follow"):
        assert frag in s, frag
