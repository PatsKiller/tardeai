"""Standing merge delegation (2026-11-02): the gates that stand between a green PR and a label.

Operator: "Build the standing merge delegation" — after the design (DSN-20261102) and the gap were put
to them. The module may add ONE label through the existing Telegram helper, and only when an AGENTS.md
capability ratified on main AND a genuine operator standing-approval comment both hold, plus every
gate below on the exact head. Hermetic: no network, no gh, no real claim board, no real STOP latch.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import merge_standing as ms  # noqa: E402

REPO = "PatsKiller/tardeai"
N = 900
BRANCH = "wt/standing-merge-demo-20261102"
SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
AUTHOR_AGENT = "claude-code"
AUTHOR_SESSION = "sess-author-1"
#: Monday 2026-11-02 17:45 America/New_York (EST, UTC-5) — inside the configured window.
INSIDE = datetime(2026, 11, 2, 22, 45, tzinfo=timezone.utc)
OUTSIDE = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def policy_text(*, version: str = "29.6.0", status: str = "ACTIVE", row_status: str = "ACTIVE",
                token: bool = True) -> str:
    row = ("| Version | Date | Status | Change class | Summary | Approval |\n|---|---|---|---|---|---|\n"
           f"| {version} | 2026-11-02 | {row_status} | MINOR | standing merge delegation "
           f"{'APPROVE_MERGE_STANDING' if token else 'no capability'} | PENDING |\n")
    return ("# AGENTS.md\n\n```\nPolicy-Version:      " + version + "\nVersioning-Scheme:   Semantic Versioning\n"
            "Status:              " + status + "\n```\n\n" + row)


def approval_comment(body: str = "", *, cid: int = 1000, login: str = "PatsKiller",
                     created: str = "2026-11-01T12:00:00Z", updated: str | None = None) -> dict:
    return {"id": cid, "user": {"login": login}, "body": body, "created_at": created,
            "updated_at": updated or created,
            "html_url": f"https://github.com/{REPO}/issues/50#issuecomment-{cid}"}


def approval_body(glob: str = "wt/*", until: str = "2026-12-01") -> str:
    return f"APPROVE_MERGE_STANDING {glob} until {until}"


def receipt_comment(reviewer: str, head: str = SHA, coordinator: str = "coord-1") -> dict:
    return {"id": hash(reviewer) % 100000, "user": {"login": reviewer}, "created_at": "2026-11-02T12:00:00Z",
            "updated_at": "2026-11-02T12:00:00Z",
            "body": f"Adversarial-review: MERGE reviewer={reviewer} head={head} coordinator={coordinator}"}


def check_runs(*rows: tuple[str, str, str]) -> dict:
    return {"total_count": len(rows),
            "check_runs": [{"name": n, "status": s, "conclusion": c, "started_at": "2026-11-02T12:00:00Z"}
                           for n, s, c in rows]}


GREEN = check_runs(("ci-gate", "completed", "success"), ("agent-governance", "completed", "success"),
                   ("secret-scan", "completed", "success"), ("pr-plain-english", "completed", "neutral"))


class Gh:
    """A read-only fake for the paths the evaluator fetches; unknown paths are a 404 (None)."""

    def __init__(self, docs: dict[str, object]):
        self.docs = dict(docs)
        self.calls: list[str] = []

    def __call__(self, path: str):
        self.calls.append(path)
        return self.docs.get(path)


def world(*, head: str = SHA, draft: bool = False, base: str = "main", labels: list[str] | None = None,
          files: list[str] | None = None, changed: int | None = None, checks: dict | None = None,
          issue_comments: list[dict] | None = None, pr_comments: list[dict] | None = None,
          issue_state: str = "open", issue_author: str = "PatsKiller") -> Gh:
    files = files if files is not None else ["scripts/x.py"]
    pr_comments = pr_comments if pr_comments is not None else [receipt_comment("rev-a", head),
                                                               receipt_comment("rev-b", head, "coord-2")]
    issue_comments = issue_comments if issue_comments is not None else [approval_comment(approval_body())]
    return Gh({
        f"repos/{REPO}/pulls/{N}": {"number": N, "head": {"ref": BRANCH, "sha": head},
                                    "base": {"ref": base}, "draft": draft,
                                    "user": {"login": "agent-bot"},
                                    "labels": [{"name": x} for x in (labels or [])],
                                    "changed_files": len(files) if changed is None else changed},
        f"repos/{REPO}/pulls/{N}/files?per_page=100": [{"filename": f} for f in files],
        f"repos/{REPO}/commits/{head}/check-runs?per_page=100&page=1": checks or GREEN,
        f"repos/{REPO}/issues?creator=PatsKiller&state=all&sort=created&direction=asc&per_page=100&page=1":
            [{"number": 50, "title": "Standing merge approvals", "user": {"login": "PatsKiller"}}],
        f"repos/{REPO}/issues/50": {"number": 50, "state": issue_state, "title": "Standing merge approvals",
                                    "user": {"login": issue_author}},
        f"repos/{REPO}/issues/50/events?direction=asc&per_page=100&page=1": [],
        f"repos/{REPO}/issues/50/comments?direction=asc&per_page=100&page=1": issue_comments,
        f"repos/{REPO}/issues/{N}/comments?direction=asc&per_page=100&page=1": pr_comments,
    })


READY = [{"pr": N}]


def run(gh: Gh | None = None, *, apply: bool = False, policy: str | None = policy_text(),
        now: datetime = INSIDE, cfg: dict | None = None, claims: dict | None = None,
        applier=None, stop: dict | None = None) -> dict:
    labelled: list[tuple] = []

    def _applier(number, *, repo):
        labelled.append((number, repo))
        return {"ok": True, "rc": 0, "action": "add"}
    return ms.review(READY, repo=REPO, cfg=cfg or ms.load_config(), apply=apply, now=now, gh_json=gh or world(),
                     policy_text=policy, label_applier=applier or _applier,
                     stop_reader=lambda: stop or {"ok": True, "state": "ABSENT"},
                     claim_reader=lambda branch: claims if claims is not None
                     else {"agent": AUTHOR_AGENT, "session": AUTHOR_SESSION})


def decision(out: dict) -> dict:
    assert out["enabled"], out
    return out["decisions"][0]


# ---------------------------------------------------------------- the capability switch


def test_default_off_with_no_ratified_capability_and_no_github_call():
    out = run(Gh({}), policy=policy_text(version="29.4.0"))
    assert out["enabled"] is False and out["decisions"] == []
    assert "OFF" in out["detail"]


def test_capability_requires_the_token_in_the_active_versions_row():
    out = ms.policy_capability(policy_text(version="29.6.0", token=False))
    assert out["capability"] is False and "does not name" in out["detail"]


def test_proposed_policy_does_not_arm_it():
    assert ms.policy_capability(policy_text(status="PROPOSED", row_status="PROPOSED"))["capability"] is False


def test_below_the_minimum_version_does_not_arm_it():
    assert ms.policy_capability(policy_text(version="29.5.0"))["capability"] is False


def test_ratified_capability_is_detected():
    cap = ms.policy_capability(policy_text())
    assert cap["capability"] is True and cap["version"] == "29.6.0"


# ---------------------------------------------------------------- happy path + dry run


def test_eligible_pr_is_labelled_once_and_receipted(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    calls: list = []
    out = run(apply=True, applier=lambda n, *, repo: (calls.append((n, repo)) or {"ok": True, "rc": 0}))
    assert out["applied"] and out["applied"][0]["ok"] is True
    assert calls == [(N, REPO)]
    receipts = (tmp_path / "data/runtime/pr_merge_standing/receipts.jsonl").read_text().splitlines()
    row = json.loads(receipts[-1])
    assert row["schema"] == "MergeStandingReceipt@v1" and row["pr"] == N and row["head"] == SHA
    assert row["standing_ref"].endswith("#issuecomment-1000")
    assert row["reviewers"] == ["rev-a", "rev-b"]
    assert row["no_consumer_reason"]


def test_dry_run_labels_nothing_and_reports_the_decision():
    calls: list = []
    out = run(apply=False, applier=lambda n, *, repo: calls.append(n) or {"ok": True})
    assert decision(out)["eligible"] is True
    assert calls == [] and out["applied"] == []
    assert "dry run" in out["detail"]


def test_only_one_label_per_run_even_with_two_eligible_prs():
    gh = world()
    gh.docs[f"repos/{REPO}/pulls/{N + 1}"] = dict(gh.docs[f"repos/{REPO}/pulls/{N}"], number=N + 1)
    gh.docs[f"repos/{REPO}/pulls/{N + 1}/files?per_page=100"] = [{"filename": "scripts/y.py"}]
    gh.docs[f"repos/{REPO}/issues/{N + 1}/comments?direction=asc&per_page=100&page=1"] = [
        receipt_comment("rev-a", SHA), receipt_comment("rev-b", SHA, "coord-2")]
    calls: list = []
    out = ms.review([{"pr": N}, {"pr": N + 1}], repo=REPO, cfg=ms.load_config(), apply=True, now=INSIDE,
                    gh_json=gh, policy_text=policy_text(),
                    label_applier=lambda n, *, repo: calls.append(n) or {"ok": True},
                    stop_reader=lambda: {"ok": True}, claim_reader=lambda b: {"agent": AUTHOR_AGENT,
                                                                              "session": AUTHOR_SESSION})
    assert len(calls) == 1 and len(out["applied"]) == 1


# ---------------------------------------------------------------- the approval


def test_expired_standing_approval_refuses():
    gh = world(issue_comments=[approval_comment(approval_body(until="2026-10-31"))])
    assert any("expired" in r for r in decision(run(gh))["refusals"])


def test_missing_approval_refuses():
    gh = world(issue_comments=[approval_comment("no approval here")])
    assert any("no unrevoked" in r for r in decision(run(gh))["refusals"])


def test_revoked_standing_approval_refuses():
    gh = world(issue_comments=[approval_comment(approval_body(), cid=1000),
                               approval_comment("REVOKE_MERGE_STANDING", cid=1001,
                                                created="2026-11-01T13:00:00Z")])
    assert any("no unrevoked" in r for r in decision(run(gh))["refusals"])


def test_a_non_operator_comment_is_not_an_approval():
    gh = world(issue_comments=[approval_comment(approval_body(), login="someone-else")])
    assert any("no unrevoked" in r for r in decision(run(gh))["refusals"])


def test_a_fenced_example_is_not_an_approval():
    gh = world(issue_comments=[approval_comment(f"```\n{approval_body()}\n```")])
    assert any("no unrevoked" in r for r in decision(run(gh))["refusals"])


def test_an_indented_example_is_not_an_approval():
    gh = world(issue_comments=[approval_comment(f"Example:\n\n    {approval_body()}\n")])
    assert any("no unrevoked" in r for r in decision(run(gh))["refusals"])


def test_an_html_hidden_line_is_not_an_approval():
    gh = world(issue_comments=[approval_comment(f"<!--\n{approval_body()}\n-->")])
    assert any("no unrevoked" in r for r in decision(run(gh))["refusals"])


def test_a_glob_that_does_not_cover_the_branch_refuses():
    gh = world(issue_comments=[approval_comment(approval_body(glob="feat/other-*"))])
    assert any("does not cover" in r for r in decision(run(gh))["refusals"])


@pytest.mark.parametrize("glob", ["*", "release/*", "main", "train/x", "wt/*/x"])
def test_a_glob_that_could_reach_a_protected_branch_refuses(glob):
    gh = world(issue_comments=[approval_comment(approval_body(glob=glob))])
    out = decision(run(gh))
    assert out["eligible"] is False


def test_a_closed_issue_refuses():
    gh = world(issue_state="closed")
    assert any("not an open issue" in r for r in decision(run(gh))["refusals"])


def test_an_edited_operator_comment_refuses():
    gh = world(issue_comments=[approval_comment(approval_body(), updated="2026-11-01T14:00:00Z")])
    assert any("edited" in r for r in decision(run(gh))["refusals"])


# ---------------------------------------------------------------- PR gates


def test_a_draft_refuses():
    assert any("draft" in r for r in decision(run(world(draft=True)))["refusals"])


def test_a_non_main_base_refuses():
    assert any("not main" in r for r in decision(run(world(base="develop")))["refusals"])


def test_a_held_label_refuses():
    assert any("held" in r for r in decision(run(world(labels=["held"])))["refusals"])


def test_a_held_path_refuses():
    assert any("held" in r for r in decision(run(world(files=["AGENTS.md"])))["refusals"])


def test_a_broker_path_refuses():
    assert any("held" in r for r in decision(run(world(files=["scripts/active_trader/x.py"])))["refusals"])


def test_an_already_labelled_pr_refuses():
    assert any("already carries" in r for r in decision(run(world(labels=["operator-merge"])))["refusals"])


def test_unverified_files_refuse():
    assert any("files" in r for r in decision(run(world(files=["scripts/x.py"], changed=7)))["refusals"])


def test_a_failing_check_refuses():
    gh = world(checks=check_runs(("ci-gate", "completed", "success"), ("secret-scan", "completed", "failure")))
    assert any("checks:" in r for r in decision(run(gh))["refusals"])


def test_a_pending_check_refuses():
    gh = world(checks=check_runs(("ci-gate", "in_progress", ""), ("secret-scan", "completed", "success")))
    assert any("checks:" in r for r in decision(run(gh))["refusals"])


def test_all_checks_skipped_is_not_green():
    gh = world(checks=check_runs(("ci-gate", "completed", "skipped"), ("secret-scan", "completed", "skipped")))
    assert any("no check reported success" in r for r in decision(run(gh))["refusals"])


# ---------------------------------------------------------------- review receipts


def test_one_receipt_refuses():
    gh = world(pr_comments=[receipt_comment("rev-a")])
    assert any("review:" in r for r in decision(run(gh))["refusals"])


def test_the_same_reviewer_twice_is_one_receipt():
    gh = world(pr_comments=[receipt_comment("rev-a"), receipt_comment("rev-a", coordinator="coord-9")])
    assert any("review:" in r for r in decision(run(gh))["refusals"])


def test_the_author_cannot_review_its_own_pr():
    gh = world(pr_comments=[receipt_comment(AUTHOR_SESSION), receipt_comment("rev-b")])
    assert any("review:" in r for r in decision(run(gh))["refusals"])


def test_a_receipt_for_another_head_refuses():
    gh = world(pr_comments=[receipt_comment("rev-a", head="b" * 40), receipt_comment("rev-b")])
    assert any("review:" in r for r in decision(run(gh))["refusals"])


def test_receipts_on_the_exact_head_are_accepted():
    gh = world(pr_comments=[receipt_comment("rev-a", head=SHA[:7]), receipt_comment("rev-b", head=SHA[:12])])
    assert decision(run(gh))["eligible"] is True


# ---------------------------------------------------------------- window, STOP, races


def test_outside_the_window_refuses():
    assert any("window:" in r for r in decision(run(now=OUTSIDE))["refusals"])


def test_the_stop_latch_refuses():
    out = run(stop={"ok": False, "state": "SET", "detail": "STOP latch SET"})
    assert any("stop:" in r for r in decision(out)["refusals"])


def test_an_unreadable_stop_latch_refuses():
    out = run(stop={"ok": False, "state": "UNREADABLE", "detail": "STOP latch UNREADABLE"})
    assert any("stop:" in r for r in decision(out)["refusals"])


def test_a_head_that_moves_before_the_label_is_never_labelled(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    gh = world()
    moved = {"n": 0}

    class Moving(Gh):
        def __call__(self, path):
            if path == f"repos/{REPO}/pulls/{N}":
                moved["n"] += 1
                if moved["n"] > 1:  # the second read (inside _apply_one) sees a new head
                    return dict(self.docs[path], head={"ref": BRANCH, "sha": "f" * 40})
            return super().__call__(path)

    calls: list = []
    out = ms.review(READY, repo=REPO, cfg=ms.load_config(), apply=True, now=INSIDE, gh_json=Moving(gh.docs),
                    policy_text=policy_text(),
                    label_applier=lambda n, *, repo: calls.append(n) or {"ok": True},
                    stop_reader=lambda: {"ok": True},
                    claim_reader=lambda b: {"agent": AUTHOR_AGENT, "session": AUTHOR_SESSION})
    assert calls == [] and out["applied"][0]["event"] == "standing-merge-head-moved"


# ---------------------------------------------------------------- integration + drift


def test_the_digest_wire_is_off_by_default_and_never_breaks_it(monkeypatch):
    from scripts.lib import pr_merge_digest as pmd

    d = {"ready": [{"pr": N}], "needs_operator": [], "not_described": [], "overflow": []}

    class Boom:
        @staticmethod
        def review(*a, **k):
            raise RuntimeError("boom")

    monkeypatch.setattr(ms, "review", Boom.review)
    out = pmd._standing_review(d, repo=REPO, apply=False)
    assert out["enabled"] is False and "standing review failed" in out["detail"]


def test_the_configured_windows_match_mergify():
    """Drift guard: the evaluator's window and the queue's window are the same window."""
    text = (ROOT / ".mergify.yml").read_text(encoding="utf-8")
    import re
    schedules = set(re.findall(r"schedule=([A-Za-z]{3}-[A-Za-z]{3} \d{2}:\d{2}-\d{2}:\d{2}\[[^\]]+\])", text))
    assert schedules, "no schedule lines found in .mergify.yml"
    cfg = ms.load_config()
    ours = set()
    for w in cfg["windows"]:
        days = w["days"]
        ours.add(f"{days[0]}-{days[-1]} {w['start']}-{w['end']}[{cfg['timezone']}]")
    assert ours == schedules


def test_a_timezone_that_is_missing_refuses():
    cfg = dict(ms.load_config(), timezone="Not/AZone")
    assert ms.merge_window(INSIDE, cfg)["ok"] is False
