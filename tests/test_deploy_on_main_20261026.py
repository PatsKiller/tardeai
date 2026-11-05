"""Hermetic tests for deploy-on-main poller (AGENTS.md §25.10 soft-add)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "persistent-state"
    (root / "data" / "runtime" / "release_window").mkdir(parents=True)
    (root / "data" / "runtime" / "deploy_on_main").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(root / "data" / "runtime" / "release_window"))
    monkeypatch.setenv("TRADEAI_DEPLOY_DELEGATION_SOFT", "1")
    return root


def test_decide_noop_when_already_served(tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.lib import deploy_on_main as D

    releases = tmp_path / "releases"
    pin = releases / "abcdef1234567890-main-exact-phase2-ts"
    pin.mkdir(parents=True)
    current = releases / "CURRENT"
    current.symlink_to(pin)
    monkeypatch.setenv("TRADEAI_PORTFOLIO_SERVER_ROOT", str(releases))

    monkeypatch.setattr(D, "fetch_origin_main", lambda repo: (True, ""))
    monkeypatch.setattr(D, "origin_main_sha", lambda repo: "abcdef1234567890aaaaaaaaaaaaaaaaaaaaaaaa")

    d = D.decide(repo=ROOT, releases=releases, fetch=False)
    assert d.action == "noop"
    assert d.reason == "already_served"


def test_decide_refuse_when_stop_set(tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.lib import deploy_on_main as D

    latch = Path(os.environ["TRADEAI_RELEASE_WINDOW_STATE_DIR"]) / "STOP.json"
    latch.write_text(json.dumps({"reason": "operator_test"}), encoding="utf-8")

    releases = tmp_path / "releases"
    pin = releases / "1111111111111111-main-exact-phase2-ts"
    pin.mkdir(parents=True)
    (releases / "CURRENT").symlink_to(pin)
    monkeypatch.setenv("TRADEAI_PORTFOLIO_SERVER_ROOT", str(releases))
    monkeypatch.setattr(D, "fetch_origin_main", lambda repo: (True, ""))
    monkeypatch.setattr(D, "origin_main_sha", lambda repo: "2222222222222222222222222222222222222222")

    d = D.decide(repo=ROOT, releases=releases, fetch=False)
    assert d.action == "refuse"
    assert d.reason.startswith("stop_latched:")


def test_write_receipt_manual_emergency(state_root: Path) -> None:
    from scripts.lib.deploy_on_main import PATH_MANUAL_EMERGENCY, write_receipt

    dest = write_receipt(
        path_kind=PATH_MANUAL_EMERGENCY,
        outcome="would_promote",
        main_sha="a" * 40,
        current_sha_before="b" * 40,
        reason="test",
    )
    assert dest.is_file()
    body = json.loads(dest.read_text(encoding="utf-8"))
    assert body["schema"] == "DeployOnMainReceipt@v1"
    assert body["path"] == "manual_emergency"
    latest = Path(os.environ["TRADEAI_STATE_ROOT"]) / "data" / "runtime" / "deploy_on_main" / "latest.json"
    assert latest.is_file()


def test_poll_once_would_promote_without_apply(tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.lib import deploy_on_main as D

    releases = tmp_path / "releases"
    pin = releases / "1111111111111111-main-exact-phase2-ts"
    pin.mkdir(parents=True)
    (releases / "CURRENT").symlink_to(pin)
    monkeypatch.setenv("TRADEAI_PORTFOLIO_SERVER_ROOT", str(releases))
    monkeypatch.setattr(D, "fetch_origin_main", lambda repo: (True, ""))
    monkeypatch.setattr(D, "origin_main_sha", lambda repo: "3333333333333333333333333333333333333333")

    out = D.poll_once(repo=ROOT, fetch=False, apply=False)
    assert out["action"] == "promote"
    assert out["outcome"] == "would_promote"


def test_post_release_tester_skip_http(state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import post_release_tester as PRT

    releases = tmp_path / "releases"
    pin = releases / "abcdef1234567890-main-exact-phase2-ts"
    pin.mkdir(parents=True)
    (releases / "CURRENT").symlink_to(pin)
    monkeypatch.setenv("TRADEAI_PORTFOLIO_SERVER_ROOT", str(releases))
    row = PRT.run(skip_http=True)
    assert row["outcome"] == "PASSED"


def test_emergency_script_refuses_without_env(tmp_path: Path) -> None:
    import subprocess

    env = os.environ.copy()
    env.pop("TRADEAI_EMERGENCY_RELEASE_SHA", None)
    r = subprocess.run(
        ["bash", str(ROOT / "scripts" / "emergency_manual_promote.sh"), "--dry-run"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "TRADEAI_EMERGENCY_RELEASE_SHA" in (r.stderr + r.stdout)
