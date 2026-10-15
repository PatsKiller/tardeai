"""Release-grant binding: a grant authorizes only the release it names.

Replays the 2026-09-25 #1229/#1230 incident shapes: two PR-specific requests
pending, a 30-use campaign grant active, promotes proceeded on tier match.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.release_grant_binding import ReleaseAction, decide, load_grants, load_requests  # noqa: E402

NOW = 1790338800.0                    # 2026-09-25 08:20:00 EDT
CAMPAIGN_GRANT = {"grant_id": "0de5acf99bb9434381244a7dcb2a5a07", "tier": "release-write", "created_at": 1790338547,
                  "expires": 1790381747, "uses": 30,
                  "reason": "trade-ai-maturity-overnight-20260912: prepare, promote, verify, and if necessary roll back "
                            "only exact merged SHAs from this campaign after semantic and identity gates pass"}
PENDING_1229 = {"request_id": "0f7ca85f285bfd49", "tier": "release-write", "status": "PENDING",
                "reason": "Go-live PR #1229 (options paper closes recorded for every registry strategy): prepare + promote "
                          "exact main 8a9222cc6 from ~/tradeai-exact-main-20260827, verify four pins + health, restart desk bot"}
ACT_1229 = ReleaseAction(action="promote", target_sha="8a9222cc6f1e0f0a0b0c0d0e0f1011121314", pr_number=1229, now=NOW)


def test_cross_campaign_reuse_is_refused():
    v = decide(ACT_1229, grants=[CAMPAIGN_GRANT], requests=[PENDING_1229])
    assert v.allowed is False
    assert "PENDING" in v.reason and "0f7ca85f285bfd49" in v.reason
    assert v.refused_grants and v.refused_grants[0]["grant_id"] == CAMPAIGN_GRANT["grant_id"]


def test_campaign_grant_without_pending_request_still_refused_when_it_names_nothing_of_this_release():
    v = decide(ACT_1229, grants=[CAMPAIGN_GRANT], requests=[])
    assert v.allowed is False
    assert "names neither" in v.refused_grants[0]["why"]


def test_campaign_grant_allowed_when_action_runs_under_that_campaign_and_nothing_specific_pends():
    act = ReleaseAction(action="promote", target_sha=ACT_1229.target_sha, pr_number=1229,
                        campaign="trade-ai-maturity-overnight-20260912", now=NOW)
    v = decide(act, grants=[CAMPAIGN_GRANT], requests=[])
    assert v.allowed is True and v.matched_by == ["campaign:trade-ai-maturity-overnight-20260912"]
    # ...but not while a specific request for THIS release is pending
    v2 = decide(act, grants=[CAMPAIGN_GRANT], requests=[PENDING_1229])
    assert v2.allowed is False and "campaign-only" in v2.refused_grants[0]["why"]


def test_explicit_authorized_go_live_by_pr_or_sha_is_allowed():
    by_pr = {**CAMPAIGN_GRANT, "grant_id": "g-pr", "reason": "Go-live PR #1229: prepare + promote exact main"}
    v = decide(ACT_1229, grants=[by_pr], requests=[PENDING_1229])
    assert v.allowed is True and v.matched_by == ["pr:#1229"] and v.grant_id == "g-pr"
    by_sha = {**CAMPAIGN_GRANT, "grant_id": "g-sha", "reason": "promote 8a9222cc6 only"}
    v = decide(ACT_1229, grants=[by_sha], requests=[])
    assert v.allowed is True and v.matched_by[0].startswith("sha:8a9222cc6")


def test_grant_that_settled_the_pending_request_is_allowed():
    settled = {**CAMPAIGN_GRANT, "grant_id": "g-tg", "reason": "generic", "remote_request_id": "0f7ca85f285bfd49"}
    v = decide(ACT_1229, grants=[settled], requests=[PENDING_1229])
    assert v.allowed is True and v.matched_by == ["settled_pending_request"]


def test_expired_and_exhausted_grants_are_refused():
    expired = {**CAMPAIGN_GRANT, "grant_id": "g-exp", "reason": "Go-live PR #1229", "expires": NOW - 1}
    v = decide(ACT_1229, grants=[expired], requests=[])
    assert v.allowed is False and v.refused_grants[0]["why"] == "expired"
    spent = {**CAMPAIGN_GRANT, "grant_id": "g-0", "reason": "Go-live PR #1229", "uses": 0}
    v = decide(ACT_1229, grants=[spent], requests=[])
    assert v.allowed is False and v.refused_grants[0]["why"] == "no_uses_left"


def test_repeated_use_consumes_and_then_refuses():
    g = {**CAMPAIGN_GRANT, "grant_id": "g-1", "reason": "Go-live PR #1229", "uses": 1}
    assert decide(ACT_1229, grants=[g], requests=[]).allowed is True
    g["uses"] -= 1                         # the guard's consume step
    assert decide(ACT_1229, grants=[g], requests=[]).allowed is False


def test_action_restriction_and_bad_inputs():
    g = {**CAMPAIGN_GRANT, "grant_id": "g-prep", "reason": "PR #1229: prepare only"}
    assert decide(ACT_1229, grants=[g], requests=[]).allowed is False
    assert decide(ReleaseAction(action="prepare", target_sha=ACT_1229.target_sha, pr_number=1229, now=NOW),
                  grants=[g], requests=[]).allowed is True
    assert decide(ReleaseAction(action="promote", target_sha="abc", now=NOW), grants=[g]).allowed is False
    assert decide(ReleaseAction(action="deploy", target_sha=ACT_1229.target_sha, now=NOW), grants=[g]).allowed is False


def test_loaders_accept_guard_file_shapes(tmp_path):
    (tmp_path / "grants.json").write_text(json.dumps({"release-write": CAMPAIGN_GRANT, "git-push": {"uses": 2, "expires": NOW + 10}}))
    rows = load_grants(tmp_path / "grants.json")
    assert {r["tier"] for r in rows} == {"release-write", "git-push"}
    (tmp_path / "req.json").write_text(json.dumps({"requests": {"0f7ca85f285bfd49": {k: v for k, v in PENDING_1229.items() if k != "request_id"}}}))
    reqs = load_requests(tmp_path / "req.json")
    assert reqs[0]["request_id"] == "0f7ca85f285bfd49"


def test_preflight_cli_fail_closed_and_warn_mode(tmp_path, monkeypatch):
    import subprocess
    (tmp_path / "grants.json").write_text(json.dumps({"release-write": CAMPAIGN_GRANT}))
    (tmp_path / "req.json").write_text(json.dumps([PENDING_1229]))
    env = {"TRADEAI_GUARD_GRANTS_PATH": str(tmp_path / "grants.json"), "TRADEAI_GUARD_REQUESTS_PATH": str(tmp_path / "req.json"),
           "PATH": "/usr/bin:/bin"}
    cmd = [sys.executable, str(ROOT / "scripts" / "release_grant_preflight.py"), "--action", "promote", "--sha", ACT_1229.target_sha, "--pr", "1229"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "REFUSED" in r.stderr
    r2 = subprocess.run(cmd, capture_output=True, text=True, env={**env, "TRADEAI_RELEASE_GRANT_BINDING": "warn"})
    assert r2.returncode == 0 and "warn mode" in r2.stderr
    out = json.loads(r2.stdout.strip().splitlines()[0])
    assert out["allowed"] is False and out["pending_request_ids"] == ["0f7ca85f285bfd49"]


# ---------------------------------------------------------------------------
# 2026-10-09 (due diligence B §2 / R2, R5): SHA wins over PR; CI before consume
# ---------------------------------------------------------------------------
TRAIN_SHA = "8c2eec70dea0b87915ed6b353e60359c620f8c77"
TRAIN_GRANT = {"grant_id": "g-train", "tier": "release-write", "expires": NOW + 3600, "uses": 9,
               "reason": f"PR #1567 sha {TRAIN_SHA}: prepare + promote (and rollback) exact-main release — "
                         "AGENTS 3.0.0 ratified (#1552), governance P16-P20 (#1554), bridge P4-P6/P21 (#1555), "
                         "health_unknown (#1562), de-flake (#1559), sharded CI (#1556), rollup fix (#1566) "
                         "[remote_request_id=c73b122335aa11ff chat=8797974247 via=button]"}
LIVE_CAMPAIGN_GRANT = {"grant_id": "g-campaign", "tier": "release-write", "expires": NOW + 3600, "uses": 1992,
                       "reason": "campaign n8n-maturity-20261009 (N8N Maturity program, 72h keyboard approval 10-09). "
                                 "Agent A runs prepare/promote, program installs/restarts/cutovers; every action "
                                 "logged on ~/N8N_PROGRAM_BOARD.md with PR # and sha."}


def _act(sha, pr=None, campaign=None, action="promote"):
    return ReleaseAction(action=action, target_sha=sha, pr_number=pr, campaign=campaign, now=NOW)


def test_audit_replay_pr_listed_in_train_grant_no_longer_authorizes_another_sha():
    # The 10-09 audit: pr=1554 with a made-up SHA was allowed because the grant lists (#1554).
    for pr, sha in ((1554, "0123456789abcdef0123456789abcdef01234567"), (1567, "f" * 40)):
        v = decide(_act(sha, pr), grants=[TRAIN_GRANT])
        assert v.allowed is False, (pr, sha)
        why = v.refused_grants[0]["why"]
        assert "a PR match alone does not bind" in why and TRAIN_SHA[:12] in why


def test_train_grant_still_binds_its_own_sha_with_or_without_pr():
    for pr in (1567, 1554, None):
        v = decide(_act(TRAIN_SHA, pr), grants=[TRAIN_GRANT])
        assert v.allowed is True and any(m.startswith("sha:8c2eec70d") for m in v.matched_by)
    # a 9-char prefix of the target is enough, as before
    assert decide(_act(TRAIN_SHA[:9], 1567), grants=[TRAIN_GRANT]).allowed is True


def test_request_and_chat_ids_are_not_mistaken_for_a_named_sha():
    from scripts.lib.release_grant_binding import named_shas

    pr_only = {**TRAIN_GRANT, "grant_id": "g-pr-only",
               "reason": "PR #1553 (+ merged #1549 #1550): deploy the merge of #1553 on main "
                         "[remote_request_id=0e7f8366ad8150ff chat=8797974247 via=button]"}
    assert named_shas(pr_only["reason"]) == []
    # A grant that names no SHA keeps the PR binding (unchanged behaviour).
    v = decide(_act("a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0", 1553), grants=[pr_only])
    assert v.allowed is True and v.matched_by == ["pr:#1553"]
    assert named_shas("prepared /x/377e9b536-main-exact-phase2-20261009-122248 sha 377e9b536afc") == [
        "377e9b536", "377e9b536afc"]
    assert named_shas("amount 123456789012 and id_deadbeef12 and deadbeef1234567890abcdef0123456789abcdef12") == []


def test_live_campaign_grant_keeps_working_for_any_sha_under_its_campaign():
    for sha in (TRAIN_SHA, "f" * 40):
        v = decide(_act(sha, 1625, campaign="n8n-maturity-20261009"), grants=[LIVE_CAMPAIGN_GRANT])
        assert v.allowed is True and v.matched_by == ["campaign:n8n-maturity-20261009"]
    # ...and binds nothing without the campaign
    assert decide(_act(TRAIN_SHA, 1625), grants=[LIVE_CAMPAIGN_GRANT]).allowed is False
    # A campaign grant whose text mentions some sha still binds via the campaign.
    noted = {**LIVE_CAMPAIGN_GRANT, "reason": LIVE_CAMPAIGN_GRANT["reason"] + " first release b7dbe6e60"}
    assert decide(_act(TRAIN_SHA, campaign="n8n-maturity-20261009"), grants=[noted]).allowed is True


def test_settled_request_cannot_widen_a_grant_to_another_sha():
    pending = {"request_id": "c73b122335aa11ff", "tier": "release-write", "status": "PENDING",
               "reason": "PR #1567: prepare + promote exact main"}
    settled = {**TRAIN_GRANT, "remote_request_id": "c73b122335aa11ff"}
    assert decide(_act("f" * 40, 1567), grants=[settled], requests=[pending]).allowed is False
    assert decide(_act(TRAIN_SHA, 1567), grants=[settled], requests=[pending]).allowed is True


def _preflight(monkeypatch, argv, *, allowed=True, ci_ok=True):
    import release_grant_preflight as pf
    from scripts.lib.release_grant_binding import Verdict

    calls = {"consume": 0, "collect": 0}

    def consume(**_):
        calls["consume"] += 1
        return {"ok": True}

    def collect(sha):
        calls["collect"] += 1
        return {"ok": ci_ok, "candidate_sha": sha, "checked_at": "2026-10-09T20:00:00Z",
                "errors": [] if ci_ok else ["not_successful:.github/workflows/agent-governance.yml"]}

    monkeypatch.setattr(pf, "decide_from_disk", lambda act: Verdict(allowed, "test", grant_id="g", matched_by=["sha:x"]))
    monkeypatch.setattr(pf, "consume_release_grant", consume)
    monkeypatch.setattr(pf, "collect_ci_evidence", collect)
    monkeypatch.setattr(sys, "argv", ["release_grant_preflight.py", *argv])
    return pf.main(), calls


def test_promote_with_ci_not_green_refuses_before_consuming(monkeypatch, tmp_path, capsys):
    rc, calls = _preflight(monkeypatch, ["--action", "promote", "--sha", TRAIN_SHA,
                                         "--ci-receipt", str(tmp_path / "ci.json")], ci_ok=False)
    assert rc == 3 and calls == {"consume": 0, "collect": 1}
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["consumed"] == {"ok": False, "skipped": "ci_not_green"} and out["ci_gate"]["ok"] is False
    assert json.loads((tmp_path / "ci.json").read_text())["ok"] is False   # receipt written for the deploy record


def test_promote_with_ci_green_consumes_exactly_once(monkeypatch, tmp_path):
    rc, calls = _preflight(monkeypatch, ["--action", "promote", "--sha", TRAIN_SHA,
                                         "--ci-receipt", str(tmp_path / "ci.json")])
    assert rc == 0 and calls == {"consume": 1, "collect": 1}


def test_fresh_green_receipt_is_reused_and_stale_or_foreign_is_not(tmp_path):
    import release_grant_preflight as pf
    from datetime import datetime, timezone

    receipt = tmp_path / "ci.json"
    checked = "2026-10-09T20:00:00Z"
    t0 = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc).timestamp()
    receipt.write_text(json.dumps({"ok": True, "candidate_sha": TRAIN_SHA, "checked_at": checked}))
    collected = []
    col = lambda s: collected.append(s) or {"ok": False, "errors": ["x"]}  # noqa: E731
    assert pf.promote_ci_gate(TRAIN_SHA, receipt, collect=col, now=t0 + 60)["source"] == "receipt"
    assert collected == []
    assert pf.promote_ci_gate(TRAIN_SHA, receipt, collect=col, now=t0 + pf.CI_RECEIPT_REUSE_S + 1)["ok"] is False
    receipt.write_text(json.dumps({"ok": True, "candidate_sha": "f" * 40, "checked_at": checked}))
    assert pf.promote_ci_gate(TRAIN_SHA, receipt, collect=col, now=t0 + 60)["ok"] is False
    receipt.write_text("not json")
    assert pf.promote_ci_gate(TRAIN_SHA, receipt, collect=col, now=t0 + 60)["ok"] is False
    assert len(collected) == 3


def test_prepare_rollback_and_emergency_skip_do_not_read_ci(monkeypatch):
    for argv in (["--action", "prepare", "--sha", TRAIN_SHA],
                 ["--action", "rollback", "--sha", TRAIN_SHA],
                 ["--action", "promote", "--sha", TRAIN_SHA, "--skip-ci-gate"]):
        rc, calls = _preflight(monkeypatch, argv, ci_ok=False)
        assert rc == 0 and calls == {"consume": 1, "collect": 0}, argv


def test_refused_binding_never_reads_ci_nor_consumes(monkeypatch):
    rc, calls = _preflight(monkeypatch, ["--action", "promote", "--sha", TRAIN_SHA], allowed=False)
    assert rc == 2 and calls == {"consume": 0, "collect": 0}


def _shell_harness(tmp_path, rc, emergency=""):
    import subprocess

    source = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    source = source[:source.rindex('case "$MODE" in')]
    fake = tmp_path / "fakepy"
    fake.write_text(f'#!/bin/sh\necho "ARGS:$*"\nexit {rc}\n')
    fake.chmod(0o755)
    script = tmp_path / "harness.sh"
    script.write_text(source + f'\nCANONICAL_SOURCE="{ROOT}"\nVENV_PYTHON="{fake}"\nEMERGENCY_SHA="{emergency}"\n'
                      + 'CI_RECEIPT_FILE=/x/post_merge_ci.json\n'
                      + 'write_deploy_receipt() { echo "RECEIPT:$*"; }\n'
                      + 'release_grant_preflight "$1" "$2"\necho AFTER\n')
    return lambda action: subprocess.run(["bash", str(script), action, TRAIN_SHA], capture_output=True, text=True)


def test_shell_promote_passes_receipt_and_rc3_is_a_ci_refusal(tmp_path):
    run = _shell_harness(tmp_path, 3)
    r = run("promote")
    assert r.returncode != 0 and "AFTER" not in r.stdout
    assert "--ci-receipt /x/post_merge_ci.json" in r.stdout and "--skip-ci-gate" not in r.stdout
    assert "RECEIPT:false promote blocked false post_merge_ci_refused" in r.stdout
    assert "before any release grant use was consumed" in r.stderr


def test_shell_binding_refusal_and_success_paths(tmp_path):
    r = _shell_harness(tmp_path, 2)("promote")
    assert r.returncode != 0 and "binds only that SHA" in r.stderr and "RECEIPT:" not in r.stdout
    ok = _shell_harness(tmp_path, 0)
    r = ok("prepare")
    assert r.returncode == 0 and "AFTER" in r.stdout and "--ci-receipt" not in r.stdout


def test_shell_emergency_promote_skips_the_ci_read(tmp_path):
    r = _shell_harness(tmp_path, 0, emergency=TRAIN_SHA)("promote")
    assert r.returncode == 0 and "--skip-ci-gate" in r.stdout and "--ci-receipt" not in r.stdout
