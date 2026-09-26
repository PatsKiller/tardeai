"""A git-push grant must name what it covers (AGENTS.md 1.3.0 PROPOSED; review 2026-09-25).

Failure it guards: any active git-push grant authorized -- and budget-overrode -- a push to ANY
branch; a 100-use campaign grant covered unrelated branches. Default mode WARNS (so existing
sessions are not broken while the operator decides); TRADEAI_GUARD_PUSH_SCOPE_ENFORCE=1 refuses.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".cursor" / "hooks"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import guard_push_auth as G  # noqa: E402

SHA = "8fdfeeb3b0c1d2e3f4a5b6c7d8e9f00112233445"


def _ledger(adir: Path, *cmd: str) -> None:
    adir.mkdir(mode=0o700, parents=True, exist_ok=True)
    subprocess.run(
        ["python3", str(HOOKS / "guard_ledger.py"), *cmd],
        env={**os.environ, "GUARD_APPROVALS_DIR": str(adir)},
        check=True,
        capture_output=True,
        text=True,
    )


def _grant(adir: Path, reason: str, *, uses: int = 3, expires_in: int = 3600) -> None:
    _ledger(
        adir,
        "grant",
        "--tier",
        "git-push",
        "--expires",
        str(int(time.time()) + expires_in),
        "--uses",
        str(uses),
        "--reason",
        reason,
    )


# --- pure scope matcher -----------------------------------------------------------------
def test_branch_named_in_reason_is_scoped():
    ok, _ = G.grant_scope_covers("push wt/m5-options @8fdfeeb3b", branch="wt/m5-options", head_sha=SHA)
    assert ok


def test_head_sha_prefix_in_reason_is_scoped():
    ok, _ = G.grant_scope_covers("push PR head 8fdfeeb3b", branch="other", head_sha=SHA)
    assert ok


def test_wrong_branch_is_not_scoped():
    ok, why = G.grant_scope_covers("push wt/lane-registry", branch="wt/m5-options", head_sha=SHA)
    assert not ok and "neither" in why


def test_wrong_sha_is_not_scoped():
    ok, _ = G.grant_scope_covers("push head deadbeef1", branch="wt/m5-options", head_sha=SHA)
    assert not ok


def test_campaign_grant_without_branch_or_sha_is_not_scoped():
    reason = "trade-ai-maturity-overnight-20260912: push only validated campaign branches"
    ok, _ = G.grant_scope_covers(reason, branch="wt/m5-options", head_sha=SHA)
    assert not ok


def test_detached_head_never_matches_by_name():
    ok, _ = G.grant_scope_covers("push HEAD to main", branch="HEAD", head_sha=SHA)
    assert not ok


# --- ledger-backed decision -------------------------------------------------------------
def test_unscoped_grant_warns_but_authorizes_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(G.SCOPE_ENFORCE_ENV, raising=False)
    adir = tmp_path / "a"
    _grant(adir, "campaign grant, no branch named")
    v = G.push_authorized_by_guard_scoped(branch="wt/x", head_sha=SHA, adir=adir)
    assert v["ok"] is True and v["scoped"] is False and v["enforced"] is False


def test_unscoped_grant_refused_when_enforced(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(G.SCOPE_ENFORCE_ENV, "1")
    adir = tmp_path / "a"
    _grant(adir, "campaign grant, no branch named")
    v = G.push_authorized_by_guard_scoped(branch="wt/x", head_sha=SHA, adir=adir)
    assert v["ok"] is False and v["enforced"] is True


def test_scoped_grant_allowed_when_enforced(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(G.SCOPE_ENFORCE_ENV, "1")
    adir = tmp_path / "a"
    _grant(adir, "push wt/x at 8fdfeeb3b")
    assert G.push_authorized_by_guard_scoped(branch="wt/x", head_sha=SHA, adir=adir)["ok"] is True


def test_expired_grant_never_authorizes(tmp_path: Path):
    adir = tmp_path / "a"
    _grant(adir, "push wt/x", expires_in=3600)
    # Rewrite the expiry into the past through the ledger's own schema.
    import json

    ledger = next(adir.glob("*.json"))
    doc = json.loads(ledger.read_text())
    doc["git-push"]["expires"] = int(time.time()) - 5
    ledger.write_text(json.dumps(doc))
    assert G.push_authorized_by_guard_scoped(branch="wt/x", head_sha=SHA, adir=adir)["ok"] is False


def test_consumed_grant_never_authorizes(tmp_path: Path):
    adir = tmp_path / "a"
    _grant(adir, "push wt/x", uses=1)
    _ledger(adir, "consume", "--tier", "git-push")
    assert G.push_authorized_by_guard_scoped(branch="wt/x", head_sha=SHA, adir=adir)["ok"] is False


# --- the real pre-push hook --------------------------------------------------------------
def test_pre_push_hook_warns_then_refuses_an_unscoped_grant(tmp_path: Path):
    from tests.test_guard_push_auth import _mini_repo, _run

    adir = tmp_path / "approvals"
    src = _mini_repo(tmp_path)
    _grant(adir, "campaign grant, no branch named")
    env = {
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(src / ".git/tradeai-push-budget.json"),
        "GUARD_APPROVALS_DIR": str(adir),
        "PYTHONPATH": str(src),
    }
    warn = _run(["git", "push", "-u", "origin", "main"], cwd=src, env=env)
    assert warn.returncode == 0, warn.stderr + warn.stdout
    assert "does not name branch 'main'" in warn.stdout + warn.stderr

    (src / "README").write_text("second\n")
    subprocess.run(["git", "add", "README"], cwd=src, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=src, check=True)
    refused = _run(["git", "push", "origin", "main"], cwd=src, env={**env, G.SCOPE_ENFORCE_ENV: "1"})
    assert refused.returncode != 0, refused.stdout
