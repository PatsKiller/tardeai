"""Held part of approvals-pr-review/v001: the CC "Approve merge" label applier and D1 in the Telegram digest.

COVERS = ["scripts/lib/pr_review_apply.py", "scripts/lib/pr_merge_digest.py"]

Synthetic PRs (numbers 91xx, invented SHAs and paths). gh, Telegram and the ledger are stubbed; nothing here reaches
GitHub, Telegram or production state.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib import merge_hold_paths as mhp
from scripts.lib import pr_merge_digest as pmd
from scripts.lib import pr_merge_telegram as pmt
from scripts.lib import pr_review as R
from scripts.lib import pr_review_apply as pra

ROOT = Path(__file__).resolve().parents[1]
H1, H2 = "a1" * 20, "b2" * 20
GREEN = [{"name": c, "conclusion": "SUCCESS"} for c in pmt.REQUIRED_CHECKS]


def approve_row(pr=9101, head=H1, actor="tailnet:operator@example.test", effect="OPERATOR_MERGE_LABEL", h="x"):
    return {"event": "DECIDED", "kind": "MERGE", "decision": "APPROVE", "effect": effect, "actor": actor, "pr": pr,
            "item_id": f"pr:{pr}", "head_sha": head, "hash_self": h * 64, "at": "2031-03-04T17:00:00+00:00"}


def view(head=H1, files=("docs/x.md",), checks=GREEN, state="OPEN", labels=()):
    return {"number": 9101, "state": state, "headRefOid": head, "isDraft": False, "labels": [{"name": x} for x in labels],
            "files": [{"path": f} for f in files], "changedFiles": len(files), "statusCheckRollup": list(checks)}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PR_MERGE_TELEGRAM_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    (tmp_path / "store").mkdir()
    return tmp_path


def test_applier_is_held_and_never_merges():
    assert set(mhp.held_classes(["scripts/lib/pr_review_apply.py"])) == {"merge_deploy_control"}
    text = (ROOT / "scripts/lib/pr_review_apply.py").read_text()
    assert "pr merge" not in text and "promote" not in text.replace("pushes or promotes", "")


def test_only_operator_merge_label_decisions_are_pending():
    rows = [approve_row(h="a"), approve_row(actor="codex", h="b"), approve_row(effect="REVIEW_APPROVED_NO_LABEL", h="c"),
            {**approve_row(h="d"), "decision": "HOLD"}, approve_row(h="e")]
    assert [r["hash_self"][0] for r in pra.pending(rows, {"e" * 64})] == ["a"]


def test_labels_bound_head_once_and_writes_binding(store):
    added = []
    out = pra.run(repo="fixture/repo", apply=True, rows=[approve_row()], view=lambda r, n: view(),
                  add_label=lambda pr, repo: added.append(pr) or {"ok": True})
    assert added == [9101] and out[0]["outcome"] == "labeled" and out[0]["source"] == "cc_review"
    assert out[0]["schema"] == "PrMergeHeadBinding@v1" and out[0]["ledger_hash"] == "x" * 64
    assert pra.bindings()[9101]["head_sha"] == H1
    again = pra.run(repo="fixture/repo", apply=True, rows=[approve_row()], view=lambda r, n: view(),
                    add_label=lambda pr, repo: added.append(pr) or {"ok": True})
    assert again == [] and added == [9101]


@pytest.mark.parametrize("v,reason", [
    (view(head=H2), "head moved"),
    (view(files=("scripts/brokers/fixture.py",)), "held: the operator's own merge"),
    (view(labels=("held",)), "held: the operator's own merge"),
    (view(checks=[{**GREEN[0], "conclusion": "FAILURE"}] + GREEN[1:]), "required checks not green"),
    (view(state="MERGED"), "PR is not open"),
])
def test_refusals_record_reason_and_add_no_label(store, v, reason):
    added = []
    out = pra.run(repo="fixture/repo", apply=True, rows=[approve_row()], view=lambda r, n: v,
                  add_label=lambda pr, repo: added.append(pr) or {"ok": True})
    assert added == [] and out[0]["outcome"] == "refused" and out[0]["reason"] == reason
    assert 9101 not in pra.bindings()


def test_dry_run_writes_nothing(store):
    out = pra.run(repo="fixture/repo", apply=False, rows=[approve_row()], view=lambda r, n: view(),
                  add_label=lambda *a, **k: pytest.fail("label in dry run"))
    assert out[0]["outcome"] == "would_label" and not pra.outcomes_path().exists()


def _review(store_obj, pr, head, verdict="MERGE", findings=()):
    rec = {"schema": R.SCHEMA, "pr": pr, "head_sha": head, "verdict": verdict, "findings": list(findings),
           "created_at": "2031-03-04T17:00:00+00:00"}
    rec["document_sha"] = R.document_sha(rec)
    store_obj.write_review(rec)


def test_d1_partition_missing_hold_blocker_and_operator_hold(store):
    s = R.Store(R.store_dir(store / "state"), approved=lambda: True)
    _review(s, 9101, H1)
    _review(s, 9102, H1, verdict="HOLD")
    _review(s, 9103, H1, findings=[{"severity": "BLOCKER"}])
    _review(s, 9105, H1)
    _review(s, 9106, H2)
    ready = [{"pr": n, "head_sha": H1, "title": f"Fixture {n}"} for n in (9101, 9102, 9103, 9104, 9105, 9106)]
    rows = [{"event": "DECIDED", "kind": "MERGE", "decision": "HOLD", "item_id": "pr:9105", "head_sha": H1}]
    keep, out = pra.partition(ready, store=s, rows=rows)
    assert [i["pr"] for i in keep] == [9101]
    reasons = {i["pr"]: i["review_reason"] for i in out}
    assert reasons == {9102: "review says hold", 9103: "blocker finding", 9104: "no review of this head",
                       9105: "you held it in the review", 9106: "no review of this head"}


def _pr(n, head=H1):
    return {"number": n, "title": f"Fixture change {n}", "url": f"https://example.test/pull/{n}", "headRefOid": head,
            "isDraft": False, "labels": [], "body": "## Summary\nDoes a thing.\n", "files": [{"path": "docs/x.md"}],
            "changedFiles": 1, "statusCheckRollup": GREEN, "baseRefName": "main"}


def test_digest_d1_excludes_unreviewed_and_adds_review_buttons(store, monkeypatch):
    s = R.Store(R.store_dir(store / "state"), approved=lambda: True)
    _review(s, 9101, H1)
    sent = []
    monkeypatch.setattr(pmd, "_send", lambda m, *, priority, reply_markup=None: sent.append((m, reply_markup)) or (True, ["1"], "accepted"))
    monkeypatch.setattr(pmd, "list_open_prs", lambda repo, limit: [_pr(9101), _pr(9102)])
    monkeypatch.setattr(pra, "review_gate_active", lambda: True)
    monkeypatch.setattr(pra, "ledger_rows", lambda: [])
    monkeypatch.setattr(pra, "review_url", lambda pr, head: f"https://cc.example.test/v3/approvals/pr:{pr}?head={head[:9]}")
    out = pmd.run_digest(apply=True)
    assert out["ready"] == [9101] and out["needs_review"] == [{"pr": 9102, "reason": "no review of this head"}]
    text, kb = sent[0]
    assert "Open the review" in text and "#9102" in text
    rows = kb["inline_keyboard"]
    assert rows[0][0]["text"] == "✅ Approve all (1)"
    urls = [b["url"] for row in rows for b in row if "url" in b]
    assert urls == ["https://cc.example.test/v3/approvals/pr:9101?head=a1a1a1a1a", "https://cc.example.test/v3/approvals/pr:9102?head=a1a1a1a1a"]
    assert all(len(b["callback_data"].encode()) <= 64 for row in rows for b in row if "callback_data" in b)


def test_digest_unchanged_before_the_reviewer_is_live(store, monkeypatch):
    monkeypatch.setattr(pmd, "_send", lambda m, *, priority, reply_markup=None: (True, ["1"], "accepted"))
    monkeypatch.setattr(pmd, "list_open_prs", lambda repo, limit: [_pr(9101), _pr(9102)])
    assert not pra.review_gate_active()  # this repo has no approved pr_reviews row (D5 is a separate PR)
    out = pmd.run_digest(apply=False)
    assert out["ready"] == [9101, 9102] and out["needs_review"] == []
    assert not any("url" in b for row in out["reply_markup"]["inline_keyboard"] for b in row)


def test_cc_review_binding_keeps_label_through_reconcile(store, monkeypatch):
    pra.run(repo="fixture/repo", apply=True, rows=[approve_row()], view=lambda r, n: view(),
            add_label=lambda pr, repo: {"ok": True})
    assert pmd.approved_bindings()[9101]["source"].startswith("cc_review:")
    labelled = {**_pr(9101), "labels": [{"name": pmt.LABEL}]}
    monkeypatch.setattr(pmd, "list_open_prs", lambda repo, limit: [labelled])
    removed = []
    monkeypatch.setattr(pmt, "remove_operator_merge_label", lambda pr, *, repo=pmt.DEFAULT_REPO: removed.append(pr) or {"ok": True})
    res = pmd.reconcile_head_binding("fixture/repo", apply=True, cfg=pmd.load_config())
    assert res == [{"pr": 9101, "action": "bound_ok", "head": H1[:9]}] and removed == []
    moved = {**labelled, "headRefOid": H2}
    monkeypatch.setattr(pmd, "list_open_prs", lambda repo, limit: [moved])
    monkeypatch.setattr(pmt, "comment_on_pr", lambda *a, **k: {"ok": True})
    res = pmd.reconcile_head_binding("fixture/repo", apply=True, cfg=pmd.load_config())
    assert res[0]["action"] == "label_removed" and removed == [9101]
