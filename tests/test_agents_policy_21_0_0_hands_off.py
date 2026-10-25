"""AGENTS.md 21.0.0 (PROPOSED, MAJOR): §28.13 design lifecycle, §28.14 self-heal monitor and fixer, §28.15 hands-off
delivery — one token. Header unchanged while PROPOSED (20.2.0/20.3.0 convention). Hermetic text checks."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_agents_policy_state as STATE  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
POLICY = (ROOT / "AI_WORK_POLICY.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_21_0_0"


def _between(start: str, end: str) -> str:
    s = AGENTS.index(start)
    return AGENTS[s : AGENTS.index(end, s)]


def _design() -> str:
    return _between("\n## 28.13 ", "\n## 28.14 ")


def _selfheal() -> str:
    return _between("\n## 28.14 ", "\n## 28.15 ")


def _handsoff() -> str:
    return _between("\n## 28.15 ", "\n---\n\n# Version history")


def _flat(t: str) -> str:
    return re.sub(r"\s+", " ", t)


def _items(sec: str, n: int) -> None:
    bullets = re.split(r"\n- \*\*(?=\d+ )", sec)[1:]
    assert len(bullets) == n, len(bullets)
    for i, b in enumerate(bullets, 1):
        assert b.startswith(f"{i} "), b[:40]
        assert "*Cause (§20):" in b, b[:60]


def _row():
    rows = re.findall(r"^\| 21\.0\.0 \| 2026-10-25 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert len(rows) == 1
    return rows[0]


def test_one_major_row_and_no_20_4_0_row():
    status, rest = _row()
    assert not re.search(r"^\| 20\.4\.0 \|", AGENTS, re.M)
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest and "`solo`" in rest
    else:
        assert re.search(rf"{TOKEN} \d+ [0-9a-f]{{40}}", rest)


def test_proposed_does_not_move_the_header_and_state_checks_pass():
    if _row()[0] == "PROPOSED":
        assert re.search(r"^Policy-Version:\s+20\.3\.0$", AGENTS, re.M)
        assert "**21.0.0 is " not in AGENTS
        for sec in (_design(), _selfheal(), _handsoff()):
            assert "(21.0.0, PROPOSED)" in sec
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_class_is_stated_unambiguously():
    f = _flat(_handsoff())
    assert "**Class: MAJOR, so 21.0.0, not 20.4.0.**" in f and "widening §17" in f
    assert "The §0 text, §2, §2A, the broker and secret rails, §23.14 and the four adapters do not change" in f


def test_design_lifecycle():
    _items(_design(), 7)
    f = _flat(_design())
    for needle in ("I approve the design workflow", "design/registry.json", "versions/vNNN/", "`v000`", "`v001`",
                   "immutable", "DRAFT → PROPOSED → APPROVED → IMPLEMENTING → VERIFIED → CURRENT", "REJECTED",
                   "Approvals → Designs", "signed decision", "Prose in a handoff, chat or PR never counts",
                   "`Design: <page>/vNNN`", "`Design: none`", "never adjusts an approved design", "removal guard",
                   "≤820 px", "15% of viewport height", "← Back", "44 × 44 px", "No sideways page scroll",
                   "≥1280 px", "tokens only", "visual compare", "read-only agent reader", "§28.8",
                   "persistent-state/data/design", "public", "Board 19", "Calendar and Replay", TOKEN):
        assert needle in f, needle


def test_self_heal():
    _items(_selfheal(), 6)
    f = _flat(_selfheal())
    for needle in ("Arm the fixer", "there is no separate guard grant", "shadow only", "A host timer, not n8n",
                   "infrastructure flake, never on a test failure", "disk-packet re-pin", "stale-lock reconcile",
                   "scripts/self_heal_fixer.py", "never deletes, skips or weakens a test", "quotes AGENTS.md §0",
                   "The fixer never merges, releases or deploys", "coordinator task", "append-only fix log",
                   "Releases & schedules → Fixes", "P1"):
        assert needle in f, needle


def test_hands_off_items():
    _items(_handsoff(), 9)
    f = _flat(_handsoff())
    for needle in ("is 5 authorized pushes", "Only the coordinator session", "TRADEAI_REMOTE_PUSH_OVERRIDE=1",
                   "Operator-approval:", "Force-push stays forbidden", "§0 rule 3",
                   # item 2: solo trains, one review
                   "exactly one PR in the window, with no other member", "portfolio-server API", "oversized",
                   "deletions", "migrations", "expand-only", "Adversarial-review: MERGE", "Real-layout proof:",
                   "shared-infra-review", "rolls back, latches STOP and pages P1", "always held",
                   # item 3: train-self / guard
                   "two `Adversarial-review: MERGE` receipts from two different reviewer agents",
                   "train dry run of the next window", "at least 3 h", "veto", "standing delegation's `solo` class",
                   "refused by the classifier and goes to the operator", "does not weaken §0/§2/§17 enforcement",
                   # items 4-7
                   "render_n8n_relay_env.py", "override only", "never widened", "TTY", "Bitwarden",
                   "/v3/system/ops-controls", "config/secret_registry.yaml", "`permitted_classes`", "change-scope",
                   "at the same moment as ratifying this version",
                   # item 8: no guard grant for routine pushes and toolchains
                   "without a guard `git-push` grant", "fast-forward only", "data/coordination/handoffs/",
                   "never force-pushes, resets", "Pushes to `main`, history rewrites and force pushes still need the operator",
                   "never in the `deps` scope", "`npx playwright test`", "lockfile changes", "guard hook must classify",
                   "16:14 ET", "Cursor",
                   # item 9: the complete list
                   "The complete list of what reaches the operator", "Approve version X", "never delegable",
                   "Credentials and secrets", "Design approvals (§28.13)", "Alerts and escalations",
                   "Everything else ships with no operator input"):
        assert needle in f, needle
    assert "release-write` grant naming that PR" not in f  # the per-PR grant tap was replaced by item 3


def test_ai_work_policy_matches():
    f = _flat(POLICY)
    assert "AGENTS.md 21.0.0 §28.15 item 1" in f and "the per-branch budget is 5 authorized pushes" in f
    assert "only the coordinator session" in f and "Operator-approval: <quote or reference>" in f
    assert "the hook allows pushes 1 through 5 on every branch" in f
    assert "§28.15 items 2, 3 and 7" in f and "veto window of at least 3 h" in f
    assert "Agents still never merge" in f
    if _row()[0] == "ACTIVE":
        assert "binding (21.0.0 ACTIVE)" in f and "PROPOSED, binding only" not in f
    assert "needs no guard `git-push` grant" in f and "AGENTS.md §28.15 item 8" in f
    assert "maximum pushes without explicit operator approval: 2" in POLICY
    assert "20.4.0" not in POLICY


def test_ratified_state_is_consistent():
    if _row()[0] == "ACTIVE":
        assert re.search(r"^Policy-Version:\s+21\.0\.0$", AGENTS, re.M)
        assert re.search(r"^Status:\s+ACTIVE$", AGENTS, re.M)
        assert re.search(r"^Supersedes:\s+20\.3\.0$", AGENTS, re.M)
        assert re.search(r"^Effective-Date:\s+2026-10-25$", AGENTS, re.M)
        assert "**21.0.0 is ACTIVE (MAJOR)" in AGENTS
        for sec in (_design(), _selfheal(), _handsoff()):
            assert "(21.0.0, ACTIVE)" in sec and re.search(r"APPROVE_AGENTS_POLICY_21_0_0 2128 [0-9a-f]{40}", sec)
