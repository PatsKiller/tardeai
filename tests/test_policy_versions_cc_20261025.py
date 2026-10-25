"""/v3/policy AGENTS.md versions: current status, pending PROPOSED PRs + exact token, operator-only approve, relay."""
import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from scripts import relay_policy_approvals as relay
from scripts.lib import operator_approvals as c
from scripts.lib import operator_approvals_api as api
from scripts.lib import policy_ratification as ratify

NOW = datetime(2032, 4, 12, 14, 0, tzinfo=timezone.utc)
MAIN_SHA, HEAD, OTHER = "a" * 40, "b" * 40, "c" * 40
OPERATOR = "tailnet:operator@example.test"


def agents(version, status, row_status, approval, extra=""):
    return (f"# AGENTS.md\n\n```\nPolicy-Version:      {version}\nStatus:              {status}\n"
            f"Effective-Date:      {'2032-04-01' if status == 'ACTIVE' else 'PENDING'}\nSupersedes:          20.2.0\n```\n\n"
            f"# 28 · Operations\n\nRead every change.{extra}\n\n"
            "## Version history\n\n| Version | Date | Status | Class | Summary | Approval |\n|---|---|---|---|---|---|\n"
            f"| {version} | 2032-04-01 | {row_status} | MINOR | change | {approval} |\n"
            "| 20.2.0 | 2032-03-01 | ACTIVE | MINOR | earlier | ratified |\n")


MAIN = agents("20.3.0", "ACTIVE", "ACTIVE", "ratified `APPROVE_AGENTS_POLICY_20_3_0 7 " + "d" * 40 + "`")
PROPOSED = agents("20.4.0", "PROPOSED", "PROPOSED", "**PENDING** — awaiting `APPROVE_AGENTS_POLICY_20_4_0 <pr> <sha>`",
                  "\n\nHands-off delivery.")
TOKEN = f"APPROVE_AGENTS_POLICY_20_4_0 2120 {HEAD}"


def policy_item(text=PROPOSED, head=HEAD, pr=2120):
    version = c.document(text, source_sha=head)["text"].split("Policy-Version:")[1].split()[0]
    doc = c.document(text, base_text=MAIN, source_sha=head, version=version, source_verified=True)
    return c.item(ident=f"policy:{pr}", kind="POLICY", title="AGENTS.md 20.4.0 hands-off delivery",
                  proposed_by="PatsKiller", created_at=NOW.isoformat(), doc=doc, source="github_pr_snapshot", pr=pr)


@pytest.fixture
def rig(tmp_path):
    clock = [NOW]
    state = {"rows": [policy_item()], "gap": None}
    ledger = c.DecisionLedger(tmp_path / "ledger.jsonl", approved=lambda: True, clock=lambda: clock[0])
    ctx = api.Ctx(principal=lambda: OPERATOR, listener=lambda: "serve_proxy", csrf=lambda m, p: (True, ""),
                  allowed_logins=frozenset({"operator@example.test"}),
                  sources={"policy_prs": lambda: {"rows": state["rows"], "gap": state["gap"]}}, ledger=ledger,
                  policy=lambda: {}, clock=lambda: clock[0], can_read=lambda: True,
                  policy_text=lambda: (MAIN_SHA, MAIN))
    return ctx, state, clock


def read_everything(ctx, clock, item):
    review = ctx.ledger.start(OPERATOR, lambda: item, item["document"]["document_sha"])
    for change in item["document"]["changes"]:
        body = {"review_id": review["review_id"], "document_sha": item["document"]["document_sha"],
                "change_id": change["id"], "phase": "enter"}
        ctx.ledger.marker(OPERATOR, lambda: item, body)
        clock[0] += timedelta(seconds=3)
        ctx.ledger.marker(OPERATOR, lambda: item, {**body, "phase": "read"})
    return review


def approve_body(**extra):
    return {"pr": 2120, "head_sha": HEAD, "version": "20.4.0", "token": TOKEN, "request_id": "req_approve_1", **extra}


def post(ctx, body):
    return api.handle(api.PREFIX + "/policy/versions/approve", "POST", body, ctx=ctx)


# ---------------------------------------------------------------------------- GET /policy/versions


def test_versions_show_current_and_pending_token(rig):
    ctx, _, _ = rig
    status, data = api.handle(api.PREFIX + "/policy/versions", "GET", ctx=ctx)
    assert status == 200
    d = data["data"]
    assert d["current"]["version"] == "20.3.0" and d["current"]["status"] == "ACTIVE" and d["current"]["consistent"]
    assert d["current"]["source_sha"] == MAIN_SHA
    [p] = d["pending"]
    assert (p["pr"], p["version"], p["head_sha"], p["token"]) == (2120, "20.4.0", HEAD, TOKEN)
    assert p["status"] == "PROPOSED" and p["awaits_token"] and p["can_approve"] and p["decision"] is None
    assert p["review"] == {"started": False, "read": 0, "total": p["changes"], "expired": False}
    assert d["pending_count"] == 1 and d["complete"] and d["github_write_path"] is None
    assert not ctx.ledger.path.exists()  # a GET never writes


