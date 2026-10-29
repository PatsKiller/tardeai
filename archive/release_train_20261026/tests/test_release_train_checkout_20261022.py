"""Release train checkout: explicit, real, self-created (ANCHOR RELEASE_TRAIN_CHECKOUT_20261022).

Blocker 2026-10-22: scripts/release_window.py defaulted RELEASE_CHECKOUT to ~/tradeai-exact-main-20260827, which no
longer existed, and nothing overrode it, so every train selection read MAIN_UNREADABLE. Now the default is
~/trade-ai-releases/train-checkout, TRADEAI_RELEASE_CHECKOUT overrides it (the claimer unit sets it explicitly), and
``Host.ensure_checkout`` creates it when absent (a locked, detached linked worktree of the canonical repo at
origin/main) or fetches origin main into it; a failure is a MAIN_UNREADABLE reason naming the path.
Also: release_train_arm.sh step E --apply NOOP re-runs the relay contract check and writes a PASS/FAIL receipt.

Hermetic: temp git repos only (a bare "origin", a canonical clone); the arming script runs in its $TMPDIR sandbox.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from scripts import release_window as RW
from scripts.lib import release_train_controller as RTC

ROOT = Path(__file__).resolve().parents[1]
CLAIM_UNIT = (
    ROOT / "docs" / "ops" / "packets" / "release-train-20261021" / "tradeai-release-train-claim.service.proposed"
)
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return p.stdout.strip()


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def repos(tmp_path: Path) -> types.SimpleNamespace:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    canonical = tmp_path / "canonical"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "a.txt").write_text("one\n")
    git(seed, "add", "a.txt")
    git(seed, "commit", "-q", "-m", "one")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origin), str(canonical)], check=True, env={**os.environ, **GIT_ENV})
    return types.SimpleNamespace(
        origin=origin, seed=seed, canonical=canonical, tmp=tmp_path, checkout=tmp_path / "releases" / "train-checkout"
    )


def advance(r: types.SimpleNamespace, text: str) -> str:
    (r.seed / "a.txt").write_text(text)
    git(r.seed, "commit", "-q", "-am", text.strip())
    git(r.seed, "push", "-q", "origin", "main")
    return git(r.seed, "rev-parse", "HEAD")


def host(r: types.SimpleNamespace, checkout: Path | None = None) -> RW.Host:
    return RW.Host(checkout=checkout or r.checkout, releases=r.tmp / "rel", canonical=r.canonical)


# ── resolve / create / read ─────────────────────────────────────────────────────────────────────────


def test_absent_checkout_is_created_detached_at_origin_main_and_main_head_reads(repos):
    head = git(repos.seed, "rev-parse", "HEAD")
    h = host(repos)
    assert not repos.checkout.exists()
    assert h.main_head() == head
    assert h._checkout_ready == "created"
    # a linked worktree of the canonical repo, detached at origin/main, locked against prune/hygiene
    assert git(repos.checkout, "rev-parse", "HEAD") == head
    rc = subprocess.run(["git", "-C", str(repos.checkout), "symbolic-ref", "-q", "HEAD"], capture_output=True)
    assert rc.returncode != 0, "HEAD must be detached"
    common = Path(git(repos.checkout, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert common.resolve() == (repos.canonical / ".git").resolve()
    assert (repos.canonical / ".git" / "worktrees" / "train-checkout" / "locked").is_file()
    assert git(repos.checkout, "remote", "get-url", "origin") == str(repos.origin)


def test_existing_checkout_is_fetched_and_head_is_not_moved(repos):
    first = git(repos.seed, "rev-parse", "HEAD")
    host(repos).ensure_checkout()
    newer = advance(repos, "two\n")
    h = host(repos)
    assert h.main_head() == newer
    assert h._checkout_ready == "fetched"
    assert git(repos.checkout, "rev-parse", "refs/remotes/origin/main") == newer  # objects present for changesets
    assert git(repos.checkout, "rev-parse", "HEAD") == first  # checkout_sha moves HEAD, not this


def test_ensure_runs_once_per_host(repos, monkeypatch):
    h = host(repos)
    h.ensure_checkout()
    calls = []
    real = h._run
    monkeypatch.setattr(h, "_run", lambda argv, **kw: (calls.append(argv), real(argv, **kw))[1])
    h.main_head()
    assert not any("fetch" in a or "worktree" in a for a in calls), calls


# ── override / default ──────────────────────────────────────────────────────────────────────────────


def _resolve(env: dict) -> dict:
    code = (
        "import json; from scripts import release_window as RW; "
        "print(json.dumps([str(RW.RELEASE_CHECKOUT), RW.RELEASE_CHECKOUT_SOURCE, str(RW.Host().checkout)]))"
    )
    e = {k: v for k, v in os.environ.items() if k != "TRADEAI_RELEASE_CHECKOUT"}
    e.update(env)
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def test_env_override_is_honoured(tmp_path):
    want = str(tmp_path / "elsewhere")
    assert _resolve({"HOME": str(tmp_path), "TRADEAI_RELEASE_CHECKOUT": want}) == [
        want,
        "env:TRADEAI_RELEASE_CHECKOUT",
        want,
    ]


def test_default_is_the_stable_path_never_a_dated_dev_tree(tmp_path):
    path, source, hosted = _resolve({"HOME": str(tmp_path)})
    assert path == hosted == str(tmp_path / "trade-ai-releases" / "train-checkout") and source == "default"
    # empty is not an override (a unit with `Environment=TRADEAI_RELEASE_CHECKOUT=` must not mean cwd)
    assert _resolve({"HOME": str(tmp_path), "TRADEAI_RELEASE_CHECKOUT": ""})[0] == path
    src = (ROOT / "scripts" / "release_window.py").read_text(encoding="utf-8")
    assert 'tradeai-exact-main-20260827")' not in src


def test_claimer_unit_sets_the_checkout_explicitly():
    lines = CLAIM_UNIT.read_text(encoding="utf-8").splitlines()
    env = [x for x in lines if x.startswith("Environment=")]
    assert "Environment=TRADEAI_RELEASE_CHECKOUT=%h/trade-ai-releases/train-checkout" in env


def test_hygiene_protects_the_checkout():
    rules = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))
    assert "~/trade-ai-releases/train-checkout" in rules["protected_paths"]["paths"]


def test_status_names_the_checkout(tmp_path):
    runner = RW.Runner(
        RW.Host(checkout=tmp_path / "co", releases=tmp_path, canonical=tmp_path), RW.State(tmp_path / "s")
    )
    _, body = runner.status()
    assert body["release_checkout"] == str(tmp_path / "co") and body["release_checkout_source"] in (
        "default",
        "env:TRADEAI_RELEASE_CHECKOUT",
    )


# ── fail closed ─────────────────────────────────────────────────────────────────────────────────────


def test_fetch_failure_is_an_explicit_reason_naming_the_path(repos):
    git(repos.canonical, "remote", "set-url", "origin", str(repos.tmp / "gone.git"))
    h = host(repos)
    with pytest.raises(RW.CheckoutUnavailable) as ei:
        h.main_head()
    msg = str(ei.value)
    assert str(repos.checkout) in msg and "fetch origin main" in msg
    assert not repos.checkout.exists()


def test_existing_checkout_fetch_failure_names_the_path(repos):
    host(repos).ensure_checkout()
    git(repos.canonical, "remote", "set-url", "origin", str(repos.tmp / "gone.git"))  # shared config
    with pytest.raises(RW.CheckoutUnavailable) as ei:
        host(repos).main_head()
    assert str(repos.checkout) in str(ei.value) and "fetch origin main failed" in str(ei.value)


def test_a_non_git_directory_is_refused_and_kept(repos):
    repos.checkout.mkdir(parents=True)
    (repos.checkout / "keep.txt").write_text("mine\n")
    with pytest.raises(RW.CheckoutUnavailable) as ei:
        host(repos).main_head()
    assert "not the top of a git work tree" in str(ei.value) and str(repos.checkout) in str(ei.value)
    assert sorted(p.name for p in repos.checkout.iterdir()) == ["keep.txt"]


def test_selection_halts_main_unreadable_with_the_path_before_reading_the_queue(tmp_path):
    path = tmp_path / "train-checkout"

    def boom():
        raise RW.CheckoutUnavailable(f"release checkout {path}: fetch origin main failed")

    def no_queue():
        raise AssertionError("the queue must not be read without a release checkout")

    fake = types.SimpleNamespace(
        host=types.SimpleNamespace(checkout=path, ensure_checkout=boom),
        queue=types.SimpleNamespace(snapshot=no_queue),
        say=lambda *_: None,
    )
    rec: dict = {}
    with pytest.raises(RTC.Halt) as ei:
        RTC.TrainController._select(fake, rec)
    assert ei.value.outcome == RTC.NO_OP and ei.value.reason == "MAIN_UNREADABLE"
    assert str(path) in ei.value.detail
    assert rec["release_checkout"] == {"path": str(path), "ok": False}


# ── release_train_arm.sh step E: NOOP re-runs the relay contract check ──────────────────────────────


def _arm_sandbox(tmp_path):
    from tests.test_release_train_arming_20261021 import Sandbox

    return Sandbox(tmp_path)


def test_step_e_noop_runs_the_relay_check_and_writes_a_pass_receipt(tmp_path):
    sb = _arm_sandbox(tmp_path)
    assert sb.apply("E").returncode == 0
    r = sb.apply("E")
    assert r.returncode == 0 and "NOOP" in r.stdout and "relay contract PASS" in r.stdout, r.stdout + r.stderr
    last = sb.receipt_rows()[-1]
    assert last["step"] == "E" and last["outcome"] == "NOOP"
    assert "relay contract PASS" in last["detail"]


def test_step_e_noop_with_a_failing_relay_check_writes_a_failed_receipt(tmp_path):
    sb = _arm_sandbox(tmp_path)
    assert sb.apply("E").returncode == 0
    wrap = tmp_path / "py-fails-relay-check"
    wrap.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do [[ "$a" == *check_n8n_relay_contract.py ]] && exit 1; done\n'
        f'exec {sys.executable} "$@"\n'
    )
    wrap.chmod(0o755)
    before = sb.live_env.read_text()
    r = sb.apply("E", RTARM_PY=str(wrap))
    assert r.returncode == 1 and "FAILED" in r.stdout, r.stdout + r.stderr
    last = sb.receipt_rows()[-1]
    assert last["step"] == "E" and last["outcome"] == "FAILED" and "relay contract check FAILED" in last["detail"]
    assert sb.live_env.read_text() == before
    assert sum(c.startswith("systemctl --user restart") for c in sb.calls()) == 1  # the first apply only


# ── CI gate ─────────────────────────────────────────────────────────────────────────────────────────


def test_ci_gate_is_registered():
    from scripts.lib import ci_gates

    names = dict(ci_gates.load_gates(ROOT))
    assert names.get("release_train_checkout_20261022") == ["tests/test_release_train_checkout_20261022.py"]
    doc = json.loads((ROOT / "config" / "ci_gates" / "release_train_checkout_20261022.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_CHECKOUT_20261022"
