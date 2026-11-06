"""Release train arming finding 3 (ANCHOR RELEASE_TRAIN_GITHUB_APP_WRITER_20261021): ``GitHubAppWriter``.

Decision D2 (a): every train write uses a fresh 1-hour GitHub App installation token, minted from a JWT signed RS256
with the App key (``~/.config/tradeai/release_train/github-app.pem``; path from config, never logged). ``git push``
publishes ONLY the bound ``refs/heads/train/<id>``, with the token as an ``http.extraheader`` passed through the one
child's environment (never argv, never a git config file); the PR calls go to the REST API. ``GITHUB_WRITES_STATUS``
stays PROPOSED, so nothing constructs a live writer.

Hermetic: a throwaway RSA key generated in tmp_path (cryptography), a mocked GitHub API (a recording function; no
network), a local bare repository for the real push. psycopg2 is stubbed by the imported controller test module.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

import base64
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from tests.test_release_train_controller_20261021 import git  # noqa: E402
from scripts import release_window as RW  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ghs_TESTTOKEN0123456789abcdefTESTTOKEN"
TRAIN = "rt-20261021-1800-abc123"


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def app(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    d = tmp_path / "release_train"
    d.mkdir(mode=0o700)
    pem = d / "github-app.pem"
    pem.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    os.chmod(pem, 0o600)
    cfg = d / "github-app.json"
    cfg.write_text(
        json.dumps(
            {
                "app_id": T.APP_ID,
                "client_id": "Iv1.test",
                "installation_id": T.APP_INSTALLATION_ID,
                "repository": "PatsKiller/tardeai",
            }
        )
    )
    os.chmod(cfg, 0o600)
    return {"key": key, "pem": pem, "cfg": cfg}


class FakeApi:
    def __init__(self, *, token_status=201, perms=None):
        self.calls: list[tuple] = []
        self.token_status = token_status
        self.perms = perms or {"contents": "write", "pull_requests": "write", "checks": "read", "metadata": "read"}

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if url.endswith("/access_tokens"):
            return self.token_status, json.dumps(
                {"token": TOKEN, "expires_at": "2026-10-21T23:00:00Z", "permissions": self.perms}
            ).encode()
        if method == "GET" and "/pulls?" in url:
            return 200, b"[]"
        if method == "POST" and url.endswith("/pulls"):
            return 201, json.dumps({"number": 9001}).encode()
        if method == "PUT" and url.endswith("/merge"):
            return 200, json.dumps({"sha": "c" * 40, "merged": True}).encode()
        return 404, b"{}"


def _minter(app, api):
    return T.GitHubAppTokenMinter(key_path=app["pem"], config_path=app["cfg"], http=api, clock=lambda: 1_800_000_000)


def test_status_is_active_and_a_non_active_status_constructs_no_live_writer(monkeypatch):
    # Arming packet I.4 PR 2: the flip. The refusal while not ACTIVE stays pinned below.
    assert T.GITHUB_WRITES_STATUS == "ACTIVE"
    monkeypatch.setattr(T, "GITHUB_WRITES_STATUS", "PROPOSED")
    with pytest.raises(T.WriterNotArmed):
        T.GitHubAppWriter(RW.Host(), T.GhCliReader(RW.Host()))
    with pytest.raises(T.WriterNotArmed):
        T.build_controller(live=True)


def test_minting_signs_an_rs256_jwt_and_narrows_the_token(app):
    api = FakeApi()
    tok = _minter(app, api).mint("push_train_ref")
    assert tok.value == TOKEN and "redacted" in repr(tok) and TOKEN not in repr(tok) and TOKEN not in str(tok)
    method, url, headers, body = api.calls[0]
    assert (method, url) == ("POST", f"https://api.github.com/app/installations/{T.APP_INSTALLATION_ID}/access_tokens")
    jwt = headers["Authorization"].split(" ", 1)[1]
    head, body64, sig = jwt.split(".")

    def unb64(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    assert json.loads(unb64(head)) == {"alg": "RS256", "typ": "JWT"}
    claims = json.loads(unb64(body64))
    assert claims == {"iat": 1_800_000_000 - 60, "exp": 1_800_000_000 + 540, "iss": "Iv1.test"}
    # RS256 = RSASSA-PKCS1-v1_5 / SHA-256; raises InvalidSignature if wrong
    app["key"].public_key().verify(unb64(sig), f"{head}.{body64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    try:  # cross-check with PyJWT where it is installed (the release venv); CI installs only cryptography
        import jwt as pyjwt
    except ImportError:
        pyjwt = None
    if pyjwt is not None:
        assert (
            pyjwt.decode(
                jwt, app["key"].public_key(), algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
            )
            == claims
        )
    assert json.loads(body) == {"repositories": ["tardeai"], "permissions": T.APP_TOKEN_PERMISSIONS}


def test_a_wider_token_is_refused(app):
    with pytest.raises(T.AppTokenError, match="wider"):
        _minter(app, FakeApi(perms={"contents": "write", "administration": "write"})).mint("x")


def test_a_refused_mint_names_no_secret(app):
    with pytest.raises(T.AppTokenError) as e:
        _minter(app, FakeApi(token_status=401)).mint("x")
    assert "HTTP 401" in str(e.value) and "BEGIN" not in str(e.value)


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_an_unsafe_key_is_refused(app, mode):
    os.chmod(app["pem"], mode)
    with pytest.raises(T.AppTokenError, match="mode 600"):
        _minter(app, FakeApi()).mint("x")


def test_a_symlinked_key_is_refused(app, tmp_path):
    link = tmp_path / "link.pem"
    link.symlink_to(app["pem"])
    m = T.GitHubAppTokenMinter(key_path=link, config_path=app["cfg"], http=FakeApi())
    with pytest.raises(T.AppTokenError, match="symlink"):
        m.mint("x")


def _origin(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "--initial-branch=main", str(origin))
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    (work / "a.txt").write_text("a\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "a")
    return origin, work, git(work, "rev-parse", "HEAD")


class _Host:
    def __init__(self, checkout):
        self.checkout = checkout


def test_push_publishes_only_the_bound_train_ref_with_no_token_in_argv_or_config(app, tmp_path):
    origin, work, sha = _origin(tmp_path)
    seen = {}

    def runner(argv, *, env, timeout):
        seen.update(argv=list(argv), env=dict(env))
        return T._run(argv, env=env, timeout=timeout)

    api = FakeApi()
    w = T.GitHubAppWriter(
        _Host(work), None, minter=_minter(app, api), status="ACTIVE", remote_url=f"file://{origin}", runner=runner
    )
    with w.reservation("intent-push", "push_train_ref"):
        out = w.push_train_ref(TRAIN, sha)
    assert out == {"ref": f"refs/heads/train/{TRAIN}", "sha": sha, "token_expires_at": "2026-10-21T23:00:00Z"}
    refs = git(origin, "for-each-ref", "--format=%(refname)")
    assert refs.splitlines() == [f"refs/heads/train/{TRAIN}"]
    assert TOKEN not in " ".join(seen["argv"]) and seen["argv"][-1] == f"{sha}:refs/heads/train/{TRAIN}"
    assert seen["env"]["GIT_CONFIG_COUNT"] == "2" and "AUTHORIZATION: basic " in seen["env"]["GIT_CONFIG_VALUE_0"]
    assert seen["env"]["GIT_CONFIG_KEY_1"] == "credential.helper" and seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    for cfg in (work / ".git" / "config", origin / "config"):
        assert "extraheader" not in cfg.read_text() and TOKEN not in cfg.read_text()
    assert TOKEN not in json.dumps(w.minter.audit) and w.minter.audit[0]["action"] == "push_train_ref"


def test_production_push_url_scopes_the_header_to_github(app, tmp_path):
    seen = {}

    def runner(argv, *, env, timeout):
        seen.update(argv=list(argv), env=dict(env))
        return 0, ""

    w = T.GitHubAppWriter(_Host(tmp_path), None, minter=_minter(app, FakeApi()), status="ACTIVE", runner=runner)
    with w.reservation("intent-push", "push_train_ref"):
        w.push_train_ref(TRAIN, "a" * 40)
    assert seen["argv"][-2] == "https://github.com/PatsKiller/tardeai.git"
    assert seen["env"]["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert "push" in seen["argv"] and "config" not in seen["argv"] and "origin" not in seen["argv"]


@pytest.mark.parametrize(
    "ref",
    ["refs/heads/main", "refs/heads/train/rt-20261021-1800-zzzzzz", "refs/tags/v1", "refs/heads/train/../main", "main"],
)
def test_any_other_ref_is_refused_before_git_runs(app, tmp_path, ref):
    ran = []
    w = T.GitHubAppWriter(
        _Host(tmp_path),
        None,
        minter=_minter(app, FakeApi()),
        status="ACTIVE",
        runner=lambda *a, **k: ran.append(a) or (0, ""),
    )
    tok = w.minter.mint("x")
    with pytest.raises(PermissionError, match="refused"):
        w._push("a" * 40, ref, bound_ref=f"refs/heads/train/{TRAIN}", token=tok)
    assert ran == []


@pytest.mark.parametrize("train_id", ["../main", "rt-1", "main", "rt-20261021-1800-abc123/../../main"])
def test_a_bad_train_id_is_refused(app, tmp_path, train_id):
    w = T.GitHubAppWriter(
        _Host(tmp_path), None, minter=_minter(app, FakeApi()), status="ACTIVE", runner=lambda *a, **k: (0, "")
    )
    with pytest.raises(ValueError):
        w.push_train_ref(train_id, "a" * 40)


def test_a_failed_push_scrubs_the_token(app, tmp_path):
    import base64

    b64 = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    w = T.GitHubAppWriter(
        _Host(tmp_path),
        None,
        minter=_minter(app, FakeApi()),
        status="ACTIVE",
        runner=lambda *a, **k: (128, f"fatal: header {b64} token {TOKEN} rejected"),
    )
    with pytest.raises(RuntimeError) as e, w.reservation("intent-push", "push_train_ref"):
        w.push_train_ref(TRAIN, "a" * 40)
    assert TOKEN not in str(e.value) and b64 not in str(e.value) and "***" in str(e.value)


def test_pr_open_and_merge_use_the_app_token_through_the_api(app, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    api = FakeApi()
    w = T.GitHubAppWriter(_Host(tmp_path), None, minter=_minter(app, api), status="ACTIVE")
    with w.reservation("intent-open", "open_batch_pr"):
        assert w.open_or_update_batch_pr(TRAIN, "a" * 40, "Release train", "body") == 9001
    with w.reservation("intent-merge", "merge_batch_pr"):
        assert w.merge_batch_pr(9001, "b" * 40, "Release train") == "c" * 40
    api_calls = [c for c in api.calls if "/access_tokens" not in c[1]]
    assert [c[0] for c in api_calls] == ["GET", "POST", "PUT"]
    assert all(c[2]["Authorization"] == f"token {TOKEN}" for c in api_calls)
    assert json.loads(api_calls[1][3])["head"] == f"train/{TRAIN}" and json.loads(api_calls[1][3])["base"] == "main"
    assert json.loads(api_calls[2][3]) == {"sha": "b" * 40, "merge_method": "merge", "commit_title": "Release train"}
    assert sum(1 for c in api.calls if "/access_tokens" in c[1]) == 2  # a fresh token per reservation
    assert TOKEN not in caplog.text and TOKEN not in json.dumps(w.minter.audit)


def test_no_token_reaches_a_train_receipt_or_run_record(app, tmp_path):
    """The writer returns no token; the claim receipt and run record are built from return values only."""
    w = T.GitHubAppWriter(
        _Host(tmp_path), None, minter=_minter(app, FakeApi()), status="ACTIVE", runner=lambda *a, **k: (0, "")
    )
    with w.reservation("intent-push", "push_train_ref"):
        push = w.push_train_ref(TRAIN, "a" * 40)
    with w.reservation("intent-open", "open_batch_pr"):
        pr = w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")
    rec = {"push": push, "pr": pr, "audit": w.minter.audit}
    assert TOKEN not in json.dumps(rec)


def test_release_venv_libraries_are_the_ones_used():
    src = (ROOT / "scripts/lib/release_train_controller.py").read_text(encoding="utf-8")
    assert "padding.PKCS1v15(), hashes.SHA256()" in src and "import jwt" not in src
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0


def test_packet_finding_3_is_marked_fixed():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    seg = text[text.index("3. **`GITHUB_WRITES_STATUS` does not deliver D2.**") :]
    assert "**Status: FIXED (built, not armed)**" in seg[:1400]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_github_app_writer_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_GITHUB_APP_WRITER_20261021"
    assert "tests/test_release_train_github_app_writer_20261021.py" in doc["files"]
