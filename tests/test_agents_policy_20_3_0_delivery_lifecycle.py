"""AGENTS.md 20.3.0 (PROPOSED, MINOR): §28.12 delivery lifecycle — claim to verified release. Adds obligations only;
§0/§2/§17 and role authority untouched. Hermetic text checks."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def _section() -> str:
    s = AGENTS.index("\n## 28.12 ")
    end = AGENTS.index("\n---\n\n# Version history", s)
    if "\n## 28.13 " in AGENTS[s:end]:  # 20.4.0 (§28.13) follows §28.12
        end = AGENTS.index("\n## 28.13 ", s)
    return AGENTS[s:end]


def test_one_row_proposed_or_ratified_with_token():
    rows = re.findall(r"^\| 20\.3\.0 \| 2026-10-25 \| (PROPOSED|ACTIVE[^|]*) \| MINOR \|(.*)$", AGENTS, re.M)
    assert len(rows) == 1
    status, rest = rows[0]
    assert status == "PROPOSED" or "APPROVE_AGENTS_POLICY_20_3_0" in rest


def test_proposed_does_not_move_the_header():
    if re.search(r"^\| 20\.3\.0 \| 2026-10-25 \| PROPOSED", AGENTS, re.M):
        assert re.search(r"^Policy-Version:\s+20\.2\.0$", AGENTS, re.M)
        assert "**20.3.0 is " not in AGENTS


def test_ten_ordered_steps_each_cite_a_cause():
    bullets = re.split(r"\n- ", _section())[1:]
    assert len(bullets) == 10
    for n, b in enumerate(bullets, 1):
        assert b.startswith(f"**{n} "), b[:40]
        assert "*Cause (§20):" in b, b[:60]


def test_steps_name_the_mechanisms():
    sec = _section()
    for needle in ("agent_claim.py", "operator-approved mockup", "git worktree add", "$HOME/.cache/agent-tmp",
                   "412 and 390", "temp `PROJECT_ROOT`", "[shared-infra]", "Real-layout proof:",
                   "config/release_train_policy.json", "needs_operator", "scripts/post_release_tester.py",
                   "scripts/delivery_failure_alerts.py", "SMS", "never the digest", "ROLLED_BACK", "STOP latch"):
        assert needle in sec, needle


def test_does_not_touch_operator_gated_sections():
    assert "does not touch §0, §2, §17 or role authority" in _section()
    assert "APPROVE_AGENTS_POLICY_20_3_0" in _section()


def test_ratified_state_is_consistent():
    row = re.search(r"^\| 20\.3\.0 \| 2026-10-25 \| (PROPOSED|ACTIVE)[^|]* \|", AGENTS, re.M).group(1)
    if row == "ACTIVE":
        assert re.search(r"APPROVE_AGENTS_POLICY_20_3_0 2107 [0-9a-f]{40}", _section())
        # Tip may be 20.3.0+; 24.0.0 soft-add is PROPOSED until ratify, ACTIVE after.
        ver = re.search(r"^Policy-Version:\s+(\S+)$", AGENTS, re.M).group(1)
        status = re.search(r"^Status:\s+(\S+)$", AGENTS, re.M).group(1)
        assert ver in ("20.3.0", "21.0.0", "22.0.0", "24.0.0")
        assert status in ("PROPOSED", "ACTIVE")
        assert re.search(r"^Supersedes:\s+(20\.[23]\.0|21\.0\.0|22\.0\.0)$", AGENTS, re.M)
        assert re.search(r"^Effective-Date:\s+(2026-10-2[56]|PENDING)$", AGENTS, re.M)
        assert "**20.3.0 is ACTIVE (MINOR)" in AGENTS and "(20.3.0, ACTIVE)" in _section()
