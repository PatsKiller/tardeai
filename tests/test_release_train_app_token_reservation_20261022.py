"""Release train Phase 6 prerequisite (ANCHOR RELEASE_TRAIN_APP_TOKEN_RESERVATION_20261022): the App token writer.

Arming packet ``docs/ops/packets/release-train-arming-20261021/README.md`` §I.1 item 3: mint a 1-hour GitHub App
installation token **per reservation** and pass it as ``GH_TOKEN`` **only to the writer's child processes**.
``GitHubAppWriter`` (finding 3) already minted per write call; this pins:

- the operator's App (id 5419776, installation 173961421, ``PatsKiller/tardeai``): a config file naming another App,
  installation or repository is refused before anything is signed or sent; an absent config uses the pins;
- the reservation binding: no token is minted outside ``reservation(intent_id, action)``, or for another action;
  one mint per reservation, dropped when it ends; the controller's ``_cap_effect`` enters it with the reservation's
  intent id after ``reserve()`` and leaves it when the effect ends;
- the child environment: ``GH_TOKEN`` is the App token, every inherited ``GH_TOKEN``/``GITHUB_TOKEN`` is stripped,
  and this process's ``os.environ`` is never modified.

``GITHUB_WRITES_STATUS`` stays PROPOSED (I.4 PR 2 is the operator's flip). Hermetic: a throwaway RSA key in
tmp_path, a recording fake API, a fake git runner. The real key (``~/.config/tradeai/release_train/github-app.pem``)
is never opened: every minter here is constructed with tmp paths, and one test proves the default path is not read.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.lib import release_train_controller as T

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ghs_APPTOKEN0123456789abcdefAPPTOKEN"
HOST_TOKEN = "gho_HOSTUSERTOKEN_must_never_reach_a_writer_child"
TRAIN = "rt-20261022-1800-abc123"


@pytest.fixture
def key_dir(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    d = tmp_path / "release_train"
    d.mkdir(mode=0o700)
    pem = d / "github-app.pem"
    pem.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    os.chmod(pem, 0o600)
    return d


def _write_cfg(d: Path, **over) -> Path:
    doc = {"app_id": T.APP_ID, "installation_id": T.APP_INSTALLATION_ID, "repository": T.APP_REPOSITORY}
    doc.update(over)
    p = d / "github-app.json"
    p.write_text(json.dumps(doc))
    os.chmod(p, 0o600)
    return p


class FakeApi:
    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if url.endswith("/access_tokens"):
            return 201, json.dumps(
                {"token": TOKEN, "expires_at": "2026-10-22T23:00:00Z", "permissions": dict(T.APP_TOKEN_PERMISSIONS)}
            ).encode()
        if method == "GET" and "/pulls?" in url:
            return 200, b"[]"
        if method == "POST" and url.endswith("/pulls"):
            return 201, json.dumps({"number": 77}).encode()
        if method == "PUT" and url.endswith("/merge"):
            return 200, json.dumps({"sha": "c" * 40}).encode()
        return 404, b"{}"

    def mints(self):
        return [c for c in self.calls if c[1].endswith("/access_tokens")]


class _Host:
    def __init__(self, checkout):
        self.checkout = checkout


def _writer(key_dir, api, *, cfg=None, runner=None):
    minter = T.GitHubAppTokenMinter(
        key_path=key_dir / "github-app.pem",
        config_path=cfg or (key_dir / "absent.json"),
        http=api,
        clock=lambda: 1_800_000_000,
    )
    return T.GitHubAppWriter(
        _Host(key_dir), None, minter=minter, status="ACTIVE", runner=runner or (lambda *a, **k: (0, ""))
    )


# ── the pinned App ───────────────────────────────────────────────────────────────────────────────


def test_the_operator_app_is_pinned_and_writes_stay_proposed():
    assert (T.APP_ID, T.APP_INSTALLATION_ID, T.APP_REPOSITORY) == (5419776, 173961421, "PatsKiller/tardeai")
    assert T.APP_KEY_PATH == Path.home() / ".config/tradeai/release_train/github-app.pem"
    assert T.GITHUB_WRITES_STATUS == "PROPOSED" and T.TRAIN_CONTROLLER_STATUS == "BUILD_ONLY"
    with pytest.raises(T.WriterNotArmed):
        T.GitHubAppWriter(_Host(Path("/nonexistent")), None)


def test_an_absent_config_mints_for_the_pinned_installation_with_the_app_id_as_issuer(key_dir):
    api = FakeApi()
    w = _writer(key_dir, api)
    with w.reservation("intent-1", "open_batch_pr"):
        assert w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b") == 77
    ((method, url, headers, body),) = api.mints()
    assert url == f"https://api.github.com/app/installations/{T.APP_INSTALLATION_ID}/access_tokens"
    claims = headers["Authorization"].split(" ", 1)[1].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert claims["iss"] == str(T.APP_ID)
    assert json.loads(body)["repositories"] == ["tardeai"]


@pytest.mark.parametrize(
    "over",
    [{"app_id": 42}, {"installation_id": 7}, {"repository": "someone/else"}, {"repository": "PatsKiller/other"}],
)
def test_a_config_naming_another_app_installation_or_repo_is_refused_before_signing(key_dir, over):
    api = FakeApi()
    w = _writer(key_dir, api, cfg=_write_cfg(key_dir, **over))
    with pytest.raises(T.AppTokenError, match="pinned App"), w.reservation("intent-1", "open_batch_pr"):
        w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")
    assert api.calls == []


def test_a_matching_config_with_a_client_id_uses_it_as_issuer(key_dir):
    api = FakeApi()
    w = _writer(key_dir, api, cfg=_write_cfg(key_dir, client_id="Iv23.pinned"))
    with w.reservation("intent-1", "merge_batch_pr"):
        assert w.merge_batch_pr(77, "b" * 40, "m") == "c" * 40
    claims = api.mints()[0][2]["Authorization"].split(" ", 1)[1].split(".")[1]
    assert json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))["iss"] == "Iv23.pinned"


def test_a_world_readable_config_is_still_refused(key_dir):
    p = _write_cfg(key_dir)
    os.chmod(p, 0o644)
    w = _writer(key_dir, FakeApi(), cfg=p)
    with pytest.raises(T.AppTokenError, match="mode 600"), w.reservation("i", "open_batch_pr"):
        w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")


def test_the_default_key_path_is_never_opened_by_these_tests(key_dir, monkeypatch):
    opened = []
    real = T._read_private_file

    def spy(path, what):
        opened.append(Path(path))
        return real(path, what)

    monkeypatch.setattr(T, "_read_private_file", spy)
    w = _writer(key_dir, FakeApi())
    with w.reservation("i", "open_batch_pr"):
        w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")
    assert opened and T.APP_KEY_PATH not in opened and all(p.is_relative_to(key_dir) for p in opened)


# ── one token per reservation ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "call",
    [
        lambda w: w.push_train_ref(TRAIN, "a" * 40),
        lambda w: w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b"),
        lambda w: w.merge_batch_pr(77, "b" * 40, "m"),
    ],
)
def test_a_write_outside_a_reservation_is_refused_and_mints_nothing(key_dir, call):
    api = FakeApi()
    w = _writer(key_dir, api)
    with pytest.raises(PermissionError, match="outside a capability reservation"):
        call(w)
    assert api.calls == []


def test_a_write_for_another_action_inside_a_reservation_is_refused(key_dir):
    api = FakeApi()
    w = _writer(key_dir, api)
    with w.reservation("intent-push", "push_train_ref"):
        with pytest.raises(PermissionError, match="inside a reservation for push_train_ref"):
            w.merge_batch_pr(77, "b" * 40, "m")
    assert api.calls == []


@pytest.mark.parametrize("intent,action", [("", "push_train_ref"), ("i", "prepare_release"), ("i", "promote")])
def test_a_reservation_needs_an_intent_and_a_writer_action(key_dir, intent, action):
    w = _writer(key_dir, FakeApi())
    with pytest.raises(PermissionError, match="refused"):
        with w.reservation(intent, action):
            pass


def test_a_nested_reservation_is_refused(key_dir):
    w = _writer(key_dir, FakeApi())
    with w.reservation("a", "push_train_ref"):
        with pytest.raises(PermissionError, match="already held"):
            with w.reservation("b", "merge_batch_pr"):
                pass
    assert w._bound is None


def test_one_mint_per_reservation_and_the_token_dies_with_it(key_dir):
    api = FakeApi()
    w = _writer(key_dir, api)
    with w.reservation("intent-open-1", "open_batch_pr"):
        w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")
        w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")  # same reservation: no second mint
        assert w._bound["token"] is not None
    assert w._bound is None
    assert len(api.mints()) == 1
    with w.reservation("intent-open-2", "open_batch_pr"):
        w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")
    assert len(api.mints()) == 2  # never cached across reservations
    assert [a["reservation"] for a in w.minter.audit] == ["intent-open-1", "intent-open-2"]
    assert TOKEN not in json.dumps(w.minter.audit)


def test_an_exception_inside_the_reservation_still_drops_the_token(key_dir):
    w = _writer(key_dir, FakeApi(), runner=lambda *a, **k: (1, "denied"))
    with pytest.raises(RuntimeError), w.reservation("i", "push_train_ref"):
        w.push_train_ref(TRAIN, "a" * 40)
    assert w._bound is None


# ── GH_TOKEN only in the writer's children ───────────────────────────────────────────────────────


def test_the_push_child_gets_gh_token_and_never_the_host_users_token(key_dir, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", HOST_TOKEN)
    monkeypatch.setenv("GITHUB_TOKEN", HOST_TOKEN)
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", HOST_TOKEN)
    before = dict(os.environ)
    seen = {}

    def runner(argv, *, env, timeout):
        seen.update(argv=list(argv), env=dict(env))
        return 0, ""

    w = _writer(key_dir, FakeApi(), runner=runner)
    with w.reservation("intent-push", "push_train_ref"):
        w.push_train_ref(TRAIN, "a" * 40)
    env = seen["env"]
    assert env["GH_TOKEN"] == TOKEN
    assert "GITHUB_TOKEN" not in env and "GH_ENTERPRISE_TOKEN" not in env
    assert HOST_TOKEN not in json.dumps(env)
    assert TOKEN not in " ".join(seen["argv"])
    assert dict(os.environ) == before and os.environ["GH_TOKEN"] == HOST_TOKEN  # the parent is untouched


def test_child_env_is_a_copy_and_strips_inherited_git_config():
    tok = T.AppToken(TOKEN, "2026-10-22T23:00:00Z", {})
    base = {"PATH": "/usr/bin", "GITHUB_TOKEN": HOST_TOKEN, "GIT_CONFIG_COUNT": "9", "GIT_CONFIG_KEY_0": "x"}
    env = T.GitHubAppWriter.child_env(tok, base)
    assert env == {"PATH": "/usr/bin", "GH_TOKEN": TOKEN}
    assert base["GITHUB_TOKEN"] == HOST_TOKEN  # input not mutated


def test_the_api_calls_carry_the_token_only_in_the_request_header(key_dir, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    api = FakeApi()
    w = _writer(key_dir, api)
    with w.reservation("intent-merge", "merge_batch_pr"):
        w.merge_batch_pr(77, "b" * 40, "m")
    put = [c for c in api.calls if c[0] == "PUT"][0]
    assert put[2]["Authorization"] == f"token {TOKEN}" and TOKEN not in put[1] and TOKEN.encode() not in put[3]
    assert "GH_TOKEN" not in os.environ


# ── the controller enters the reservation ────────────────────────────────────────────────────────


class _Res:
    def __init__(self, intent_id):
        self.intent_id, self.done, self.ended = intent_id, False, None

    def recheck(self, observed):
        return None

    def succeeded(self, detail):
        self.done, self.ended = True, "SUCCEEDED"

    def failed_no_effect(self, detail):
        self.done, self.ended = True, "FAILED_NO_EFFECT"

    def uncertain(self, detail):
        self.done, self.ended = True, "UNCERTAIN"

    def _end(self, state, detail, refund=False):
        self.done, self.ended = True, state


class _Authority:
    def __init__(self):
        self.reserved: list[tuple] = []

    def reserve(self, token, action, observed=None):
        self.reserved.append((token, action))
        return _Res(f"intent-{action}-{len(self.reserved)}")


class _Ctl:
    """Just the attributes ``TrainController._cap_effect`` touches."""

    def __init__(self, writer):
        self.writer, self.authority, self.effects = writer, _Authority(), []

    def _intent(self, action, detail):
        return f"key-{action}"

    def _update_intent(self, key, **kw):
        pass

    def _effect(self, key, state, detail):
        self.effects.append((key, state))


def test_cap_effect_binds_the_writer_to_the_reservation_it_just_made(key_dir):
    api = FakeApi()
    w = _writer(key_dir, api)
    ctl = _Ctl(w)
    seen = {}

    def effect():
        seen["bound"] = dict(w._bound)
        return w.open_or_update_batch_pr(TRAIN, "a" * 40, "t", "b")

    out = T.TrainController._cap_effect(ctl, lambda: "cap", "open_batch_pr", lambda: {}, effect, label="open")
    assert out == 77
    assert seen["bound"]["intent_id"] == "intent-open_batch_pr-1" and seen["bound"]["action"] == "open_batch_pr"
    assert w._bound is None and ctl.effects == [("key-open_batch_pr", "SUCCEEDED")]
    assert w.minter.audit[0]["reservation"] == "intent-open_batch_pr-1"


def test_cap_effect_does_not_bind_the_writer_for_a_non_writer_action(key_dir):
    w = _writer(key_dir, FakeApi())
    ctl = _Ctl(w)
    seen = {}
    T.TrainController._cap_effect(
        ctl, lambda: "cap", "prepare_release", lambda: {}, lambda: seen.setdefault("b", w._bound), label="prepare"
    )
    assert seen["b"] is None


def test_cap_effect_still_works_with_a_writer_that_has_no_reservation():
    class Plain:
        simulated = False

    ctl = _Ctl(Plain())
    assert (
        T.TrainController._cap_effect(ctl, lambda: "c", "push_train_ref", lambda: {}, lambda: "ok", label="x") == "ok"
    )


def test_a_refused_write_inside_cap_effect_is_uncertain_not_silent(key_dir):
    """A writer refusal raised during the effect is recorded (never swallowed); the reservation is not left held."""
    w = _writer(key_dir, FakeApi())
    ctl = _Ctl(w)
    with pytest.raises(T.Halt):
        T.TrainController._cap_effect(
            ctl, lambda: "c", "push_train_ref", lambda: {}, lambda: w.merge_batch_pr(1, "b" * 40, "m"), label="x"
        )
    assert w._bound is None and ctl.effects[-1][1] == "UNCERTAIN"


# ── docs and registration ────────────────────────────────────────────────────────────────────────


def test_packet_and_app_doc_record_the_reservation_binding():
    packet = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    assert "RELEASE_TRAIN_APP_TOKEN_RESERVATION_20261022" in packet
    doc = (ROOT / "docs/ops/RELEASE_TRAIN_GITHUB_APP.md").read_text(encoding="utf-8")
    assert "5419776" in doc and "173961421" in doc and "GH_TOKEN" in doc


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_app_token_reservation_20261022.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_APP_TOKEN_RESERVATION_20261022"
    assert doc["files"] == ["tests/test_release_train_app_token_reservation_20261022.py"]
