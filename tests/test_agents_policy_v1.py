"""AGENTS.md policy v1.0.0 — structural and authority guarantees.

The constitution is the one document every adapter defers to. Nothing enforces
its shape, so it accumulated: two sections numbered 13.5, two different sections
both numbered 13.6, two "Where things go" tables, and no version at all. A
standard that only grows stops being read, and an unread standard is worse than
none because it still looks like coverage (AGENTS.md 20).

Asserted over parsed structure, not by eyeballing. Where a rule is about text,
comments and fenced blocks are handled explicitly rather than grepped blind.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ADAPTERS = (
    ROOT / "CLAUDE.md",
    ROOT / ".cursor" / "rules" / "00-tradeai-work-policy.mdc",
    ROOT / ".github" / "copilot-instructions.md",
)

REQUIRED_KEYS = (
    "Policy-Version", "Versioning-Scheme", "Policy-Schema", "Status",
    "Effective-Date", "Last-Reviewed", "Canonical-Repo-Path",
    "Drive-Mirror-Path", "Supersedes", "Approval-Class",
)


def _text() -> str:
    return AGENTS.read_text(encoding="utf-8")


def _flat() -> str:
    """Whitespace-normalized. A rule about CONTENT must not depend on where a
    line happens to wrap: `secret reads` is one phrase whether or not markdown
    broke it across two lines."""
    return " ".join(AGENTS.read_text(encoding="utf-8").split())


def _control_block() -> dict:
    """The first fenced block after the title, parsed as Key: Value."""
    t = _text()
    m = re.search(r"^# AGENTS\.md.*?\n+```\n(.*?)\n```", t, re.S | re.M)
    assert m, "no document-control block immediately below the title"
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


# ----------------------------------------------------------- canonical name --

def test_root_agents_md_is_the_constitution():
    assert AGENTS.is_file(), "root AGENTS.md must exist"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda p: p.name)
def test_adapters_resolve_to_root_agents_md(adapter):
    assert adapter.is_file(), f"{adapter} missing"
    assert "AGENTS.md" in adapter.read_text(encoding="utf-8"), (
        f"{adapter.name} must point at root AGENTS.md"
    )


def test_no_agents_nd_is_referenced_anywhere():
    """AGENTS.nd is a stale snapshot, never canonical.

    Scoped to files that could ROUTE a reader there. The maturity-program audit
    trail is excluded by design: it names AGENTS.nd in order to record that
    nothing points at it, and a test that cannot tell a pointer from an audit
    finding would make the audit unwritable.
    """
    hits = []
    for p in ROOT.rglob("*.md"):
        if ".git" in p.parts or "node_modules" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("docs/implementation/maturity-program/"):
            continue
        try:
            if "AGENTS.nd" in p.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(p.relative_to(ROOT)))
        except OSError:
            continue
    assert hits == [], f"AGENTS.nd referenced in {hits}"


# ---------------------------------------------------------------- versioning --

@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_control_block_carries_every_required_key(key):
    assert key in _control_block(), f"document-control block is missing {key}"


def test_policy_version_is_semver():
    v = _control_block()["Policy-Version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", v), f"not semver: {v!r}"


def test_first_baseline_supersedes_unversioned():
    """1.0.0, not 2.0.0: there is no prior formal 1.x to supersede."""
    cb = _control_block()
    if cb["Policy-Version"] == "1.0.0":
        assert cb["Supersedes"] == "UNVERSIONED"


def test_status_is_a_known_lifecycle_value():
    assert _control_block()["Status"] in {"PROPOSED", "ACTIVE", "SUPERSEDED"}


def test_control_block_carries_no_self_referential_hash():
    """A SHA of this file cannot live inside this file. It belongs in the mirror
    manifest, which is written after the content commit exists."""
    cb = _control_block()
    for k, v in cb.items():
        assert not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", v), (
            f"{k} looks like a self-referential commit/content hash: {v}"
        )


def test_version_history_current_row_matches_policy_version():
    t = _text()
    assert "# Version history" in t, "no version history table"
    v = _control_block()["Policy-Version"]
    assert re.search(rf"^\|\s*{re.escape(v)}\s*\|", t, re.M), (
        f"version history has no row for the current Policy-Version {v}"
    )


def test_document_version_policy_defines_all_three_change_classes():
    t = _text()
    assert "# Document version policy" in t
    for cls in ("MAJOR", "MINOR", "PATCH"):
        assert cls in t, f"version policy does not define {cls}"


# --------------------------------------------------------------- de-duplication --

def test_no_duplicate_numbered_sections():
    nums = re.findall(r"^#+ *(\d+(?:\.\d+)?[A-Z]?) ·", _text(), re.M)
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    assert dupes == [], f"duplicate numbered sections: {dupes}"


def test_subsections_of_13_are_in_ascending_order():
    """Removing the duplicated 13.5 stub exposed 13.4 -> 13.6 -> 13.5 -> 13.7."""
    nums = re.findall(r"^#+ *(13\.\d) ·", _text(), re.M)
    assert nums == sorted(nums), f"out of order: {nums}"


def test_where_things_go_appears_once():
    assert _text().count("## Where things go") == 1


def test_the_merge_kept_every_unique_rule():
    """Deduplication must not lose content. These lines each existed in exactly
    one of the two merged blocks."""
    t = _flat()
    for fragment in (
        "WAVE_<n>_<slug>",                        # naming, from the first table
        "never behavioural rules",                # skills rule, first table
        # The PROHIBITION itself, not just the enforcement that backs it.
        # Mutation M11 deleted this line while leaving `check_no_secrets.py`
        # intact and the suite stayed green: presence of a neighbour is not
        # presence of the rule.
        "Never sync `.env`, keys, or credentials",
        "check_no_secrets.py",                    # Drive secrets rule, first table
        "before rebuilding something that seems absent",   # archive row, second
        "indexed by the generator, not by hand",  # generator rule, second
    ):
        assert fragment in t, f"merge dropped: {fragment!r}"


# ------------------------------------------------------------ role authority --

ROLES = ("ADVISORY_AGENT", "EXECUTION_ENGINEERING_AGENT",
         "RELEASE_COORDINATOR", "LIVE_CANARY_CONTROLLER")


@pytest.mark.parametrize("role", ROLES)
def test_role_authority_profile_is_defined(role):
    assert role in _text(), f"role authority profile {role} missing"


def test_profiles_fail_closed_to_the_narrowest_role():
    t = _text()
    assert "resolves to `ADVISORY_AGENT`" in t, (
        "an unrecognised profile must fail closed to the narrowest role"
    )


def test_execution_engineering_is_defined_but_not_granted():
    t = _text()
    assert "defined but not granted" in t, (
        "EXECUTION_ENGINEERING_AGENT must be explicitly blocked until reconciled"
    )


DENIALS = (
    "no broker subsystem access",
    "no behavior writes",
    "no live credentials, endpoints, 2FA, deploy, live flags, or real broker calls",
    "no merge and no deploy without exact-SHA operator approval",
    "never an LLM agent",
)


@pytest.mark.parametrize("denial", DENIALS, ids=lambda d: d[:34])
def test_every_authority_denial_is_present(denial):
    """Mutation target. Removing any one of these must turn this red — a profile
    that quietly loses a denial is how authority migrates into an agent."""
    assert denial in _text(), f"authority denial removed: {denial!r}"


def test_no_profile_grants_operator_only_powers():
    t = _flat()
    assert "No profile grants" in t
    for power in ("broker execution", "2FA", "secret reads", "scheduler changes",
                  "live flags"):
        assert power in t, f"the no-profile-grants list omits {power!r}"


def test_amending_role_authority_requires_the_operator():
    t = _text()
    assert "Amending this section is operator-only" in t
    assert "OPERATOR_REQUIRED_FOR_SECTIONS_0_2_17_AND_ROLE_AUTHORITY" in t


# --------------------------------------------------------- safety floor intact --

@pytest.mark.parametrize("rail", (
    "MBI_BEHAVIOR",
    "BehaviorWriteRefused",
    "Never route around a permission denial",
    "Never delete.",
))
def test_the_universal_safety_floor_survived_the_edit(rail):
    assert rail in _text(), f"safety rail lost in the rewrite: {rail!r}"


def test_a_proposed_policy_is_not_dated_effective():
    """M12. `Status: PROPOSED` with a concrete `Effective-Date` asserts the
    policy is already in force while it is still awaiting approval. An absent
    approval must never render as an affirmative one (AGENTS.md 9.1)."""
    cb = _control_block()
    if cb["Status"] == "PROPOSED":
        assert cb["Effective-Date"] == "PENDING", (
            f"PROPOSED policy claims Effective-Date {cb['Effective-Date']!r}"
        )


def test_an_active_policy_carries_a_real_effective_date():
    """The pair of the PROPOSED rule. Flipping Status to ACTIVE while leaving
    Effective-Date PENDING would publish a policy that is in force on no date --
    the same absent-renders-affirmative defect, mirrored."""
    cb = _control_block()
    if cb["Status"] == "ACTIVE":
        assert cb["Effective-Date"] != "PENDING", (
            "ACTIVE policy still says Effective-Date: PENDING"
        )
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cb["Effective-Date"]), (
            f"Effective-Date is not an ISO date: {cb['Effective-Date']!r}"
        )
