"""Independent PR review (Design approvals-pr-review/v001; docs/ops/PR_REVIEW_MODAL_SPEC.md).

Synthetic PRs only (numbers 91xx, invented titles, paths and SHAs). GitHub, the model, the credit book, the status
poster and the ledger clock are stubbed; nothing here reaches the network, the token manager or a real store.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import pr_independent_review as runner
from scripts.lib import operator_approvals as core
from scripts.lib import operator_approvals_api as api
from scripts.lib import pr_review as R
from scripts.lib import pr_review_view as V

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2031, 3, 4, 17, 0, tzinfo=timezone.utc)
HEAD = "a1" * 20
HEAD2 = "b2" * 20
BASE = "c3" * 20
CFG = R.load_config()

DIFF = """diff --git a/scripts/fixture_job.py b/scripts/fixture_job.py
index 1111111..2222222 100644
--- a/scripts/fixture_job.py
+++ b/scripts/fixture_job.py
@@ -10,3 +10,5 @@ def run():
     a = 1
-    b = 2
+    b = 3
+    c = 4
+    return a + b + c
diff --git a/tests/test_fixture_job.py b/tests/test_fixture_job.py
new file mode 100644
--- /dev/null
+++ b/tests/test_fixture_job.py
@@ -0,0 +1,2 @@
+def test_run():
+    assert True
"""
FILES = [{"path": "scripts/fixture_job.py", "additions": 3, "deletions": 1, "status": "modified"},
         {"path": "tests/test_fixture_job.py", "additions": 2, "deletions": 0, "status": "added"}]
GREEN = [{"name": c, "conclusion": "SUCCESS"} for c in R.required_checks()]
CREDIT_OK = {"status": "OK", "today_used_usd": "1.00", "daily_cap_usd": "10", "reserved_today_usd": "0",
             "remaining_budget_usd": "150", "expiry": "2031-04-01T00:00:00+00:00"}


def hunks():
    return R.split_hunks(DIFF)


def model_json(hs, **over):
    doc = {"summary": "Changes a fixture sum. Touches nothing else.", "risk": {"level": "LOW", "why": "small"},
           "hunk_notes": {h["id"]: "explains the hunk" for h in hs}, "findings": [], "verdict": "MERGE"}
    doc.update(over)
    return json.dumps(doc)


# ── harness ──────────────────────────────────────────────────────────────────


def test_split_hunks_lines_and_stable_ids():
    hs = hunks()
    assert [h["file"] for h in hs] == ["scripts/fixture_job.py", "tests/test_fixture_job.py"]
    assert (hs[0]["start_line"], hs[0]["end_line"], hs[0]["added"], hs[0]["removed"]) == (10, 14, 3, 1)
    assert hs[1]["start_line"] == 1 and hs[1]["added"] == 2
    assert [h["id"] for h in hunks()] == [h["id"] for h in hs]


def test_data_quality_gate_refuses_moved_head_partial_list_and_missing_file():
    hs = hunks()
    ok = dict(files=FILES, changed_files=2, hunks=hs, head_now=HEAD, head=HEAD, diff_text=DIFF)
    assert R.data_quality_gate(**ok) is None
    assert "moved" in R.data_quality_gate(**{**ok, "head_now": HEAD2})
    assert "partial" in R.data_quality_gate(**{**ok, "changed_files": 3})
    assert "missing" in R.data_quality_gate(**{**ok, "hunks": hs[:1]})
    assert "empty" in R.data_quality_gate(**{**ok, "diff_text": "  "})


def test_author_from_trailers_and_independence():
    msgs = ["feat: x\n\nCo-Authored-By: Claude Opus 5.5 <noreply@example.test>\nClaude-Session: https://example.test/s/session_fixture01"]
    author = R.author_identity(msgs, "Agent: claude-fixture", "fixture-login")
    assert author["vendor"] == "Claude Code" and author["session"] == "session_fixture01"
    assert author["model"] == "Claude Opus 5.5"
    rev = {"id": R.reviewer_id("0304-1700-abc"), "model": "Claude Sonnet 5.5"}
    ind = R.independence(author, rev)
    assert ind["ok"] and ind["rule"] == "AGENTS.md §28.15 item 10" and not ind["same_model_family"]
    clash = R.independence({**author, "ids": author["ids"] + [rev["id"]]}, rev)
    assert not clash["ok"]


def test_rules_risk_floor_dropped_findings_blocker_and_notes():
    hs = hunks()
    inside = {"severity": "MINOR", "title": "t", "file": "scripts/fixture_job.py", "line": 12, "detail": "", "suggestion": ""}
    outside = {**inside, "line": 900}
    m = R.parse_model(model_json(hs, findings=[inside, outside]))
    r = R.apply_rules(m, hunks=hs, held=[], shared_infra=True, gate_defect=None, unexplained_max=0.1)
    assert r["risk"]["level"] == "MEDIUM" and r["dropped_findings"] == 1 and len(r["findings"]) == 1
    assert r["verdict"] == "MERGE_WITH_NOTES"
    held = R.apply_rules(m, hunks=hs, held=["broker_order"], shared_infra=False, gate_defect=None, unexplained_max=0.1)
    assert held["risk"]["level"] == "HIGH"
    blocker = R.parse_model(model_json(hs, findings=[{**inside, "severity": "BLOCKER"}]))
    assert R.apply_rules(blocker, hunks=hs, held=[], shared_infra=False, gate_defect=None, unexplained_max=0.1)["verdict"] == "HOLD"
    unexplained = R.parse_model(model_json(hs, hunk_notes={hs[0]["id"]: "only one"}))
    r2 = R.apply_rules(unexplained, hunks=hs, held=[], shared_infra=False, gate_defect=None, unexplained_max=0.1)
    assert r2["verdict"] == "CANNOT_REVIEW" and r2["unexplained_hunks"] == 1
    assert R.apply_rules(None, hunks=hs, held=[], shared_infra=False, gate_defect="partial", unexplained_max=0.1)["verdict"] == "CANNOT_REVIEW"


def test_parse_model_fenced_and_invalid():
    hs = hunks()
    assert R.parse_model("```json\n" + model_json(hs) + "\n```")["verdict"] == "MERGE"
    assert R.parse_model("not json") is None
    assert R.parse_model(json.dumps({"summary": "x", "verdict": "SHIP_IT"})) is None


def test_chunking_by_budget_and_too_large():
    hs = hunks()
    assert len(R.chunk_hunks(hs, 10_000, 3)) == 1
    assert len(R.chunk_hunks(hs, 260, 3)) == 2
    assert R.chunk_hunks(hs, 50, 3) is None


def test_held_classes_come_from_the_hold_list_never_the_model():
    assert R.held_classes(["scripts/brokers/fixture.py"], []) == ["broker_order"]
    assert R.held_classes(["docs/x.md"], ["held"]) == ["held_label"]
    assert R.held_classes(["docs/x.md"], []) == []


def test_d1_approve_all_eligibility():
    rec = {"head_sha": HEAD, "verdict": "MERGE", "findings": []}
    assert R.approve_all_eligible(rec, HEAD) == (True, "reviewed")
    assert not R.approve_all_eligible(None, HEAD)[0]
    assert not R.approve_all_eligible(rec, HEAD2)[0]
    assert not R.approve_all_eligible({**rec, "verdict": "HOLD"}, HEAD)[0]
    assert not R.approve_all_eligible({**rec, "findings": [{"severity": "BLOCKER"}]}, HEAD)[0]


# ── budget (D3, §29) ────────────────────────────────────────────────────────


def test_preflight_quotes_every_limit_and_waits_without_credit():
    pf = R.preflight(kind="review", tier="normal", pr=9101, cfg=CFG, spend_rows=[], credit=CREDIT_OK, now=NOW, env={})
    assert pf["ok"] and pf["process_id"] == "pr_independent_review"
    assert set(pf["limits"]) >= {"credit", "process", "combined", "global_daily_usd_cap", "headroom_usd"}
    assert pf["limits"]["combined"]["daily_cost_cap_usd"] == 2.0
    deep = R.preflight(kind="review", tier="deep", pr=9101, cfg=CFG, spend_rows=[], credit=CREDIT_OK, now=NOW, env={})
    assert deep["process_id"] == "pr_independent_review_deep"
    for status in ("EXPIRED", "PAUSED_TODAY", "UNAVAILABLE", "EXHAUSTED"):
        w = R.preflight(kind="review", tier="normal", pr=9101, cfg=CFG, spend_rows=[], credit={**CREDIT_OK, "status": status}, now=NOW, env={})
        assert not w["ok"] and status in w["reason"]
    assert R.preflight(kind="review", tier="normal", pr=1, cfg=CFG, spend_rows=[], credit={**CREDIT_OK, "status": "EXPIRED"},
                       now=NOW, env={})["next_try_at"] is None


def test_combined_two_dollar_cap_and_daily_counts():
    spent = [{"at": R.iso(NOW), "kind": "review", "call": 1, "pr": 9100 + i, "provider": "anthropic",
              "process_id": "pr_independent_review_deep", "cost_usd": 0.39} for i in range(5)]
    pf = R.preflight(kind="review", tier="normal", pr=9101, cfg=CFG, spend_rows=spent, credit=CREDIT_OK, now=NOW, env={})
    assert not pf["ok"] and "combined" in pf["reason"]  # 1.95 spent; a $0.10 call would pass $2.00
    many = [{"at": R.iso(NOW), "kind": "review", "call": 1, "pr": 9000 + i, "provider": "anthropic",
             "process_id": "pr_independent_review", "cost_usd": 0.0} for i in range(20)]
    assert "20 reviews" in R.preflight(kind="review", tier="normal", pr=1, cfg=CFG, spend_rows=many, credit=CREDIT_OK, now=NOW, env={})["reason"]
    same = many[:3]
    for r in same:
        r["pr"] = 9101
    assert "this PR" in R.preflight(kind="review", tier="normal", pr=9101, cfg=CFG, spend_rows=same, credit=CREDIT_OK, now=NOW, env={})["reason"]
    yesterday = [{**spent[0], "at": R.iso(NOW - timedelta(days=1)), "cost_usd": 5}]
    assert R.preflight(kind="review", tier="normal", pr=1, cfg=CFG, spend_rows=yesterday, credit=CREDIT_OK, now=NOW, env={})["ok"]


def test_registry_rows_caps_tiers_and_never_deepseek():
    reg = {p["id"]: p for p in json.loads((ROOT / "config/llm_process_registry.json").read_text())["processes"]}
    credit = json.loads((ROOT / "config/anthropic_credit_policy.json").read_text())
    routing = json.loads((ROOT / "config/llm_routing_policy.json").read_text())
    procs = routing["policies"][routing.get("default_policy_id", "default")]["processes"]
    for pid in ("pr_independent_review", "pr_independent_review_deep", "pr_independent_review_oauth"):
        row = reg[pid]
        assert not any("deepseek" in lane for lane in row["allowed_lanes"])
        assert row["advisory_only"] and not row["tools_allowed"] and not row["fallback_allowed"] and row["circuit_breaker"]
        assert pid in procs
    assert reg["pr_independent_review"]["daily_cost_cap_usd"] == 2.0
    assert reg["pr_independent_review_deep"]["daily_cost_cap_usd"] == 2.0
    assert reg["pr_independent_review_oauth"]["daily_cost_cap_usd"] == 0.05  # nominal; OAuth costs $0
    assert reg["pr_independent_review_oauth"]["allowed_lanes"] == ["chatgpt", "grok"]
    assert credit["ops_process_tiers"]["pr_independent_review"] == "mid"            # Sonnet 5.5
    assert credit["ops_process_tiers"]["pr_independent_review_deep"] == "high"      # Opus 5.5
    assert credit["models"]["mid"] == "claude-sonnet-5-5" and credit["models"]["high"] == "claude-opus-5-5"
    assert {"pr_independent_review", "pr_independent_review_deep"} <= set(credit["anthropic_only_processes"])
    assert "pr_independent_review_oauth" not in credit["ops_process_tiers"]
    assert CFG["budget"]["combined_daily_cost_cap_usd"] == 2.0 and CFG["budget"]["max_reviews_per_day"] == 20
    assert CFG["commit_status"]["required_by_mergify"] is False
    assert "independent-review" not in (ROOT / ".mergify.yml").read_text()  # D4: not required yet


# ── store (D5) ──────────────────────────────────────────────────────────────


def approved_registry():
    return {"domains": [{"domain": "pr_reviews", "store": {"dir": "coordination/pr_reviews"},
                         "writer": "scripts/pr_independent_review.py",
                         "approval": {"approved_by": "operator", "approved_on": "2031-03-04", "reference": "fixture"}}]}


def test_store_approval_row_required():
    assert R.store_approved(approved_registry(), CFG)
    bad = approved_registry()
    bad["domains"][0]["approval"]["approved_by"] = "agent"
    assert not R.store_approved(bad, CFG)
    assert not R.store_approved({"domains": []}, CFG)
    # This PR does not activate the store (D5 is the coordinator's separate PR).
    assert not R.registry_store_approved(ROOT, CFG)


def test_store_refuses_writes_until_approved_and_never_overwrites(tmp_path):
    s = R.Store(tmp_path / "pr_reviews", approved=lambda: False)
    with pytest.raises(R.StoreRefused, match="STORE_APPROVAL_PENDING"):
        s.add_spend({"at": R.iso(NOW)})
    assert not (tmp_path / "pr_reviews").exists()
    s.approved = lambda: True
    rec = {"schema": R.SCHEMA, "pr": 9101, "head_sha": HEAD, "verdict": "MERGE", "created_at": R.iso(NOW)}
    rec["document_sha"] = R.document_sha(rec)
    s.write_review(rec)
    with pytest.raises(R.StoreRefused, match="REVIEW_EXISTS"):
        s.write_review(rec)
    assert s.latest(9101)["head_sha"] == HEAD and len(s.index()) == 1


# ── runner ──────────────────────────────────────────────────────────────────


class Fake:
    def __init__(self, *, files=None, labels=(), credit=None, provider="anthropic", texts=None, committed=None, body=""):
        self.files = files or FILES
        self.labels = list(labels)
        self.credit_row = credit or CREDIT_OK
        self.provider = provider
        self.texts = list(texts or [])
        self.calls: list[tuple] = []
        self.statuses: list[tuple] = []
        self.committed = committed or (NOW - timedelta(hours=1))
        self.body = body
        self.qs: list[dict] = []

    def pr(self, n=9101, head=HEAD, draft=False, rollup=GREEN):
        return {"number": n, "title": "Fixture: tidy a sum", "url": f"https://example.test/pr/{n}", "headRefOid": head,
                "baseRefOid": BASE, "baseRefName": "main", "isDraft": draft, "labels": [{"name": x} for x in self.labels],
                "statusCheckRollup": rollup, "changedFiles": len(self.files), "createdAt": R.iso(NOW - timedelta(hours=2))}

    def deps(self, prs):
        def model(pid, prompt, max_tokens, lanes=None, response_json=True):
            self.calls.append((pid, lanes, max_tokens))
            if self.texts:
                t = self.texts.pop(0)
                if isinstance(t, Exception):
                    raise t
                return t, {"provider": self.provider if not lanes else lanes[0], "model": "fixture-model", "cost_usd": 0.0 if lanes else 0.07}
            return model_json(hunks()), {"provider": self.provider if not lanes else lanes[0], "model": "fixture-model",
                                         "cost_usd": 0.0 if lanes else 0.07}
        return runner.Deps(
            list_prs=lambda repo: prs,
            view_pr=lambda repo, n: {**self.pr(n), "body": self.body, "files": self.files,
                                     "commits": [{"messageHeadline": "fixture", "messageBody": "Claude-Session: https://example.test/s/session_fx",
                                                  "committedDate": R.iso(self.committed)}], "author": {"login": "fixture-login"}},
            diff=lambda repo, b, h: DIFF, head=lambda repo, n: HEAD, model=model,
            post_status=lambda repo, sha, payload, env: self.statuses.append((sha, payload)) or {"posted": False, "reason": "STATUS_IDENTITY_NOT_PROVISIONED"},
            questions=lambda: self.qs, credit=lambda now: self.credit_row,
            agents_text=lambda: "# 0 · If you read nothing else\n\nrule\n\n## 25.10 Mergify merges, the host promotes (25.0.0)\n\nmerge\n",
            clock=lambda: NOW)


def store(tmp_path, ok=True):
    return R.Store(tmp_path / "pr_reviews", approved=lambda: ok)


def test_dry_run_calls_nothing_and_writes_nothing(tmp_path):
    f = Fake()
    out = runner.cycle(repo="fixture/repo", cfg=CFG, store=store(tmp_path), deps=f.deps([f.pr(), f.pr(9102, draft=True)]), apply=False)
    assert [r["pr"] for r in out["would_review"]] == [9101] and f.calls == [] and f.statuses == []
    assert out["would_review"][0]["preflight"]["process_id"] == "pr_independent_review"
    assert not (tmp_path / "pr_reviews").exists()


def test_apply_refused_until_store_approved(tmp_path):
    f = Fake()
    out = runner.cycle(repo="fixture/repo", cfg=CFG, store=store(tmp_path, ok=False), deps=f.deps([f.pr()]), apply=True)
    assert out["refused_all"] == "STORE_APPROVAL_PENDING" and f.calls == [] and not (tmp_path / "pr_reviews").exists()


def test_settle_ten_minutes_after_last_push(tmp_path):
    f = Fake(committed=NOW - timedelta(minutes=4))
    out = runner.cycle(repo="fixture/repo", cfg=CFG, store=store(tmp_path), deps=f.deps([f.pr()]), apply=True)
    assert out["settling"][0]["next_try_at"] == R.iso(NOW + timedelta(minutes=6)) and f.calls == []


def test_normal_pr_sonnet_review_written_once_status_attempted_spend_logged(tmp_path):
    f = Fake()
    s = store(tmp_path)
    out = runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    assert out["reviewed"][0]["verdict"] == "MERGE"
    assert [c[0] for c in f.calls] == ["pr_independent_review"]
    rec = s.review(9101, HEAD)
    assert rec["schema"] == "PrReview@v1" and rec["independent"]["ok"] and rec["second_read"] is None
    assert rec["reviewer"]["id"].startswith("host:pr_independent_review:") and rec["reviewer"]["cost_usd"] == 0.07
    assert rec["document_sha"] == R.document_sha(rec)
    assert all(h["note"] for a in rec["areas"] for fl in a["files"] for h in fl["hunks"])
    assert f.statuses[0][1]["context"] == "tradeai/independent-review" and f.statuses[0][1]["state"] == "success"
    assert rec["status_post"]["reason"] == "STATUS_IDENTITY_NOT_PROVISIONED"
    assert s.spend()[0]["process_id"] == "pr_independent_review"
    again = runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    assert again["already"] == [9101] and len(f.calls) == 1


def test_held_pr_opus_plus_free_oauth_second_read(tmp_path):
    held_files = FILES + [{"path": "scripts/brokers/fixture_adapter.py", "additions": 0, "deletions": 0, "status": "modified"}]
    f = Fake(files=held_files)
    s = store(tmp_path)
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    assert [c[0] for c in f.calls] == ["pr_independent_review_deep", "pr_independent_review_oauth"]
    assert f.calls[1][1] == ("chatgpt", "grok")
    rec = s.review(9101, HEAD)
    assert rec["classes"]["held"] == ["broker_order"] and rec["risk"]["level"] == "HIGH"
    assert rec["second_read"]["provider"] == "chatgpt" and rec["second_read"]["cost_usd"] == 0.0
    assert "held" in f.statuses[0][1]["description"]


def test_shared_infra_label_uses_deep_reviewer(tmp_path):
    f = Fake(labels=["shared-infra"])
    runner.cycle(repo="fixture/repo", cfg=CFG, store=store(tmp_path), deps=f.deps([f.pr()]), apply=True)
    assert f.calls[0][0] == "pr_independent_review_deep"


def test_deepseek_answer_discarded_and_schema_retry_once(tmp_path):
    f = Fake(provider="deepseek")
    s = store(tmp_path)
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    assert len(f.calls) == 2  # one retry
    assert s.review(9101, HEAD)["verdict"] == "CANNOT_REVIEW"


def test_unusable_credit_waits_with_no_paid_fallback(tmp_path):
    f = Fake(credit={**CREDIT_OK, "status": "EXPIRED"})
    s = store(tmp_path)
    out = runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    assert f.calls == [] and s.review(9101, HEAD) is None
    assert s.status(9101)["state"] == "WAITING_FOR_CREDIT" and out["waiting"][0]["reason"] == "credit EXPIRED"
    f2 = Fake(texts=[RuntimeError("ANTHROPIC_CREDIT_UNAVAILABLE: anthropic-only process; queue and retry")])
    s2 = R.Store(tmp_path / "two", approved=lambda: True)
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s2, deps=f2.deps([f2.pr()]), apply=True)
    assert s2.status(9101)["state"] == "WAITING_FOR_CREDIT" and s2.review(9101, HEAD) is None


def test_red_or_draft_prs_get_no_review(tmp_path):
    f = Fake()
    red = [{"name": c, "conclusion": "FAILURE"} for c in R.required_checks()]
    out = runner.cycle(repo="fixture/repo", cfg=CFG, store=store(tmp_path), deps=f.deps([f.pr(rollup=red), f.pr(9102, draft=True)]), apply=False)
    assert out["would_review"] == []


def test_question_answered_once_within_cap(tmp_path):
    f = Fake()
    s = store(tmp_path)
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    f.qs = [{"event": "QUESTION", "item_id": "pr:9101", "source_sha": HEAD, "question": "Does this touch trading?",
             "hash_self": "q" * 64, "at": R.iso(NOW)}]
    f.texts = ["No. It changes a fixture sum only."]
    out = runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    assert out["answered"] and s.answers()[0]["answer"].startswith("No.")
    assert f.calls[-1][0] == "pr_independent_review"
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    assert len(s.answers()) == 1


def test_status_poster_never_uses_gh_without_the_provisioned_token(monkeypatch):
    monkeypatch.delenv("TRADEAI_REVIEW_STATUS_TOKEN", raising=False)
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    assert runner.default_post_status("fixture/repo", HEAD, {}, "TRADEAI_REVIEW_STATUS_TOKEN")["reason"] == "STATUS_IDENTITY_NOT_PROVISIONED"


def test_new_code_never_merges_labels_or_comments():
    for rel in ("scripts/pr_independent_review.py", "scripts/lib/pr_review.py", "scripts/lib/pr_review_view.py"):
        text = (ROOT / rel).read_text()
        assert "pr merge" not in text and "--add-label" not in text and "pr comment" not in text and "pr review" not in text
        assert not re.search(r"\b(place_order|submit_order)\b", text)


# ── ledger + view + API ─────────────────────────────────────────────────────


def _review(tmp_path, *, files=FILES, findings=()):
    s = store(tmp_path)
    f = Fake(files=files)
    if findings:
        f.texts = [model_json(hunks(), findings=list(findings))]
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    return s


def _ctx(tmp_path, monkeypatch, approved=True):
    monkeypatch.setattr(R, "registry_store_approved", lambda root=None, cfg=None: True)
    monkeypatch.setattr(api, "state_root", lambda: tmp_path)
    clock = [NOW]
    monkeypatch.setattr(R, "utc_now", lambda: NOW)
    ledger = core.DecisionLedger(tmp_path / "ledger.jsonl", approved=lambda: approved, clock=lambda: clock[0])
    sources = {"pr_reviews": lambda: V.merge_items(state_root=tmp_path, root=ROOT, code_sha="", now=NOW)}
    ctx = api.Ctx(principal=lambda: "tailnet:operator@example.test", listener=lambda: "serve_proxy",
                  csrf=lambda m, p: (True, ""), allowed_logins=frozenset({"operator@example.test"}),
                  sources=sources, ledger=ledger, policy=lambda: {}, clock=lambda: clock[0], can_read=lambda: True)
    return ctx, clock


def _write_snapshot(tmp_path, head=HEAD, green=True):
    R.Store(R.store_dir(tmp_path, CFG), approved=lambda: True).write_snapshot(
        {"as_of": R.iso(NOW), "prs": [{"pr": 9101, "title": "Fixture: tidy a sum", "head_sha": head, "draft": False,
                                        "labels": [], "checks_green": green, "checks": {}, "created_at": R.iso(NOW)}]})


def test_merge_item_decide_approve_and_effects(tmp_path, monkeypatch):
    finding = {"severity": "MINOR", "title": "fixture finding", "file": "scripts/fixture_job.py", "line": 11, "detail": "d", "suggestion": "s"}
    s = R.Store(R.store_dir(tmp_path, CFG), approved=lambda: True)
    f = Fake()
    f.texts = [model_json(hunks(), findings=[finding])]
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    _write_snapshot(tmp_path)
    ctx, clock = _ctx(tmp_path, monkeypatch)
    status, q = api.handle(api.PREFIX + "/approvals?kind=MERGE", "GET", None, {"kind": "MERGE"}, ctx=ctx)
    assert status == 200 and [i["id"] for i in q["data"]["items"]] == ["pr:9101"]
    assert q["data"]["items"][0]["pill"]["label"] == "Merge · 1 follow-up"
    status, item = api.handle(api.PREFIX + "/approvals/pr%3A9101", "GET", ctx=ctx)
    doc = item["data"]["document"]
    assert doc["document_sha"] == s.review(9101, HEAD)["document_sha"] and doc["source_sha"] == HEAD
    assert item["data"]["decisions_store_approved"] is True
    current = lambda: ctx.sources["pr_reviews"]()["rows"][0]  # noqa: E731
    review = ctx.ledger.start(ctx.principal(), current, doc["document_sha"])
    base = {"document_sha": doc["document_sha"], "review_id": review["review_id"], "request_id": "request_123456"}
    with pytest.raises(core.Refused, match="CHANGES_UNREAD"):
        ctx.ledger.decide(ctx.principal(), current, {**base, "decision": "APPROVE"})
    with pytest.raises(core.Refused, match="INVALID_DECISION"):
        ctx.ledger.decide(ctx.principal(), current, {**base, "decision": "REJECT"})
    for ch in doc["changes"]:
        ctx.ledger.marker(ctx.principal(), current, {**base, "change_id": ch["id"], "phase": "enter"})
        clock[0] += timedelta(seconds=3)
        ctx.ledger.marker(ctx.principal(), current, {**base, "change_id": ch["id"], "phase": "read"})
    row = ctx.ledger.decide(ctx.principal(), current, {**base, "decision": "APPROVE"})
    assert row["effect"] == "OPERATOR_MERGE_LABEL" and row["head_sha"] == HEAD and row["pr"] == 9101 and not row["held"]


def test_stale_review_cannot_be_approved_and_held_records_no_label(tmp_path, monkeypatch):
    _review(tmp_path / "x")  # unrelated store, ignore
    s = R.Store(R.store_dir(tmp_path, CFG), approved=lambda: True)
    held_files = FILES + [{"path": "scripts/brokers/fixture_adapter.py", "additions": 0, "deletions": 0, "status": "modified"}]
    f = Fake(files=held_files)
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    _write_snapshot(tmp_path)
    ctx, _ = _ctx(tmp_path, monkeypatch)
    current = lambda: ctx.sources["pr_reviews"]()["rows"][0]  # noqa: E731
    it = current()
    assert it["pill"]["label"] == "Held · your own merge"
    review = ctx.ledger.start(ctx.principal(), current, it["document"]["document_sha"])
    row = ctx.ledger.decide(ctx.principal(), current, {"document_sha": it["document"]["document_sha"], "review_id": review["review_id"],
                                                       "request_id": "request_held01", "decision": "APPROVE"})
    assert row["effect"] == "REVIEW_APPROVED_NO_LABEL" and row["held"]
    _write_snapshot(tmp_path, head=HEAD2)  # a new push
    stale = current()
    assert stale["pill"]["label"] == "New push · re-reviewing" and stale["merge"]["refusal"] == "REVIEW_STALE"
    assert stale["document"]["document_sha"] != it["document"]["document_sha"] and stale["document"]["changes"] == []
    r2 = ctx.ledger.start(ctx.principal(), current, stale["document"]["document_sha"])
    with pytest.raises(core.Refused, match="REVIEW_STALE"):
        ctx.ledger.decide(ctx.principal(), current, {"document_sha": stale["document"]["document_sha"], "review_id": r2["review_id"],
                                                     "request_id": "request_stale1", "decision": "APPROVE"})
    held_row = ctx.ledger.decide(ctx.principal(), current, {"document_sha": stale["document"]["document_sha"], "review_id": r2["review_id"],
                                                            "request_id": "request_hold01", "decision": "HOLD"})
    assert held_row["effect"] == "HOLD_THIS_HEAD"


def test_hold_refused_for_non_merge_items(tmp_path):
    row = core.item(ident="policy-1", kind="POLICY", title="t", proposed_by=None, created_at=None, source="f",
                    doc=core.document("x\n", source_sha="d" * 40))
    led = core.DecisionLedger(tmp_path / "l.jsonl", approved=lambda: True, clock=lambda: NOW)
    rv = led.start("tailnet:op", lambda: row, row["document"]["document_sha"])
    with pytest.raises(core.Refused, match="INVALID_DECISION"):
        led.decide("tailnet:op", lambda: row, {"document_sha": row["document"]["document_sha"], "review_id": rv["review_id"],
                                                "request_id": "request_123456", "decision": "HOLD"})


def test_question_route_records_and_store_pending_refuses(tmp_path, monkeypatch):
    s = R.Store(R.store_dir(tmp_path, CFG), approved=lambda: True)
    f = Fake()
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    _write_snapshot(tmp_path)
    ctx, _ = _ctx(tmp_path, monkeypatch)
    sha = ctx.sources["pr_reviews"]()["rows"][0]["document"]["document_sha"]
    status, out = api.handle(api.PREFIX + "/approvals/pr%3A9101/question", "POST",
                             {"question": "Does this touch trading?", "document_sha": sha, "request_id": "request_q00001"}, ctx=ctx)
    assert status == 200 and out["data"]["event"] == "QUESTION" and out["data"]["source_sha"] == HEAD
    status, item = api.handle(api.PREFIX + "/approvals/pr%3A9101", "GET", ctx=ctx)
    assert item["data"]["thread"]["questions"][0]["question"] == "Does this touch trading?"
    assert item["data"]["thread"]["questions"][0]["answer"] is None
    pending, _ = _ctx(tmp_path, monkeypatch, approved=False)
    status, out = api.handle(api.PREFIX + "/approvals/pr%3A9101/question", "POST",
                             {"question": "q", "document_sha": sha, "request_id": "request_q00002"}, ctx=pending)
    assert status == 503 and out["error"] == "STORE_APPROVAL_PENDING"


def test_summary_strip_counts_spend_and_store_states(tmp_path, monkeypatch):
    s = R.Store(R.store_dir(tmp_path, CFG), approved=lambda: True)
    f = Fake()
    runner.cycle(repo="fixture/repo", cfg=CFG, store=s, deps=f.deps([f.pr()]), apply=True)
    _write_snapshot(tmp_path)
    ctx, _ = _ctx(tmp_path, monkeypatch, approved=False)
    status, out = api.handle(api.PREFIX + "/pr-reviews/summary", "GET", ctx=ctx)
    d = out["data"]
    assert status == 200 and d["counts"]["ready"] == 1 and d["spend"]["usd_today"] == 0.07 and d["spend"]["cap_usd"] == 2.0
    assert d["decisions_store_approved"] is False and d["store_approved"] is True
    assert d["label_applier_live"] in (True, False)


def test_no_snapshot_before_store_approval_is_empty_not_a_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "registry_store_approved", lambda root=None, cfg=None: False)
    out = V.merge_items(state_root=tmp_path, root=ROOT, code_sha="", now=NOW)
    assert out == {"rows": [], "gap": None}