def test_versions_source_gap_is_unknown_count_not_zero(rig):
    ctx, state, _ = rig
    state["rows"], state["gap"] = [], "Exact open PR snapshot incomplete"
    d = api.handle(api.PREFIX + "/policy/versions", "GET", ctx=ctx)[1]["data"]
    assert d["pending_count"] is None and not d["complete"] and d["gaps"][0]["source"] == "policy_prs"

    def boom():
        raise c.Refused("POLICY_PR_SNAPSHOT_UNAVAILABLE", 503)
    ctx.sources["policy_prs"] = boom
    d = api.handle(api.PREFIX + "/policy/versions", "GET", ctx=ctx)[1]["data"]
    assert d["pending_count"] is None and d["gaps"] == [{"source": "policy_prs", "reason": "POLICY_PR_SNAPSHOT_UNAVAILABLE"}]


def test_active_heads_are_not_listed_as_pending(rig):
    ctx, state, _ = rig
    state["rows"] = [policy_item(text=agents("20.4.0", "ACTIVE", "ACTIVE", "ratified"))]
    assert api.handle(api.PREFIX + "/policy/versions", "GET", ctx=ctx)[1]["data"]["pending"] == []


def test_unauthenticated_reader_refused(rig):
    ctx, _, _ = rig
    ctx.principal, ctx.can_read = (lambda: ""), (lambda: False)
    assert api.handle(api.PREFIX + "/policy/versions", "GET", ctx=ctx) == (403, {"ok": False, "error": "AUTHENTICATED_READER_REQUIRED"})


# ---------------------------------------------------------------------------- POST approve


def test_operator_approve_records_same_row_as_reader(rig):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    status, data = post(ctx, approve_body())
    assert status == 200, data
    row = data["data"]["decision"]
    assert row["event"] == "DECIDED" and row["decision"] == "APPROVE" and row["kind"] == "POLICY"
    assert row["policy_token"] == TOKEN and row["actor"] == OPERATOR and row["effect"] == "RECORD_ONLY"
    assert row["source_sha"] == HEAD and row["item_id"] == "policy:2120"
    assert data["data"]["effect"] == "RECORDED_AWAITING_RELAY" and "PR #2120" in data["data"]["relay"]
    # The projection now shows it decided, awaiting relay, and no longer approvable.
    [p] = api.handle(api.PREFIX + "/policy/versions", "GET", ctx=ctx)[1]["data"]["pending"]
    assert p["decision"]["policy_token"] == TOKEN and p["decision"]["effect"] == "RECORDED_AWAITING_RELAY"
    assert not p["can_approve"]
    # The in-app row counts as ratification evidence exactly like the PR comment.
    ev = ratify.ratification_evidence(token=TOKEN, comments=[], ledger_rows=ctx.ledger.rows())
    assert ev["path"] == "in_app_decision" and ev["actor"] == OPERATOR


def test_idempotent_retry_returns_same_row(rig):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    first = post(ctx, approve_body())[1]["data"]["decision"]
    again = post(ctx, approve_body())
    assert again[0] == 200 and again[1]["data"]["decision"]["hash_self"] == first["hash_self"]
    assert sum(r["event"] == "DECIDED" for r in ctx.ledger.rows()) == 1
    assert post(ctx, approve_body(request_id="req_approve_2"))[1]["error"] == "ALREADY_DECIDED"


@pytest.mark.parametrize("actor,listener", [("service-token", "serve_proxy"), ("codex", "serve_proxy"), ("agent-reader:claude", "serve_proxy"),
                                            (OPERATOR, "loopback"), ("tailnet:stranger@example.test", "serve_proxy")])
def test_agents_refused(rig, actor, listener):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    ctx.principal, ctx.listener = (lambda: actor), (lambda: listener)
    ctx.can_read = lambda: True  # a read-only agent reader may read, never approve
    assert post(ctx, approve_body()) == (403, {"ok": False, "error": "AGENT_CALLER_REFUSED"})
    assert not any(r["event"] == "DECIDED" for r in ctx.ledger.rows())


def test_csrf_missing_refused(rig):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    ctx.csrf = lambda m, p: (False, "missing token")
    assert post(ctx, approve_body()) == (403, {"ok": False, "error": "CSRF_REFUSED"})
    assert not any(r["event"] == "DECIDED" for r in ctx.ledger.rows())


def test_head_moved_refused(rig):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    state["rows"] = [policy_item(head=OTHER)]  # a new push to the PR after the operator loaded the page
    assert post(ctx, approve_body())[1]["error"] == "DOCUMENT_CHANGED"
    assert not any(r["event"] == "DECIDED" for r in ctx.ledger.rows())


