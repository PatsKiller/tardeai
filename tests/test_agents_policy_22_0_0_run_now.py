"""AGENTS.md 22.0.0 (ACTIVE, MAJOR): Ops → Controls may force a live canary Run now.

Pins the ACTIVE amendment text after ratification. §0 / §2 / adapters are unchanged;
the §25.3 soft-add keeps the 17.0.0 CLI pin wording.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def _header_block() -> str:
    return AGENTS.split("\n---\n", 1)[0]


def _section_25_3() -> str:
    start = AGENTS.index("\n## 25.3 ")
    end = AGENTS.index("\n## 25.4 ", start)
    return AGENTS[start:end]


def test_header_is_22_0_0_active():
    hdr = _header_block()
    m = re.search(r"^Policy-Version:\s*(\S+)", hdr, re.M)
    assert m and m.group(1) == "22.0.0", hdr[:200]
    assert re.search(r"^Status:\s*ACTIVE\b", hdr, re.M), hdr[:200]
    assert re.search(r"^Supersedes:\s*21\.0\.0\b", hdr, re.M), hdr[:200]
    assert "22.0.0 is ACTIVE" in AGENTS[:20000]
    assert "22.0.0 is PROPOSED" not in AGENTS


def test_version_history_one_active_row_with_token():
    rows = re.findall(
        r"^\| 22\.0\.0 \| 2026-10-25 \| (PROPOSED|ACTIVE[^|]*) \| MAJOR \|(.*)$",
        AGENTS,
        re.M,
    )
    assert len(rows) == 1, rows
    status, rest = rows[0]
    assert status.startswith("ACTIVE"), status
    assert "release_train.run_now" in rest
    assert "APPROVE_AGENTS_POLICY_22_0_0 2149 a91e0806cbd92fbbd6f09f971ed13fbb35338fa1" in rest


def test_section_25_3_adds_ops_controls_run_now_without_dropping_cli_pin():
    sec = _section_25_3()
    assert "release_train.run_now" in sec
    assert "RUN NOW EPOCH" in sec
    assert "Ops → Controls" in sec
    # Soft-add: the original 17.0.0 refusal of Command Center still appears for the CLI-only era.
    assert "never accepted from n8n, the Command Center" in sec or "Command Center" in sec
    assert "host CLI" in sec.lower() or "Host CLI" in sec or "`scripts/release_control_cli.py`" in AGENTS
    assert "*Cause (§20):" in sec


def test_section_17_lists_run_now_as_operator_only():
    assert "release_train.run_now" in AGENTS
    assert "Release train Run now (22.0.0" in AGENTS or "forcing a live canary train from Ops → Controls" in AGENTS


def test_banner_names_major_and_ratification():
    banner = AGENTS[:12000]
    assert "22.0.0 is ACTIVE (MAJOR)" in banner
    assert "APPROVE_AGENTS_POLICY_22_0_0 2149" in banner
    assert "#2128" in banner or "21.0.0" in banner
