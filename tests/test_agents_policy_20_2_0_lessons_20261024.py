"""AGENTS.md 20.2.0 (PROPOSED, MINOR): §28.9 lessons of 2026-10-23/24. Adds restrictions only; §0/§2/§17 untouched."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def _section() -> str:
    s = AGENTS.index("\n## 28.9 ")
    return AGENTS[s:AGENTS.index("\n---\n\n# Version history", s)]


def test_one_row_proposed_or_ratified_with_token():
    rows = re.findall(r"^\| 20\.2\.0 \| 2026-10-24 \| (PROPOSED|ACTIVE[^|]*) \| MINOR \|(.*)$", AGENTS, re.M)
    assert len(rows) == 1
    status, rest = rows[0]
    assert status == "PROPOSED" or "APPROVE_AGENTS_POLICY_20_2_0" in rest


def test_six_rules_each_cite_a_cause():
    bullets = [b for b in re.split(r"\n- ", _section())[1:]]
    assert len(bullets) == 6
    for b in bullets:
        assert "*Cause (§20):" in b, b[:80]


def test_rules_present():
    sec = _section()
    for needle in ("operator-approved mockup", "[shared-infra]", "owned by the CIO record",
                   "last successful run", "A GET never triggers a broker read", "monitored n8n lane"):
        assert needle in sec, needle


def test_does_not_touch_operator_gated_sections():
    assert "§0, §2, §17 or role authority" in _section()
