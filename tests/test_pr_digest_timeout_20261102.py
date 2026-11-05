"""A real subprocess timeout in one gh call must not abort the whole digest (2026-11-02)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import pr_merge_digest as pmd  # noqa: E402


class Run:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        return self.behaviour(argv, kw)


def fake(rc=0, out="{}"):
    class P:
        returncode = rc
        stdout = out
        stderr = ""
    return P()


def test_a_detail_timeout_becomes_a_marked_pr_not_an_exception(monkeypatch):
    run = Run(lambda argv, kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 90)))
    monkeypatch.setattr(pmd.subprocess, "run", run)
    out = pmd.enrich_pr("o/r", {"number": 2}, {"detail_retry_attempts": 2, "detail_retry_backoff_s": 0})
    assert out["_detail_error"].startswith("timeout after 90s")
    assert len(run.calls) == 2  # bounded retry, then the caller's policy


def test_a_listing_timeout_fails_visibly_after_bounded_retries(monkeypatch):
    run = Run(lambda argv, kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 90)))
    monkeypatch.setattr(pmd.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="failed after retries"):
        pmd.list_open_prs("o/r", 5, {"list_retry_attempts": 2, "list_retry_backoff_s": 0})
    assert len(run.calls) == 2


def test_a_401_is_not_retried(monkeypatch):
    run = Run(lambda argv, kw: fake(rc=1, out="HTTP 401: Bad credentials"))
    monkeypatch.setattr(pmd.subprocess, "run", run)
    rc, out = pmd._gh_retry(["pr", "view", "1"], {"detail_retry_attempts": 3}, attempts_key="detail_retry_attempts",
                            backoff_key="detail_retry_backoff_s", default_backoff=0)
    assert rc == 1 and "401" in out and len(run.calls) == 1
