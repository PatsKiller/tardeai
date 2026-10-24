"""D2 helper (ANCHOR RELEASE_TRAIN_GITHUB_APP_CONFIG_20261023): ``scripts/ops/release_train_github_app_config.py``.

The operator-run helper discovers the App installation for the repository owner (``GET /app/installations`` with an
RS256 JWT), proves repository access with one narrowed installation token that is then dropped
(``POST /app/installations/<id>/access_tokens`` + ``GET /installation/repositories``), and writes
``github-app.json`` atomically, mode 600, with the keys ``GitHubAppTokenMinter.config`` reads.

Hermetic: a throwaway RSA key generated in tmp_path, a fake HTTP layer (a recording function; no network), tmp
output paths. The real ``~/.config/tradeai/release_train`` is never opened. psycopg2 is stubbed by the imported
controller test module.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import tests.test_release_train_controller_20261021  # noqa: F401  (psycopg2 stub)
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.ops import release_train_github_app_config as H  # noqa: E402

TOKEN = "ghs_D2HELPERTESTTOKEN0123456789abcdefXYZ"
REPO = "PatsKiller/tardeai"
APP_ID = "5419776"
NOW = 1_792_800_000.0


@pytest.fixture
def app(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    d = tmp_path / "release_train"
    d.mkdir(mode=0o700)
    pem = d / "github-app.pem"
    pem_bytes = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
    pem.write_bytes(pem_bytes)
    os.chmod(pem, 0o600)
    return {"key": key, "pem": pem, "pem_bytes": pem_bytes, "out": d / "github-app.json", "dir": d}


def _inst(iid, login, **extra):
    return {"id": iid, "account": {"login": login, "type": "User"}, "app_slug": "tradeai-release-train",
            "repository_selection": "selected", "suspended_at": None, **extra}


class FakeGitHub:
    def __init__(self, installations=None, *, token_status=201, visible=(REPO,), list_status=200):
        self.installations = installations if installations is not None else [_inst(173961421, "PatsKiller")]
        self.token_status, self.visible, self.list_status = token_status, list(visible), list_status
        self.calls: list[tuple] = []
        self.jwts: list[str] = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        auth = headers.get("Authorization", "")
        if method == "GET" and "/app/installations?" in url:
            self.jwts.append(auth.split(" ", 1)[1])
            return 200, json.dumps(self.installations).encode()
        if method == "POST" and url.endswith("/access_tokens"):
            self.jwts.append(auth.split(" ", 1)[1])
            return self.token_status, json.dumps({"token": TOKEN, "expires_at": "2026-10-24T00:00:00Z",
                                                  "permissions": dict(T.APP_TOKEN_PERMISSIONS)}).encode()
        if method == "GET" and "/installation/repositories" in url:
            assert auth == f"Bearer {TOKEN}"
            repos = [{"full_name": r} for r in self.visible]
            return self.list_status, json.dumps({"total_count": len(repos), "repositories": repos}).encode()
        return 404, b"{}"


def _run(app, api, *extra, capsys):
    argv = ["--app-id", APP_ID, "--repository", REPO, "--key-path", str(app["pem"]), "--out", str(app["out"]),
            *extra]
    rc = H.main(argv, http=api, clock=lambda: NOW)
    out, err = capsys.readouterr()
    return rc, out, err


def _assert_no_secret(app, api, *texts):
    secrets = [TOKEN, app["pem_bytes"].decode(), *api.jwts]
    body = app["pem_bytes"].decode().split("-----")[2].strip().splitlines()[1]  # a line of key material
    secrets.append(body)
    for t in texts:
        for s in secrets:
            assert s not in t


def test_writes_config_mode_600_with_the_keys_the_controller_reads(app, capsys):
    api = FakeGitHub()
    rc, out, err = _run(app, api, capsys=capsys)
    assert rc == 0, err
    st = os.lstat(app["out"])
    assert stat.S_ISREG(st.st_mode) and (st.st_mode & 0o777) == 0o600
    cfg = json.loads(app["out"].read_text())
    assert cfg == {"app_id": 5419776, "installation_id": 173961421, "repository": REPO}
    assert isinstance(cfg["installation_id"], int)
    # The controller's own reader accepts the file it wrote.
    m = T.GitHubAppTokenMinter(key_path=app["pem"], config_path=app["out"], http=api)
    assert m.config() == {"iss": "5419776", "installation_id": 173961421, "repository": REPO}
    summary = json.loads(out)
    assert summary["write"]["result"] == "written" and summary["verified"]["token_discarded"] is True
    assert summary["verified"]["repositories"] == [REPO]
    # The call sequence: list installations, mint narrowed token, list its repositories.
    assert [(c[0], c[1].split("?")[0]) for c in api.calls] == [
        ("GET", f"{T.GITHUB_API}/app/installations"),
        ("POST", f"{T.GITHUB_API}/app/installations/173961421/access_tokens"),
        ("GET", f"{T.GITHUB_API}/installation/repositories"),
    ]
    assert json.loads(api.calls[1][3]) == {"repositories": ["tardeai"], "permissions": T.APP_TOKEN_PERMISSIONS}
    _assert_no_secret(app, api, out, err, app["out"].read_text())
    assert not [p for p in app["dir"].iterdir() if p.name.endswith(".tmp")]


def test_jwt_is_rs256_signed_by_the_key_with_iss_app_id(app, capsys):
    api = FakeGitHub()
    assert _run(app, api, capsys=capsys)[0] == 0
    head, body, sig = api.jwts[0].split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    assert json.loads(pad(head)) == {"alg": "RS256", "typ": "JWT"}
    claims = json.loads(pad(body))
    assert claims["iss"] == APP_ID and claims["exp"] - claims["iat"] == 600
    app["key"].public_key().verify(pad(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())


def test_client_id_is_used_as_iss_and_written(app, capsys):
    api = FakeGitHub()
    assert _run(app, api, "--client-id", "Iv23liTEST", capsys=capsys)[0] == 0
    assert json.loads(app["out"].read_text())["client_id"] == "Iv23liTEST"
    body = api.jwts[0].split(".")[1]
    assert json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))["iss"] == "Iv23liTEST"


def test_dry_run_prints_and_writes_nothing(app, capsys):
    api = FakeGitHub()
    rc, out, err = _run(app, api, "--dry-run", capsys=capsys)
    assert rc == 0, err
    assert not os.path.lexists(app["out"])
    summary = json.loads(out)
    assert summary["dry_run"] is True and summary["write"]["result"] == "would_write"
    assert summary["config"] == {"app_id": 5419776, "installation_id": 173961421, "repository": REPO}
    _assert_no_secret(app, api, out, err)
    assert sorted(p.name for p in app["dir"].iterdir()) == ["github-app.pem"]


def test_multiple_installations_pick_the_repo_owner(app, capsys):
    api = FakeGitHub([_inst(1001, "someone-else"), _inst(2002, "patskiller"), _inst(3003, "AnotherOrg")])
    rc, out, err = _run(app, api, capsys=capsys)
    assert rc == 0, err
    assert json.loads(app["out"].read_text())["installation_id"] == 2002
    assert api.calls[1][1].endswith("/app/installations/2002/access_tokens")


def test_wrong_repo_owner_is_refused_and_nothing_written(app, capsys):
    api = FakeGitHub([_inst(1001, "someone-else")])
    rc, out, err = _run(app, api, capsys=capsys)
    assert rc == 2 and "REFUSED" in err and "no installation on account 'PatsKiller'" in err
    assert not os.path.lexists(app["out"]) and out == ""
    assert all("/access_tokens" not in c[1] for c in api.calls)
    _assert_no_secret(app, api, out, err)


def test_repo_not_in_installation_is_refused(app, capsys):
    # GitHub answers 422 when a narrowed token names a repository the installation cannot see.
    api = FakeGitHub(token_status=422)
    rc, out, err = _run(app, api, capsys=capsys)
    assert rc == 2 and "HTTP 422" in err and not os.path.lexists(app["out"])
    _assert_no_secret(app, api, out, err)


def test_token_that_cannot_see_the_repo_is_refused(app, capsys):
    api = FakeGitHub(visible=("PatsKiller/other",))
    rc, out, err = _run(app, api, capsys=capsys)
    assert rc == 2 and "cannot see PatsKiller/tardeai" in err and not os.path.lexists(app["out"])
    _assert_no_secret(app, api, out, err)


def test_ambiguous_and_suspended_installations_are_refused(app, capsys):
    rc, _, err = _run(app, FakeGitHub([_inst(1, "PatsKiller"), _inst(2, "PatsKiller")]), capsys=capsys)
    assert rc == 2 and "ambiguous" in err
    rc, _, err = _run(app, FakeGitHub([_inst(1, "PatsKiller", suspended_at="2026-10-20T00:00:00Z")]), capsys=capsys)
    assert rc == 2 and "suspended" in err
    assert not os.path.lexists(app["out"])


def test_key_must_be_mode_600(app, capsys):
    os.chmod(app["pem"], 0o644)
    api = FakeGitHub()
    rc, out, err = _run(app, api, capsys=capsys)
    assert rc == 2 and "mode 600" in err and api.calls == []
    _assert_no_secret(app, api, out, err)


def test_existing_different_file_is_archived_not_deleted(app, capsys):
    app["out"].write_text('{"app_id": 1, "installation_id": 2, "repository": "x/y"}\n')
    os.chmod(app["out"], 0o600)
    old = app["out"].read_bytes()
    rc, out, err = _run(app, FakeGitHub(), capsys=capsys)
    assert rc == 0, err
    archived = Path(json.loads(out)["write"]["archived"])
    assert archived.read_bytes() == old and archived.parent == app["dir"]
    assert json.loads(app["out"].read_text())["installation_id"] == 173961421
    # A second identical run changes nothing and archives nothing.
    rc, out, _ = _run(app, FakeGitHub(), capsys=capsys)
    assert rc == 0 and json.loads(out)["write"]["result"] == "unchanged"
    assert len([p for p in app["dir"].iterdir() if p.name.endswith(".archived")]) == 1


def test_symlinked_output_is_refused(app, tmp_path, capsys):
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    os.symlink(target, app["out"])
    rc, _, err = _run(app, FakeGitHub(), capsys=capsys)
    assert rc == 2 and "not a regular file" in err and target.read_text() == "{}"


def test_bad_arguments_are_refused_before_any_call(app, capsys):
    api = FakeGitHub()
    rc = H.main(["--app-id", "abc", "--repository", REPO, "--key-path", str(app["pem"]), "--out", str(app["out"])],
                http=api)
    assert rc == 2 and api.calls == []
    rc = H.main(["--app-id", APP_ID, "--repository", "not-a-repo", "--key-path", str(app["pem"]),
                 "--out", str(app["out"])], http=api)
    assert rc == 2 and api.calls == []
    capsys.readouterr()


def test_default_paths_are_the_controllers():
    a = H.build_parser().parse_args(["--app-id", "1", "--repository", REPO])
    assert Path(a.key_path) == T.APP_KEY_PATH and Path(a.out) == T.APP_CONFIG_PATH
