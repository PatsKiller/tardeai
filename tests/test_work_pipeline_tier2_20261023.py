"""Work pipeline Tier 2 (operator 2026-10-23, "both"): passkey assertion + typed phrase per act, through the host
applier, as Ops -> Controls change kinds ``pipeline.*``. Hermetic: the Ops Controls harness (in-memory store, fake
WebAuthn verifier, fake host runner) from tests/test_ops_controls_20261022.py; gh and the deploy script are fakes.

Proves: every Tier 2 kind is refused without a passkey assertion and without the exact typed phrase; agent callers
are refused; approve_design and contract_reviewed write their ledgers only through the applier (with the operator's
words, actor and request id) and the registry reads the approval at once; merge, release and package approval are
OFF by default (FEATURE_OFF before any request exists); merge, when enabled, refuses unless every required check is
exactly ``success`` at the expected head, then merges with --match-head-commit; release, when enabled, refuses without
an active release-write grant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib import design_registry as DR
from scripts.lib import work_pipeline_tier2 as T2
from tests.test_ops_controls_20261022 import (  # noqa: F401 - env is a fixture
    OP,
    enroll_passkey,
    env,
    idem,
    post,
    risky,
    run_applier,
    step_up,
)

SHA = "a" * 40


def setup_pipeline(e, **flags):
    e.cfg["work_pipeline"] = {**(e.cfg.get("work_pipeline") or {}), "claims_dir": str(e.tmp / "claims"), **flags}
    d = e.hosts.code_root / "docs" / "designs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "DSN-20261023-demo.md").write_text(
        "---\nid: DSN-20261023-demo\ntitle: Demo\nstatus: PROPOSED\napproval: awaiting operator\n---\nbody\n"
    )
    (e.hosts.code_root / "config" / "n8n_health_contracts.json").write_text(
        json.dumps({"contracts": {"cio-ask-research": {"status": "DRAFT"}, "done-lane": {"status": "REVIEWED"}}})
    )
    enroll_passkey(e)


def create(e, kind, params):
    return post(e, "/requests", {"kind": kind, "params": params, "idempotency_key": idem()})


# --------------------------------------------------------------------------------------------- gates


def test_flags_default_merge_release_item_off():
    f = T2.flags({})
    assert f["pipeline.approve_design"] and f["pipeline.contract_reviewed"]
    assert not f["pipeline.merge_pr"] and not f["pipeline.release_now"] and not f["pipeline.approve_item"]
    repo = json.loads((Path(__file__).resolve().parents[1] / "config" / "ops_controls.json").read_text())
    assert repo["work_pipeline"]["merge_pr_enabled"] is False and repo["work_pipeline"]["release_now_enabled"] is False
    assert repo["work_pipeline"]["approve_item_enabled"] is False


def test_off_kinds_refused_before_any_request(env):
    setup_pipeline(env)
    for kind, params in (("pipeline.merge_pr", {"pr": 1997, "head_sha": SHA}), ("pipeline.release_now", {"sha": SHA}),
                         ("pipeline.approve_item", {"package_id": "pkg-20261023-x", "items": "all"})):  # fmt: skip
        st, body = create(env, kind, params)
        assert st == 409 and body["error"] == "FEATURE_OFF", body
    assert env.store.list_approved("applier", 10) == []


def test_tier2_needs_passkey_and_exact_phrase(env):
    setup_pipeline(env)
    st, body = create(env, "pipeline.approve_design", {"design_id": "DSN-20261023-demo", "words": "approve the demo"})
    assert st == 200 and body["request"]["status"] == "AWAITING_STEP_UP"
    rid = body["request"]["request_id"]
    assert env.store.get_request(rid)["phrase"] == "APPROVE DESIGN DSN-20261023-demo 2026-10-23"
    st, body = post(env, f"/requests/{rid}/approve", {})
    assert st in (401, 403, 409) and body["ok"] is False  # no assertion: refused
    st, body = step_up(env, rid, phrase="APPROVE DESIGN DSN-20261023-other 2026-10-23")
    assert st in (400, 403) and body["ok"] is False  # wrong phrase
    st, body = step_up(env, rid, sig="bad")
    assert st in (400, 401, 403) and body["ok"] is False  # bad assertion
    run_applier(env)
    assert not (env.tmp / "claims" / T2.DESIGN_LEDGER_REL).exists()


def test_agent_callers_refused(env):
    setup_pipeline(env)
    env.who["principal"] = "service-token"
    st, body = create(env, "pipeline.approve_design", {"design_id": "DSN-20261023-demo", "words": "approve"})
    assert st == 403 and body["error"] == "AGENT_CALLER_REFUSED"


# --------------------------------------------------------------------------------------------- effects


def test_approve_design_writes_ledger_through_the_applier_and_registry_reads_it(env):
    setup_pipeline(env)
    rid = risky(env, "pipeline.approve_design", {"design_id": "DSN-20261023-demo", "words": "Approved, go ahead"})
    ledger = env.tmp / "claims" / T2.DESIGN_LEDGER_REL
    assert not ledger.exists()  # Command Center never writes it: only the applier does
    out = run_applier(env)
    assert out and out[0]["outcome"] == "APPLIED", out
    row = json.loads(ledger.read_text().splitlines()[-1])
    assert row["schema"] == T2.DESIGN_SCHEMA and row["id"] == "DSN-20261023-demo" and row["status"] == "APPROVED"
    assert row["words"] == "Approved, go ahead" and row["actor"] == OP and row["request_id"] == rid
    assert row["file"] == "docs/designs/DSN-20261023-demo.md"
    # the registry overlays the approval at once; the file catches up in the next commit
    designs = [
        {
            "id": "DSN-20261023-demo",
            "title": "Demo",
            "status": "PROPOSED",
            "approval": "awaiting operator",
            "phases": [],
        }
    ]
    out = DR.apply_ledger_approvals(designs, env.tmp / "claims")
    assert (
        out[0]["status"] == "APPROVED" and out[0]["file_pending"] is True and "Approved, go ahead" in out[0]["approval"]
    )
    assert DR.designs_awaiting(env.hosts.code_root, out) == []
    st, body = create(env, "pipeline.approve_design", {"design_id": "DSN-20261023-demo", "words": "again"})
    assert st == 409 and body["error"] == "NO_CHANGE"


def test_approve_design_unknown_id_refused(env):
    setup_pipeline(env)
    st, body = create(env, "pipeline.approve_design", {"design_id": "DSN-20261023-nope", "words": "approve it"})
    assert st == 404 and body["error"] == "NOT_FOUND"


def test_contract_reviewed_only_for_draft_lanes(env):
    setup_pipeline(env)
    st, body = create(env, "pipeline.contract_reviewed", {"lane_id": "done-lane", "words": "looks right"})
    assert st == 409 and body["error"] == "NOT_DRAFT"
    risky(env, "pipeline.contract_reviewed", {"lane_id": "cio-ask-research", "words": "reviewed: healthy = answer"})
    assert run_applier(env)[0]["outcome"] == "APPLIED"
    row = json.loads((env.tmp / "claims" / T2.CONTRACT_LEDGER_REL).read_text().splitlines()[-1])
    assert row["lane_id"] == "cio-ask-research" and row["status"] == "REVIEWED" and row["actor"] == OP
    assert "cio-ask-research" in T2.contract_reviews(env.tmp / "claims")


class FakeGh:
    def __init__(self, conclusions, head=SHA):
        self.conclusions = conclusions
        self.head = head
        self.merged = False
        self.calls = []

    def __call__(self, argv, stdin=None):
        self.calls.append(list(argv))
        if argv[:4] == ["gh", "api", "--method", "GET"]:
            path = argv[4]
            if path.endswith("/protection/required_status_checks"):
                return 0, json.dumps({"contexts": sorted(self.conclusions)}), ""
            if "/check-runs" in path:
                runs = [
                    {"name": n, "conclusion": c, "started_at": "2026-10-23T15:00:00Z"}
                    for n, c in self.conclusions.items()
                ]
                return 0, json.dumps({"check_runs": runs}), ""
            if "/pulls/" in path:
                return 0, json.dumps({"state": "closed" if self.merged else "open", "merged": self.merged,
                                      "head": {"sha": self.head}, "base": {"ref": "main"}, "merge_commit_sha": "m" * 40}), ""  # fmt: skip
        if argv[:3] == ["gh", "pr", "merge"]:
            assert "--match-head-commit" in argv and argv[argv.index("--match-head-commit") + 1] == SHA
            self.merged = True
            return 0, "merged", ""
        raise AssertionError(argv)


def test_merge_pr_requires_exact_success_then_merges_with_head_match(env):
    setup_pipeline(env, merge_pr_enabled=True)
    gh = FakeGh({"ci-gate": "success", "cio-hardening": "neutral"})
    env.hosts.runner = gh
    risky(env, "pipeline.merge_pr", {"pr": 1997, "head_sha": SHA})
    out = run_applier(env)
    assert out[0]["outcome"] == "REFUSED" and out[0]["code"] == "CHECKS_NOT_SUCCESS"
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in gh.calls)
    gh.conclusions["cio-hardening"] = "success"
    risky(env, "pipeline.merge_pr", {"pr": 1997, "head_sha": SHA})
    out = run_applier(env)
    assert out[0]["outcome"] == "APPLIED" and gh.merged


def test_merge_pr_refuses_moved_head(env):
    setup_pipeline(env, merge_pr_enabled=True)
    env.hosts.runner = FakeGh({"ci-gate": "success"}, head="b" * 40)
    risky(env, "pipeline.merge_pr", {"pr": 1997, "head_sha": SHA})
    assert run_applier(env)[0]["code"] == "STATE_CHANGED"


def test_release_now_needs_release_write_grant(env):
    setup_pipeline(env, release_now_enabled=True)
    calls = []

    def runner(argv, stdin=None):
        calls.append(list(argv))
        if argv[0] == env.host.guard_bin and argv[1] == "id":
            g = env.host.grants.get(argv[2])
            return (0, g + "\n", "") if g else (1, "", "none")
        if argv[0] == "bash" and argv[1].endswith("cio_phase2_exact_main_deploy.sh"):
            return 0, f"{argv[2]} ok", ""
        raise AssertionError(argv)

    env.hosts.runner = runner
    risky(env, "pipeline.release_now", {"sha": SHA})
    out = run_applier(env)
    assert out[0]["outcome"] == "REFUSED" and out[0]["code"] == "NO_RELEASE_GRANT"
    assert not any(c[0] == "bash" for c in calls)
    env.host.grants["release-write"] = "r" * 8 + "1234567890abcdef"
    risky(env, "pipeline.release_now", {"sha": SHA})
    out = run_applier(env)
    assert out[0]["outcome"] == "APPLIED"
    assert [c[2] for c in calls if c[0] == "bash"] == ["prepare", "promote"]


def test_phrases():
    t = "2026-10-23"
    assert T2.phrase("pipeline.merge_pr", {"pr": 1997}, t) == "MERGE PR #1997 2026-10-23"
    assert T2.phrase("pipeline.release_now", {"sha": SHA}, t) == "RELEASE aaaaaaaaa 2026-10-23"
    assert T2.phrase("pipeline.contract_reviewed", {"lane_id": "x-lane"}, t) == "CONTRACT REVIEWED x-lane 2026-10-23"


def test_kinds_are_risky_applier_kinds():
    from scripts.lib import ops_controls_core as C

    for k in T2.FLAGS:
        spec = C.kind_spec(k)
        assert spec.direction == C.RISKY and spec.executor == C.EXEC_APPLIER and spec.supported
