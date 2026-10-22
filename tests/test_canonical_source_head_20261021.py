"""The deploy script refuses when CANONICAL_SOURCE's HEAD is not the SHA it prepares or promotes (2026-10-21).

Release 1's first promote failed because scripts/cio_phase2_exact_main_deploy.sh ran release_grant_preflight.py from
CANONICAL_SOURCE (the dev tree), which was on an older main and did not know --no-consume. The verifier is unchanged
(still CANONICAL_SOURCE's); require_canonical_source_at refuses, with a clear message, BEFORE any release grant use
and before prepare builds anything. Real git repos for ROOT, origin and CANONICAL_SOURCE; a fake python logs every
preflight call so "nothing was consulted" is proven. Hermetic: tmp HOME, releases and state.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = "scripts/cio_phase2_exact_main_deploy.sh"

FAKE_PY = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
case " $* " in
  *" --ci-only "*) exit "${FAKE_CI_RC:-2}" ;;
esac
if [[ "$*" == *release_grant_preflight.py* ]]; then
  if [[ "$*" == *"--no-consume"* ]]; then exit 0; fi
  exit 2
fi
exit 0
"""

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(*args) -> str:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    return ""


def _head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def _sandbox(tmp_path: Path):
    root = tmp_path / "root"
    (root / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(ROOT / DEPLOY, root / "scripts")
    shutil.copy2(ROOT / "scripts" / "lib" / "release_venv.sh", root / "scripts" / "lib")
    origin = tmp_path / "origin.git"
    _git("init", "-q", "--bare", "-b", "main", str(origin))
    _git("-C", str(root), "init", "-q", "-b", "main")
    _git("-C", str(root), "remote", "add", "origin", str(origin))
    (root / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    _git("-C", str(root), "add", ".gitignore")
    _git("-C", str(root), "commit", "-q", "-m", "c1")
    old = _head(root)
    _git("-C", str(root), "commit", "-q", "--allow-empty", "-m", "c2")
    new_sha = _head(root)
    _git("-C", str(root), "push", "-q", "origin", "main")
    canonical = tmp_path / "canonical"
    _git("clone", "-q", str(origin), str(canonical))
    (canonical / "scripts").mkdir()
    (canonical / "scripts" / "release_grant_preflight.py").write_text("# presence only\n", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("fakepy", "python3"):
        p = bindir / name
        p.write_text(FAKE_PY, encoding="utf-8")
        p.chmod(0o755)
    home = tmp_path / "home"
    rel = home / "trade-ai-releases" / "portfolio-server"
    prev, new = rel / "prev", rel / "new"
    for d, sha in ((prev, old), (new, new_sha)):
        d.mkdir(parents=True)
        (d / "BUILD_SHA").write_text(sha + "\n", encoding="utf-8")
    (rel / "CURRENT").symlink_to(prev)
    log = tmp_path / "py.log"
    env = {"PATH": f"{bindir}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(home), "TRADE_AI_CI": "1",
           "VENV_PYTHON": str(bindir / "fakepy"), "CANONICAL_SOURCE": str(canonical), "FAKE_LOG": str(log), **GIT_ENV}
    return root, env, log, canonical, old, new_sha, new, rel


def _run(root: Path, env: dict, *args):
    return subprocess.run(["bash", str(root / DEPLOY), *args], env=env, capture_output=True, text=True, timeout=120)


def _preflight_calls(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [ln for ln in log.read_text(encoding="utf-8").splitlines() if "release_grant_preflight.py" in ln]


def test_promote_with_a_stale_canonical_source_is_refused_before_any_grant_call(tmp_path):
    root, env, log, canonical, old, new_sha, new, rel = _sandbox(tmp_path)
    _git("-C", str(canonical), "checkout", "-q", "--detach", old)          # the dev tree is one commit behind
    p = _run(root, env, "promote", str(new))
    assert p.returncode != 0
    assert f"CANONICAL_SOURCE {canonical} HEAD {old[:12]} != promote SHA {new_sha[:12]}" in p.stderr, p.stderr
    assert "refused before any release grant use was consumed" in p.stderr
    assert f"merge --ff-only {new_sha}" in p.stderr                        # the message says how to fix it
    assert _preflight_calls(log) == []                                     # no --no-consume, no CI, no consume
    assert os.readlink(rel / "CURRENT").endswith("prev")


def test_promote_with_the_canonical_source_at_the_sha_reaches_the_ordered_gates(tmp_path):
    root, env, log, canonical, old, new_sha, new, rel = _sandbox(tmp_path)
    assert _head(canonical) == new_sha
    p = _run(root, env, "promote", str(new))                               # CI fake refuses (rc 2): stop there
    assert p.returncode != 0 and "activation refused" in p.stderr, p.stderr
    assert "verifier version proven" in p.stdout
    calls = _preflight_calls(log)
    assert calls and "--no-consume" in calls[0]                            # release-1 ordering is unchanged
    assert not [c for c in calls if "--action promote" in c and "--no-consume" not in c]


def test_promote_with_an_unreadable_canonical_source_is_refused(tmp_path):
    root, env, log, canonical, old, new_sha, new, rel = _sandbox(tmp_path)
    plain = tmp_path / "plain"
    (plain / "scripts").mkdir(parents=True)
    env["CANONICAL_SOURCE"] = str(plain)
    p = _run(root, env, "promote", str(new))
    assert p.returncode != 0 and "is not a readable git checkout" in p.stderr, p.stderr
    assert _preflight_calls(log) == []


def test_prepare_with_a_stale_canonical_source_is_refused_before_the_grant_and_the_build(tmp_path):
    root, env, log, canonical, old, new_sha, new, rel = _sandbox(tmp_path)
    _git("-C", str(canonical), "checkout", "-q", "--detach", old)
    p = _run(root, env, "prepare")
    assert p.returncode != 0
    assert f"HEAD {old[:12]} != prepare SHA {new_sha[:12]}" in p.stderr, p.stderr
    assert _preflight_calls(log) == []
    assert "Cloning CURRENT runtime tree" not in p.stdout                  # nothing was built


def test_prepare_with_the_canonical_source_at_the_sha_reaches_the_binding(tmp_path):
    root, env, log, canonical, old, new_sha, new, rel = _sandbox(tmp_path)
    p = _run(root, env, "prepare")                                         # the fake binding refuses: stop there
    assert p.returncode != 0 and "release grant binding refused prepare of " + new_sha in p.stderr, p.stderr
    assert [c for c in _preflight_calls(log) if "--action prepare" in c]


def test_the_check_runs_before_the_first_grant_call_in_both_commands():
    text = (ROOT / DEPLOY).read_text(encoding="utf-8")
    for cmd, first_grant in (("cmd_prepare() {", 'release_grant_preflight prepare "$(git_sha)"'),
                             ("cmd_promote() {", 'release_grant_preflight promote "$sha" --no-consume')):
        body = text[text.index(cmd):]
        body = body[: body.index("\n}\n")]
        assert body.index("require_canonical_source_at") < body.index(first_grant), cmd