@pytest.mark.parametrize("field,value,code", [("token", f"APPROVE_AGENTS_POLICY_20_4_0 2121 {HEAD}", "TOKEN_MISMATCH"),
                                              ("version", "20.5.0", "DOCUMENT_CHANGED"), ("pr", "2120", "PR_REQUIRED"),
                                              ("request_id", "x", "REQUEST_ID_REQUIRED")])
def test_binding_fields_refused(rig, field, value, code):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    assert post(ctx, approve_body(**{field: value}))[1]["error"] == code


def test_unread_changes_refused(rig):
    ctx, state, _ = rig
    assert post(ctx, approve_body())[1]["error"] == "CHANGES_UNREAD"
    ctx.ledger.start(OPERATOR, lambda: state["rows"][0], state["rows"][0]["document"]["document_sha"])
    assert post(ctx, approve_body())[1]["error"] == "CHANGES_UNREAD"
    assert not any(r["event"] == "DECIDED" for r in ctx.ledger.rows())


def test_expired_reading_session_refused(rig):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    clock[0] += timedelta(minutes=31)
    assert post(ctx, approve_body())[1]["error"] == "REVIEW_EXPIRED"


# ---------------------------------------------------------------------------- ratification evidence + relay


def test_pr_comment_and_in_app_paths_are_equal():
    comment = {"id": 9, "user": {"login": "PatsKiller"}, "body": TOKEN + "\n", "created_at": "t"}
    assert ratify.ratification_evidence(token=TOKEN, comments=[comment])["path"] == "pr_comment"
    assert ratify.ratification_evidence(token=TOKEN, comments=[{**comment, "user": {"login": "x"}}]) is None
    agent_row = {"event": "DECIDED", "decision": "APPROVE", "kind": "POLICY", "policy_token": TOKEN, "actor": "codex"}
    assert ratify.ratification_evidence(token=TOKEN, ledger_rows=[agent_row]) is None
    assert ratify.ratification_evidence(token=TOKEN, ledger_rows=[{**agent_row, "actor": OPERATOR}])["path"] == "in_app_decision"
    assert ratify.token_for("20.4.0", 2120, HEAD) == TOKEN and ratify.parse_token(TOKEN)["pr"] == 2120
    assert ratify.token_for("20.4", 2120, HEAD) is None and ratify.token_for("20.4.0", 0, HEAD) is None


class FakeGh:
    def __init__(self, head=HEAD, comments=(), fail_comment=False):
        self.head, self.comments, self.fail_comment, self.calls = head, list(comments), fail_comment, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[1:3] == ["pr", "comment"]:
            return subprocess.CompletedProcess(cmd, 1 if self.fail_comment else 0, "https://x/c/1\n", "boom")
        if cmd[-1].endswith("/pulls/2120"):
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"head": {"sha": self.head}}), "")
        if "/comments" in cmd[4]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps([self.comments]), "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected")


def approved_ledger(rig):
    ctx, state, clock = rig
    read_everything(ctx, clock, state["rows"][0])
    post(ctx, approve_body())
    return ctx.ledger.path


def test_relay_dry_run_posts_nothing(rig, capsys):
    path, gh = approved_ledger(rig), FakeGh()
    assert relay.main(["--ledger", str(path)], run=gh) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "WOULD_POST" and out["token"] == TOKEN
    assert not any(cmd[1:3] == ["pr", "comment"] for cmd in gh.calls)


def test_relay_apply_posts_token_verbatim_once(rig, capsys):
    path, gh = approved_ledger(rig), FakeGh()
    assert relay.main(["--ledger", str(path), "--apply"], run=gh) == 0
    posted = [cmd for cmd in gh.calls if cmd[1:3] == ["pr", "comment"]]
    assert posted == [["gh", "pr", "comment", "2120", "--repo", relay.REPO, "--body", TOKEN]]
    assert json.loads(capsys.readouterr().out)["action"] == "POSTED"
    gh2 = FakeGh(comments=[{"body": TOKEN, "user": {"login": "PatsKiller"}}])
    relay.main(["--ledger", str(path), "--apply"], run=gh2)
    assert json.loads(capsys.readouterr().out)["action"] == "ALREADY_RELAYED"
    assert not any(cmd[1:3] == ["pr", "comment"] for cmd in gh2.calls)


def test_relay_refuses_moved_head_and_reports_failure(rig, capsys):
    path = approved_ledger(rig)
    gh = FakeGh(head=OTHER)
    assert relay.main(["--ledger", str(path), "--apply"], run=gh) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "SKIP_HEAD_MOVED"
    assert not any(cmd[1:3] == ["pr", "comment"] for cmd in gh.calls)
    assert relay.main(["--ledger", str(path), "--apply"], run=FakeGh(fail_comment=True)) == 1


def test_relay_corrupt_ledger_fails_closed(tmp_path, capsys):
    bad = tmp_path / "l.jsonl"
    bad.write_text('{"event": "DECIDED"}\n')
    assert relay.main(["--ledger", str(bad)], run=FakeGh()) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "LEDGER_CORRUPT"
