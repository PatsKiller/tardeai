"""AGENTS.md 23.0.0 (PROPOSED, MAJOR): Telegram remote grants are retired.

Pins the PROPOSED amendment text and the production RETIRED constant. Header stays
22.0.0 ACTIVE until ratification; code ships RETIRED so Telegram cannot grant.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
GRA = (ROOT / "scripts" / "lib" / "guard_remote_approval.py").read_text(encoding="utf-8")


def _header_block() -> str:
    return AGENTS.split("\n---\n", 1)[0]


def test_header_stays_22_0_0_active_until_ratification():
    hdr = _header_block()
    m = re.search(r"^Policy-Version:\s*(\S+)", hdr, re.M)
    assert m and m.group(1) == "22.0.0", hdr[:200]
    assert re.search(r"^Status:\s*ACTIVE\b", hdr, re.M), hdr[:200]
    assert "23.0.0 is PROPOSED" in AGENTS[:25000]
    assert "23.0.0 is ACTIVE" not in AGENTS[:25000]


def test_version_history_proposed_row():
    rows = re.findall(
        r"^\| 23\.0\.0 \| 2026-10-25 \| (PROPOSED|ACTIVE[^|]*) \| MAJOR \|(.*)$",
        AGENTS,
        re.M,
    )
    assert len(rows) == 1, rows
    status, rest = rows[0]
    assert status == "PROPOSED", status
    assert "TELEGRAM_REMOTE_GRANT_STATUS" in rest or "Telegram remote grants" in rest
    assert "APPROVE_AGENTS_POLICY_23_0_0" in rest


def test_remote_approval_section_is_retired():
    assert "## Remote approval by Telegram — RETIRED (23.0.0)" in AGENTS
    assert "TELEGRAM_GRANT_RETIRED" in AGENTS
    assert "Train publication needs no grant" in AGENTS
    # Old "how to approve from the phone" procedure must not remain as current guidance.
    assert "`/approve <CODE>`" in AGENTS  # named as refused
    assert "moves the *typing* to Telegram" not in AGENTS


def test_production_constant_is_retired():
    assert 'TELEGRAM_REMOTE_GRANT_STATUS = "RETIRED"' in GRA
    assert "def telegram_remote_grants_retired()" in GRA
    assert 'TELEGRAM_GRANT_RETIRED' in GRA


def test_banner_names_major_and_pending_token():
    banner = AGENTS[:25000]
    assert "23.0.0 is PROPOSED (MAJOR)" in banner
    assert "APPROVE_AGENTS_POLICY_23_0_0" in banner
    assert "Ops → Controls" in banner
