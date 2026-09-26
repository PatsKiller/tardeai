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
