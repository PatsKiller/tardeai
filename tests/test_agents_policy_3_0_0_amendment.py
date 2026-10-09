"""AGENTS.md 3.0.0 — governed LLM and Agent capability in n8n (§23 amendment), PROPOSED 2026-10-09.

The failure this guards against: an authority-widening amendment that reads as a grant before it is
ratified, or loses the preconditions that make it safe. While 3.0.0 is PROPOSED the control block must
say PENDING and supersede 2.0.1; the version row must carry the pending token; §23 must name Agent
nodes, governance parity and the precondition checklist; the five operator decisions of 2026-10-09
must be present; and the stale "2.0.0 is PROPOSED" sentence (audit C G11) must not come back.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ADR = (ROOT / "docs/architecture/n8n/ADR_COORDINATION_SECRETS.md").read_text(encoding="utf-8")


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _version() -> tuple[int, ...]:
    return tuple(int(x) for x in _control("Policy-Version").split("."))


def _section_23() -> str:
    m = re.search(r"^# 23 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m, "§23 not found"
    return m.group(0)


def _subsection(number: str) -> str:
    m = re.search(rf"^## {re.escape(number)} .*?(?=^## |^---$)", _section_23(), re.M | re.S)
    assert m, number
    return m.group(0)


def _flat(text: str) -> str:
    """Prose is wrapped at ~100 columns; compare with whitespace collapsed."""
    return re.sub(r"\s+", " ", text)


def test_header_is_3_0_0_proposed_or_later():
    assert _version() >= (3, 0, 0)
    if _version() == (3, 0, 0) and _control("Status") == "PROPOSED":
        assert _control("Effective-Date") == "PENDING"
        assert _control("Supersedes") == "2.0.1"


def test_version_row_is_major_and_names_the_token_and_evidence():
    m = re.search(r"^\| 3\.0\.0 \| 2026-10-09 \| (\w+) \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no 3.0.0 MAJOR version row"
    status, rest = m.group(1), m.group(2)
    assert status in {"PROPOSED", "ACTIVE"}
    if status == "PROPOSED":
        assert "PENDING" in rest and "APPROVE_AGENTS_POLICY_3_0_0" in rest
    for path in (
        "docs/implementation/n8n-parallel/proposals/agents-3-0-0-governed-n8n-agents-20261009.md",
        "guardrail-audit-a-config-20261009.md",
        "guardrail-audit-b-code-20261009.md",
        "guardrail-audit-c-policy-n8n-20261009.md",
    ):
        assert path in rest, path


def test_stale_2_0_0_proposed_sentence_is_gone():
    assert "**2.0.0 is PROPOSED" not in AGENTS
    assert "**2.0.0 is ACTIVE from 2026-10-08" in AGENTS
    assert "the 1.6.1 text governs" not in _section_23()


def test_section_23_headings_present():
    s = _section_23()
    for n in ("23.1", "23.2", "23.3", "23.4", "23.5", "23.6", "23.7", "23.8", "23.9", "23.10"):
        assert re.search(rf"^## {re.escape(n)} ", s, re.M), n


def test_agent_nodes_reach_host_only_through_relay_and_reads():
    s = _subsection("23.3")
    assert "n8n workflows and n8n Agent nodes may cause host work only through the relay" in s
    assert "per-process tool allowlist at the bridge" in s
    assert "DOF SQL" in s


def test_five_operator_decisions_recorded_with_date():
    # (1) ratify the proposal text as 3.0.0
    assert "(1) ratify the proposal's §3 text as 3.0.0" in _flat(AGENTS)
    # (2) routing order, in §23.4
    r = _flat(_subsection("23.4"))
    assert "Operator decision recorded 2026-10-09 (decision 2)" in r
    assert "primary Grok (OAuth proxy), secondary ChatGPT (OAuth proxy), fallback DeepSeek (metered)" in r
    # (3) egress blocked, not proxied, in §23.3 and §23.8
    e = _flat(_subsection("23.3"))
    assert "internet egress is BLOCKED, not proxied" in e
    assert "Operator decision recorded 2026-10-09 (decision 3)" in e and "DOCKER-USER" in e
    assert "no internet egress" in _flat(_subsection("23.8"))
    # (4) first Agent scope, in §23.8
    a = _flat(_subsection("23.8"))
    assert "Operator decision recorded 2026-10-09 (decision 4)" in a
    for frag in ("explain why lane X failed", "coordination reads", "shadowed first"):
        assert frag in a, frag
    # (5) MFA waived, DB role still required, in §23.5
    c = _flat(_subsection("23.5"))
    assert "Operator waiver recorded 2026-10-09 (decision 5): owner MFA is not required" in c
    assert "does not extend to the database role" in c
    assert "Owner MFA is on and" not in c


# The bullets 3.0.0 adds or replaces; each must cite its cause (§20 convention). Pre-existing 2.0.0
# bullets keep their own wording and are not re-checked here.
NEW_BULLETS = {
    "23.3": (
        "n8n workflows and n8n Agent nodes may cause host work",
        "An Agent may not invoke unrestricted execution",
        "Every Agent tool call is checked against a per-process tool allowlist",
        "The n8n container reaches the host only at",
    ),
    "23.4": (
        "n8n workflows and Agent nodes may request AI capability",
        "They may not select a provider",
        "Routing order is a policy",
        "Free-text Agent input is allowed only",
        "Every model output used by a workflow",
    ),
    "23.5": ("n8n holds at most two credentials", "Operator waiver recorded 2026-10-09"),
    "23.8": (
        "An Agent node is permitted only",
        "Its model node points at the governed bridge",
        "Its tools are limited",
        "Turn count",
        "The n8n container has no internet egress",
        "The first Agent is read-only",
    ),
    "23.9": ("Before any lane or capability moves into n8n",),
}


def test_new_rules_cite_their_cause():
    for n, starts in NEW_BULLETS.items():
        bullets = re.split(r"^- ", _subsection(n), flags=re.M)[1:]
        for start in starts:
            hits = [b for b in bullets if _flat(b).lstrip("*").startswith(start)]
            assert len(hits) == 1, f"§{n}: bullet starting {start!r} not found once"
            assert "Cause (§" in _flat(hits[0]), f"§{n} bullet {start!r} has no Cause"


def test_preconditions_checklist_is_complete_and_grants_nothing():
    s = _subsection("23.10")
    assert "grants nothing" in s
    expected = [2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22]
    for n in expected:
        assert re.search(rf"^- \[ \] \*\*P{n}\*\* ", s, re.M), f"P{n} missing from §23.10"
    for n in (1, 10, 14, 23):
        assert not re.search(rf"^- \[ \] \*\*P{n}\*\* ", s, re.M), f"P{n} should not be an open item"


def test_section_17_names_agent_activation_and_bridge_token():
    assert "**activating an n8n Agent node, or creating the n8n bridge\ntoken**" in AGENTS


def test_section_23_7_lists_what_3_0_0_replaced():
    s = _subsection("23.7")
    assert "3.0.0 (PROPOSED" in s
    for frag in ("§23.3 first bullet", "§23.4", "§23.5", "§17 gains", "ADR_COORDINATION_SECRETS"):
        assert frag in s, frag


def test_adr_status_line_consistent_and_addendum_present():
    assert "PROPOSED 2.0.0" not in ADR
    assert re.search(r"^Policy:\s+AGENTS\.md §23\.5 \(ACTIVE 2\.0\.0", ADR, re.M)
    assert "## Addendum — AGENTS.md 3.0.0" in ADR
    add = ADR.split("## Addendum — AGENTS.md 3.0.0", 1)[1]
    assert "§23.10" in add and "bridge token" in add and "MFA is waived" in add
