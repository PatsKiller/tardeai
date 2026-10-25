"""Exact-version reviews, actor/CSRF checks, source gaps and no authority escalation."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.lib import operator_approvals as c
from scripts.lib import operator_approvals_api as api

NOW = datetime(2032, 4, 12, 14, 0, tzinfo=timezone.utc)
SHA = "a" * 40


@pytest.fixture
def rig(tmp_path):
    clock = [NOW]
    row = c.item(ident="policy-42", kind="POLICY", title="Policy amendment", proposed_by="worker",
                 created_at=NOW.isoformat(), source="fixture", pr=42,
                 doc=c.document("# 0 · Rules\n\nNever bypass a denial.\n\n# 28 · Operations\n\nRead every change.",
                                source_sha=SHA, version="20.2.0", source_verified=True))
    ledger = c.DecisionLedger(tmp_path / "ledger.jsonl", approved=lambda: True, clock=lambda: clock[0])
    ctx = api.Ctx(principal=lambda: "tailnet:operator@example.test", listener=lambda: "serve_proxy",
                  csrf=lambda m, p: (True, ""), allowed_logins=frozenset({"operator@example.test"}),
                  sources={"fixture": lambda: [row]}, ledger=ledger, policy=lambda: {}, clock=lambda: clock[0],
                  can_read=lambda: True)
    return ctx, row, clock


def start(ctx, row):
    return ctx.ledger.start(ctx.principal(), lambda: row, row["document"]["document_sha"])


def decision(row, review, **extra):
    return {"document_sha": row["document"]["document_sha"], "review_id": review["review_id"],
            "decision": "APPROVE", "request_id": "request_123456", **extra}


def read_all(ctx, row, clock, review):
    for change in row["document"]["changes"]:
        body = decision(row, review, change_id=change["id"], phase="enter")
        ctx.ledger.marker(ctx.principal(), lambda: row, body)
        clock[0] += timedelta(seconds=3)
        ctx.ledger.marker(ctx.principal(), lambda: row, {**body, "phase": "read"})


def test_policy_token_binds_exact_document_commit_and_pr(rig):
    ctx, row, clock = rig
    review = start(ctx, row)
    read_all(ctx, row, clock, review)
    result = ctx.ledger.decide(ctx.principal(), lambda: row, decision(row, review))
    assert result["policy_token"] == f"APPROVE_AGENTS_POLICY_20_2_0 42 {SHA}"
    assert result["actor"] == "tailnet:operator@example.test"
    assert result["effect"] == "RECORD_ONLY"
    assert result["document_sha"] == row["document"]["document_sha"]


def test_unread_changes_refused_and_no_decision_written(rig):
    ctx, row, _ = rig
    review = start(ctx, row)
    with pytest.raises(c.Refused, match="CHANGES_UNREAD"):
        ctx.ledger.decide(ctx.principal(), lambda: row, decision(row, review))
    assert not any(r["event"] == "DECIDED" for r in ctx.ledger.rows())


@pytest.mark.parametrize("actor,listener", [("service-token", "serve_proxy"), ("tailnet:operator@example.test", "loopback"),
                                            ("tailnet:stranger@example.test", "serve_proxy"), ("codex", "serve_proxy"), ("", "serve_proxy")])
def test_agents_and_forged_body_actor_cannot_decide(rig, actor, listener):
    ctx, row, _ = rig
    ctx.principal, ctx.listener = lambda: actor, lambda: listener
    status, data = api.handle(api.PREFIX + "/approvals/policy-42/decide", "POST",
                              {"actor": "tailnet:operator@example.test", "decision": "APPROVE"}, ctx=ctx)
    assert status == 403 and data["error"] == "AGENT_CALLER_REFUSED"
    assert not ctx.ledger.path.exists()


@pytest.mark.parametrize("route", ["open", "read", "decide"])
def test_csrf_checked_on_every_write(rig, route):
    ctx, row, _ = rig
    ctx.csrf = lambda m, p: (False, "cross-site")
    status, data = api.handle(api.PREFIX + f"/approvals/policy-42/{route}", "POST", {}, ctx=ctx)
    assert status == 403 and data["error"] == "CSRF_REFUSED"
    assert not ctx.ledger.path.exists()


def test_get_does_not_create_ledger_or_embed_whole_documents(rig):
    ctx, _, _ = rig
    status, data = api.handle(api.PREFIX + "/approvals", "GET", ctx=ctx)
    assert status == 200 and data["data"]["pending_count"] == 1
    assert "document" not in data["data"]["items"][0]
    assert not ctx.ledger.path.exists()


def test_source_failure_is_unknown_count_and_preserves_known_rows(rig):
    ctx, _, _ = rig
    def broken():
        raise ValueError("do not expose raw error contents")
    ctx.sources["missing"] = broken
    data = api.queue(ctx)
    assert data["pending_count"] is None and data["known_pending_count"] == 1
    assert data["gaps"] == [{"source": "missing", "reason": "ValueError"}]


def test_text_change_resets_read_markers(rig):
    ctx, row, clock = rig
    review = start(ctx, row)
    read_all(ctx, row, clock, review)
    prior = decision(row, review)
    row["document"] = c.document("A different amendment", source_sha=SHA, version="20.2.0", source_verified=True)
    with pytest.raises(c.Refused, match="DOCUMENT_CHANGED"):
        ctx.ledger.decide(ctx.principal(), lambda: row, prior)


def test_actor_and_expiry_bound_read_session(rig):
    ctx, row, clock = rig
    review = start(ctx, row)
    with pytest.raises(c.Refused, match="REVIEW_SESSION_REFUSED"):
        ctx.ledger.decide("tailnet:someoneelse", lambda: row, decision(row, review))
    clock[0] += timedelta(minutes=31)
    with pytest.raises(c.Refused, match="REVIEW_EXPIRED"):
        ctx.ledger.decide(ctx.principal(), lambda: row, decision(row, review))


def test_marker_requires_continuous_three_seconds_on_server_clock(rig):
    ctx, row, clock = rig
    review = start(ctx, row)
    body = decision(row, review, change_id=row["document"]["changes"][0]["id"], phase="read")
    with pytest.raises(c.Refused, match="CHANGE_NOT_READ"):
        ctx.ledger.marker(ctx.principal(), lambda: row, body)
    ctx.ledger.marker(ctx.principal(), lambda: row, {**body, "phase": "enter"})
    clock[0] += timedelta(seconds=2)
    with pytest.raises(c.Refused, match="CHANGE_NOT_READ"):
        ctx.ledger.marker(ctx.principal(), lambda: row, body)
    ctx.ledger.marker(ctx.principal(), lambda: row, {**body, "phase": "leave"})
    clock[0] += timedelta(seconds=10)
    with pytest.raises(c.Refused, match="CHANGE_NOT_READ"):
        ctx.ledger.marker(ctx.principal(), lambda: row, body)


@pytest.mark.parametrize("kind", ["RELEASE", "SPEND", "ACTIVATE", "CONFLICT"])
def test_governed_actions_never_approved_by_ledger(rig, kind):
    ctx, row, clock = rig
    row["kind"], row["decision_mode"] = kind, "GOVERNED_PATH"
    review = start(ctx, row)
    read_all(ctx, row, clock, review)
    with pytest.raises(c.Refused, match="GOVERNED_ACTION_REQUIRED"):
        ctx.ledger.decide(ctx.principal(), lambda: row, decision(row, review))


def test_unverified_commit_content_cannot_mint_policy_token(rig):
    ctx, row, clock = rig
    row["document"]["source_verified"] = False
    review = start(ctx, row)
    read_all(ctx, row, clock, review)
    with pytest.raises(c.Refused, match="POLICY_BINDING_REQUIRED"):
        ctx.ledger.decide(ctx.principal(), lambda: row, decision(row, review))


def test_idempotent_decision_and_conflicting_retry(rig):
    ctx, row, clock = rig
    review = start(ctx, row)
    read_all(ctx, row, clock, review)
    body = decision(row, review)
    first = ctx.ledger.decide(ctx.principal(), lambda: row, body)
    assert ctx.ledger.decide(ctx.principal(), lambda: row, body) == first
    with pytest.raises(c.Refused, match="IDEMPOTENCY_CONFLICT"):
        ctx.ledger.decide(ctx.principal(), lambda: row, {**body, "decision": "REJECT"})
    assert sum(r["event"] == "DECIDED" for r in ctx.ledger.rows()) == 1


def test_simultaneous_decisions_have_only_one_winner(rig):
    ctx, row, clock = rig
    review = start(ctx, row)
    read_all(ctx, row, clock, review)
    def decide(i):
        try:
            return ctx.ledger.decide(ctx.principal(), lambda: row, decision(row, review, request_id=f"request_{i:08}"))["event"]
        except c.Refused as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, (1, 2)))
    assert sorted(outcomes) == ["ALREADY_DECIDED", "DECIDED"]
    assert len(ctx.ledger.rows()) > 1  # verifies the entire hash chain after concurrent writers


def test_corrupt_chain_fails_closed(rig):
    ctx, row, _ = rig
    start(ctx, row)
    ctx.ledger.path.write_text(ctx.ledger.path.read_text().replace("READ_STARTED", "forged"))
    with pytest.raises(c.Refused, match="LEDGER_CORRUPT"):
        ctx.ledger.rows()


def test_build_permission_cannot_enable_new_store(rig):
    ctx, row, _ = rig
    ctx.ledger.approved = lambda: False
    with pytest.raises(c.Refused, match="STORE_APPROVAL_PENDING"):
        start(ctx, row)
    assert not ctx.ledger.path.exists()
    assert not c.writes_approved({"proposed_domains": [{"id": "operator_decisions"}]})
    assert c.writes_approved({"domains": [{"id": "operator_decisions", "store": {"file": "governance/operator_decisions.jsonl"}, "writer": c.WRITER,
                                           "approval": {"approved_by": "operator", "approved_on": "2032-04-12", "reference": "exact sign-off"}}]})


def test_removals_require_reading_and_sensitive_sections_are_flagged():
    doc = c.document("# 0 · Rules\n\nMay proceed.", source_sha=SHA, base_text="# 0 · Rules\n\nNever proceed.")
    assert doc["prechecks"]["sensitive_sections"] == ["0"]
    assert doc["prechecks"]["weakens_rules"] == "REVIEW_REQUIRED"
    assert any(r["before"] == "Never proceed." for r in doc["changes"])


def test_policy_no_evidence_is_never_enforced():
    policy = c.policy_projection("# 0 · Rules\n\nNever delete.", source_sha=SHA)
    assert policy["counts"]["WRITTEN-only"] == len(policy["rules"])
    rule = policy["rules"][-1]["id"]
    forged = {rule: {"document_sha": "stale", "test_passed": True, "runtime_passed": True}}
    assert all(r["status"] == "WRITTEN-only" for r in c.policy_projection("# 0 · Rules\n\nNever delete.", source_sha=SHA, enforcement=forged)["rules"])


def test_explicit_ref_dedup_preserves_pending_governed_items(rig):
    ctx, row, _ = rig
    financial = c.item(ident="financial:action_queue:7", kind="FINANCIAL", title=row["title"], proposed_by=None,
                       created_at=None, source="action_queue", doc=row["document"], source_refs=["action_queue:7"])
    row["source_refs"].append("action_queue:7")
    ctx.sources["finance"] = lambda: [financial]
    data = api.queue(ctx)
    assert len(data["items"]) == 1 and data["items"][0]["requires_governed_action"]
    assert data["items"][0]["related_sources"]


def test_similar_titles_are_never_merged_without_reference(rig):
    ctx, row, _ = rig
    second = {**row, "id": "other", "source_refs": ["independent:other"]}
    ctx.sources["other"] = lambda: [second]
    assert api.queue(ctx)["pending_count"] == 2


def test_rejection_of_trade_review_does_not_hide_actual_pending_source(rig):
    ctx, row, _ = rig
    row["kind"], row["decision_mode"] = "FINANCIAL", "GOVERNED_PATH"
    review = start(ctx, row)
    ctx.ledger.decide(ctx.principal(), lambda: row, decision(row, review, decision="REJECT"))
    assert api.queue(ctx)["pending_count"] == 1


def test_rule_disagreement_becomes_proposal_without_changing_policy(rig):
    ctx, _, _ = rig
    policy = c.policy_projection("# 0 · Rules\n\nNever delete.", source_sha=SHA)
    body = {"position": "DISAGREE", "comment": "Please clarify the cleanup exception.",
            "document_sha": policy["document_sha"], "rule_id": policy["rules"][-1]["id"]}
    before = repr(policy)
    result = ctx.ledger.feedback(ctx.principal(), lambda: policy, body)
    assert result["effect"] == "PROPOSAL_ONLY" and repr(policy) == before
    assert ctx.ledger.proposal_rows()[0]["kind"] == "DESIGN"
    with pytest.raises(c.Refused, match="DOCUMENT_CHANGED"):
        ctx.ledger.feedback(ctx.principal(), lambda: policy, {**body, "document_sha": "old"})


def test_actual_rulebook_before_after_pair_fits_and_offsets_name_exact_changed_text():
    text = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text()
    updated = text + "\nAn additional fixture sentence for exact review.\n"
    doc = c.document(updated, base_text=text, source_sha=SHA, version="20.2.0")
    additions = [change for change in doc["changes"] if change["kind"] == "added"]
    assert additions
    for change in additions:
        offset = change["after_offset"]
        assert updated[offset:offset + len(change["after"])] == change["after"]


def test_audit_proposals_cannot_embed_a_decision_or_invent_evidence(rig):
    ctx, _, _ = rig
    policy = c.policy_projection("# 0 · Rules\n\nNever delete.", source_sha=SHA)
    finding = {"title": "Review cleanup evidence", "detail": "No receipt was supplied.", "rule_id": "rule", "evidence_refs": ["receipt:1"], "decision": "APPROVE", "auto_apply": True}
    event = ctx.ledger.audit_findings(policy=policy, audit_key="c" * 40, findings=[finding], evidence_refs={"receipt:1"})
    assert event["event"] == "AUDIT_FINDINGS" and event["effect"] == "PROPOSAL_ONLY"
    assert "decision" not in event["findings"][0] and event["findings"][0]["auto_apply"] is False
    assert ctx.ledger.proposal_rows()[0]["kind"] == "FINDING"
    with pytest.raises(c.Refused, match="UNSUPPORTED_AUDIT_FINDING"):
        ctx.ledger.audit_findings(policy=policy, audit_key="d" * 40, findings=[finding], evidence_refs=set())


def test_financial_adapter_accepts_real_database_clock_types_without_losing_queue(monkeypatch):
    import sys
    import types
    from decimal import Decimal
    module = types.ModuleType("scripts.lib.cio_truth")
    module.financial_queue_items = lambda **kwargs: {"complete": True, "items": [{"source_id": "7", "canonical_entity_id": "action_queue:7",
        "source": "action_queue", "source_refs": [{"source": "action_queue", "id": "7"}], "kind": "actions", "title": "Review fixture",
        "created_at": NOW, "action": {"amount": Decimal("12.34")}}]}
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_truth", module)
    result = api._default_sources(Path(__file__).resolve().parents[1])["financial_queues"]()
    assert result["gap"] is None and result["rows"][0]["created_at"] == NOW.isoformat()
    assert "action_queue:7" in result["rows"][0]["source_refs"]
    assert "12.34" in result["rows"][0]["document"]["text"]


def test_author_explanations_bind_exact_pr_head_and_reset_review_hash():
    import json
    doc = c.document("A proposed rule.", source_sha=SHA)
    ident = doc["changes"][0]["id"]
    notes = {"head_sha": SHA, "annotations": {ident: {"plain": "You review the proposal.", "reason": "A prior change lacked review."}}}
    pr = {"body": "```approval-reader-notes\n" + json.dumps(notes) + "\n```"}
    annotations = api.reader_annotations(pr, doc)
    updated = c.document("A proposed rule.", source_sha=SHA, annotations=annotations)
    assert updated["changes"][0]["plain"] == "You review the proposal."
    assert updated["document_sha"] != doc["document_sha"]
    notes["head_sha"] = "b" * 40
    assert api.reader_annotations({"body": "```approval-reader-notes\n" + json.dumps(notes) + "\n```"}, doc) == {}


def _policy_repository(root):
    import os
    import subprocess
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
           "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test",
           "GIT_AUTHOR_DATE": "2032-04-12T14:00:00Z", "GIT_COMMITTER_DATE": "2032-04-12T14:00:00Z"}
    def write(text, parent=None):
        def git(*args, data=None):
            return subprocess.run(["git", "-C", str(root), *args], input=data, text=True, capture_output=True, check=True, env=env).stdout.strip()
        blob = git("hash-object", "-w", "--stdin", data=text)
        tree = git("mktree", data=f"100644 blob {blob}\tAGENTS.md\n")
        args = ["commit-tree", tree, "-m", "fixture policy"] + (["-p", parent] if parent else [])
        commit = git(*args)
        git("update-ref", "refs/heads/main", commit)
        return commit
    return write


def test_packed_release_binds_its_own_commit_without_git_or_env_override(tmp_path, monkeypatch):
    repository = tmp_path / "canonical"
    write = _policy_repository(repository)
    old_text = "Policy-Version: 20.1.0\n\n# 0 · Rules\n\nNever bypass a denial.\n"
    original = write(old_text)
    newer = write(old_text.replace("20.1.0", "20.2.0"), original)
    release = repository / "packed-release"; release.mkdir()
    (release / "SOURCE_COMMIT").write_text(original)
    (release / "BUILD_SHA").write_text(original)
    (release / "AGENTS.md").write_text(old_text)
    monkeypatch.setattr(api, "CANONICAL_REPOSITORY", repository)
    monkeypatch.setenv("TRADEAI_SOURCE_SHA", "f" * 40)
    assert not (release / ".git").exists()
    assert api.source_revision(release) == original != newer
    assert api._git(release, "rev-parse", "HEAD").strip() == original
    assert api.policy_source(release) == (original, old_text)


def test_packed_release_stamp_or_policy_disagreement_is_reported_not_repaired(tmp_path, monkeypatch):
    repository = tmp_path / "canonical"
    write = _policy_repository(repository)
    text = "Policy-Version: 20.1.0\n\n# 0 · Rules\n\nNever bypass.\n"
    commit = write(text)
    release = tmp_path / "release"; release.mkdir()
    (release / "SOURCE_COMMIT").write_text(commit)
    (release / "BUILD_SHA").write_text("f" * 40)
    (release / "AGENTS.md").write_text(text)
    monkeypatch.setattr(api, "CANONICAL_REPOSITORY", repository)
    with pytest.raises(c.Refused, match="RELEASE_SOURCE_STAMPS_DISAGREE"):
        api.source_revision(release)
    assert (release / "BUILD_SHA").read_text() == "f" * 40
    (release / "BUILD_SHA").write_text(commit)
    (release / "AGENTS.md").write_text("Altered artifact wording")
    with pytest.raises(c.Refused, match="RELEASE_POLICY_CONTENT_MISMATCH"):
        api.policy_source(release)
    assert (release / "AGENTS.md").read_text() == "Altered artifact wording"


def test_w10_adapter_uses_durable_default_and_opaque_ids_with_real_watch_link(monkeypatch):
    import sys
    import types
    from urllib.parse import urlparse, parse_qs
    package = types.ModuleType("scripts.lib.conflicts"); package.__path__ = []
    module = types.ModuleType("scripts.lib.conflicts.api")
    key = "security:guid:U0:source:Schwab Rollover IRA / Research & ops"
    def read(**kwargs):
        assert kwargs == {"limit": 200}  # code artifacts must not replace W10's canonical state root
        return {"gap": None, "total": 1, "rows": [{"id": key, "title": "Review source disagreement", "proposed_by": "conflict engine",
            "created_at": NOW.isoformat(), "document": {"text": "Both source versions and their clear condition.", "version": "1", "source_sha": "d" * 64},
            "governed_href": "/v3/watch?conflict=" + key}]}
    module.approval_rows = read
    monkeypatch.setitem(sys.modules, "scripts.lib.conflicts", package)
    monkeypatch.setitem(sys.modules, "scripts.lib.conflicts.api", module)
    row = api._default_sources(Path(__file__).resolve().parents[1])["conflicts"]()[0]
    assert row["id"].startswith("conflict:") and " " not in row["id"]
    assert row["decision_mode"] == "GOVERNED_PATH"
    assert urlparse(row["governed_href"]).path == "/watch"
    assert parse_qs(urlparse(row["governed_href"]).query)["conflict"] == [key]
