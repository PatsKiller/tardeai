"""AGENTS.md 20.4.0 (PROPOSED, MINOR at the operator's instruction): §28.13 design lifecycle §28.14 self-heal monitor and fixer and §28.15 hands-off delivery — push budget 5 with a
coordinator-only override on approved scope, solo shared-infra trains, lane activation from the repo, no TTY ACK for
routine setup, configuration vs secrets, and what still reaches the operator. Hermetic text checks."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
POLICY = (ROOT / "AI_WORK_POLICY.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_20_4_0"


def _section() -> str:
    s = AGENTS.index("\n## 28.15 ")
    return AGENTS[s : AGENTS.index("\n---\n\n# Version history", s)]


def _design() -> str:
    s = AGENTS.index("\n## 28.13 ")
    return AGENTS[s : AGENTS.index("\n## 28.14 ", s)]


def _selfheal() -> str:
    s = AGENTS.index("\n## 28.14 ")
    return AGENTS[s : AGENTS.index("\n## 28.15 ", s)]


def _row():
    rows = re.findall(r"^\| 20\.4\.0 \| 2026-10-25 \| (PROPOSED|ACTIVE)[^|]* \| MINOR \|(.*)$", AGENTS, re.M)
    assert len(rows) == 1
    return rows[0]


def test_one_row_proposed_with_pending_token_or_ratified():
    status, rest = _row()
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{40}}", rest)


def test_proposed_does_not_move_the_header_and_state_checks_pass():
    if _row()[0] == "PROPOSED":
        assert re.search(r"^Policy-Version:\s+20\.3\.0$", AGENTS, re.M)
        assert "**20.4.0 is " not in AGENTS
        assert "(20.4.0, PROPOSED)" in _section() and "(20.4.0, PROPOSED)" in _design() and "(20.4.0, PROPOSED)" in _selfheal()
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_six_numbered_items_each_cite_a_cause():
    bullets = re.split(r"\n- ", _section())[1:]
    assert len(bullets) == 6
    for n, b in enumerate(bullets, 1):
        assert b.startswith(f"**{n} "), b[:40]
        assert "*Cause (§20):" in b, b[:60]


def test_items_name_the_mechanisms_and_the_limits():
    sec = re.sub(r"\s+", " ", _section())
    for needle in ("is 5 authorized pushes", "coordinator session", "TRADEAI_REMOTE_PUSH_OVERRIDE=1",
                   "Operator-approval:", "Force-push stays forbidden", "§0 rule 3",
                   "solo train", "exactly one such PR per window and no other member", "[shared-infra]",
                   "shared-infra-review", "Real-layout proof:", "adversarial review receipt",
                   "check_allowlist_consistency.py", "check_lane_registry.py", "cron_outage_watchdog.py",
                   "rolls back and pages P1", "train_self", "guard_ci_enforcement", "agents_policy",
                   "broker_active_trader", "config/lane_registry.json", "render_n8n_relay_env.py",
                   "override only", "never widened", "TTY", "Bitwarden", "/v3/system/ops-controls",
                   "config/secret_registry.yaml", "Approve version X", "release-write", "naming that PR",
                   "§24.8 unchanged", "unless a failure alert fires"):
        assert needle in sec, needle


def test_rails_stay_and_class_is_stated():
    sec = re.sub(r"\s+", " ", _section())
    assert "The §0 text, §2, §2A, the broker and secret rails, §23.14 and the four adapters do not change" in sec
    assert "21.0.0" in sec and TOKEN in sec
    for cause in ("four approved PRs", "grant expired", "relay live list", "TTY ACKs", "SMS"):
        assert cause in sec, cause


def test_ai_work_policy_states_the_same_budget_and_override():
    flat = re.sub(r"\s+", " ", POLICY)
    assert "AGENTS.md 20.4.0 §28.15 item 1" in flat
    assert "the per-branch budget is 5 authorized pushes" in flat
    assert "only the coordinator session" in flat and "Operator-approval: <quote or reference>" in flat
    assert "renaming or re-creating a branch to reset a budget is still routing around a denial" in flat
    assert "the hook allows pushes 1 through 5 on every branch" in flat
    assert "AGENTS.md 20.4.0 (§28.15 item 6)" in flat
    # until 20.4.0 is ACTIVE and the hook change merges, the default budget stays 2
    assert "maximum pushes without explicit operator approval: 2" in POLICY


def test_design_lifecycle_five_items_cite_causes_and_bind_the_approved_points():
    sec = _design()
    bullets = re.split(r"\n- ", sec)[1:]
    assert len(bullets) == 5
    for n, b in enumerate(bullets, 1):
        assert b.startswith(f"**{n} "), b[:40]
        assert "*Cause (§20):" in b, b[:60]
    flat = re.sub(r"\s+", " ", sec)
    for needle in ("I approve the design workflow", "`design/` is the single home", "design/registry.json",
                   "persistent-state/data/design", "repo is public", "real financial data is never committed",
                   "`v000`", "`v001`", "immutable", "DRAFT", "PROPOSED", "APPROVED (the operator only",
                   "Approvals → Designs", "signed decision", "prose in a handoff never counts",
                   "`Design: <page>/vNNN`", "`Design: none`", "VERIFIED", "CURRENT", "SUPERSEDED", "REJECTED",
                   "never adjusts an approved design", "≤820 px", "412 and 390", "15% of viewport height",
                   "← Back", "44 px", "no sideways page scroll", "ET times", "hide that needs approval",
                   "≥1280 px", "1440", "tokens only", "design-reference check", "removal guard",
                   "visual compare", "read-only agent reader", "Board 19", "Calendar and Replay", "Decision history showed 0",
                   "logged-in pages", TOKEN):
        assert needle in flat, needle


def test_self_heal_six_items_cite_causes_and_never_merge():
    sec = _selfheal()
    bullets = re.split(r"\n- ", sec)[1:]
    assert len(bullets) == 6
    for n, b in enumerate(bullets, 1):
        assert b.startswith(f"**{n} "), b[:40]
        assert "*Cause (§20):" in b, b[:60]
    flat = re.sub(r"\s+", " ", sec)
    for needle in ("Arm the fixer", "no separate guard grant", "shadow only", "host timer (not n8n",
                   "main CI", "post-release tester", "nightly sweep", "infrastructure flake (never a test failure)",
                   "generated file", "disk-packet re-pin", "stale-lock reconcile", "scripts/self_heal_fixer.py",
                   "isolated worktree", "diff guard", "never deletes, skips or weakens a test", "quotes AGENTS.md §0",
                   "The fixer never merges, releases or deploys", "Broker, Active Trader and MBI",
                   "guard, policy, hooks and AGENTS.md", "the train's own code", "credentials",
                   "coordinator task", "append-only fix log", "Releases & schedules → Fixes", "P1", TOKEN):
        assert needle in flat, needle
