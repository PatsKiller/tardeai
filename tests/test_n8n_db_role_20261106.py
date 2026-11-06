"""n8n program 0.1e (2026-11-06): n8n runs on a least-privilege database role.

ANCHOR: N8N_DB_ROLE_20261106

Hermetic: docker is a fake runner; nothing is started, no network, no database.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))

import n8n_db_role as role  # noqa: E402

PW = "A" * 20 + "b-c_d" * 4  # 40 chars of the token alphabet; synthetic
H = "a" * 64


def _write(p: Path, text: str, mode: int = 0o600) -> Path:
    p.write_text(text, encoding="utf-8")
    os.chmod(p, mode)
    return p


# ---- SQL and the secret ------------------------------------------------------------------------------------------


def test_scram_verifier_matches_rfc7677_derivation():
    salt = bytes(range(16))
    v = role.scram_verifier(PW, salt=salt)
    assert role.VERIFIER_RE.fullmatch(v)
    head, keys = v.split("$", 1)[1].split("$")
    assert head == "4096:" + base64.b64encode(salt).decode()
    salted = hashlib.pbkdf2_hmac("sha256", PW.encode(), salt, 4096)
    stored = hashlib.sha256(hmac.new(salted, b"Client Key", hashlib.sha256).digest()).digest()
    assert keys.split(":")[0] == base64.b64encode(stored).decode()


def test_apply_sql_never_takes_a_plaintext_password():
    with pytest.raises(ValueError):
        role.apply_sql(PW)
    sql = role.apply_sql(role.scram_verifier(PW))
    assert PW not in sql
    for attr in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS", "LOGIN"):
        assert attr in sql
    assert "REVOKE ALL ON DATABASE postgres, template1 FROM PUBLIC" in sql
    assert "GRANT CONNECT, TEMPORARY ON DATABASE n8n TO n8n_app" in sql
    assert "OWNER TO n8n_app" in sql and "relowner = 'n8n'::regrole" in sql
    assert "deptype = 'e'" in sql  # extension members (uuid-ossp) are left alone


def test_rollback_keeps_the_role_and_restores_public_grants():
    sql = role.rollback_sql()
    assert "DROP" not in sql.upper()
    assert "ALTER ROLE n8n_app NOLOGIN" in sql and "OWNER TO n8n'" in sql.replace("OWNER TO n8n',", "OWNER TO n8n'")
    assert "TO PUBLIC" in sql


def test_prepare_secret_writes_once_at_0600(tmp_path):
    p = tmp_path / "cfg" / "app.env"
    out = role.prepare_secret(p, token=lambda: PW)
    assert out["ok"] and out["written"] and PW not in json.dumps(out)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    again = role.prepare_secret(p, token=lambda: "Z" * 40)
    assert again["ok"] and not again["written"] and p.read_text() == f"N8N_APP_PG_PASSWORD={PW}\n"


def test_app_env_problems(tmp_path):
    assert role.app_env_problems(tmp_path / "x")[0].startswith("app env file missing")
    assert any("mode" in p for p in role.app_env_problems(_write(tmp_path / "a", f"N8N_APP_PG_PASSWORD={PW}\n", 0o644)))
    assert any("usable" in p for p in role.app_env_problems(_write(tmp_path / "b", "N8N_APP_PG_PASSWORD=short\n")))
    assert any("other keys" in p for p in role.app_env_problems(_write(tmp_path / "c", f"N8N_APP_PG_PASSWORD={PW}\nX=1\n")))
    assert role.app_env_problems(_write(tmp_path / "d", f"N8N_APP_PG_PASSWORD={PW}\n")) == []


def test_override_compose_only_changes_the_db_user():
    d = yaml.safe_load(role.OVERRIDE_COMPOSE.read_text(encoding="utf-8"))
    assert set(d["services"]) == {"n8n"} and set(d["services"]["n8n"]) == {"environment"}
    env = d["services"]["n8n"]["environment"]
    assert env["DB_POSTGRESDB_USER"] == "n8n_app"
    assert env["DB_POSTGRESDB_PASSWORD"].startswith("${N8N_APP_PG_PASSWORD:?")


# ---- steps against a fake docker ----------------------------------------------------------------------------------


class FakeDocker:
    def __init__(self, *, role_state=None, cutover=True, conns=("n8n",), active=("17", "17"), up_rc=0,
                 psql_fail=False, verify_ok=True):
        self.role_state = role_state
        self.cutover, self.conns, self.active, self.up_rc = cutover, list(conns), list(active), up_rc
        self.psql_fail, self.verify_ok = psql_fail, verify_ok
        self.calls: list[tuple[list[str], str | None]] = []

    def state(self):
        return {"app_role": self.role_state, "old_role_super": True,
                "owners": {"n8n_app" if self.role_state else "n8n": 182},
                "database_acl": {}, "n8n_connections": {c: 2 for c in self.conns}}

    def __call__(self, argv, stdin=None):
        argv = list(argv)
        self.calls.append((argv, stdin))
        ok = lambda out="": subprocess.CompletedProcess(argv, 0, out, "")  # noqa: E731
        if argv[:2] == ["docker", "inspect"]:
            return ok(str(role.cut.REPO_COMPOSE) if self.cutover else "/srv/old-lab/docker-compose.n8n.yml")
        if argv[:2] == ["docker", "exec"] and "-Atc" in argv:
            val = self.active.pop(0) if len(self.active) > 1 else self.active[0]
            return ok(f"{val}\n")
        if argv[:2] == ["docker", "exec"]:
            user = argv[argv.index("-U") + 1]
            db = argv[argv.index("-d") + 1]
            assert stdin is not None and stdin.startswith("\\set VERBOSITY terse\n")
            if user == "n8n_app":
                if "CREATE ROLE" in stdin or db == "postgres":
                    return subprocess.CompletedProcess(argv, 1, "", "ERROR:  permission denied" if self.verify_ok else "")
                return ok("f\n" if "rolsuper" in stdin else "17\n")
            if "json_build_object" in stdin:
                return ok(json.dumps(self.state()) + "\n")
            if self.psql_fail:
                return subprocess.CompletedProcess(argv, 3, "", "ERROR: boom PASSWORD 'SCRAM-SHA-256$4096:zz$yy:xx'")
            if "OWNER TO n8n_app" in stdin:
                self.role_state = {"login": True, "super": False, "createrole": False, "createdb": False,
                                   "replication": False, "bypassrls": False}
            return ok()
        if argv[:2] == ["docker", "compose"] and "up" in argv:
            if self.up_rc == 0:
                self.conns = ["n8n_app"] if str(role.OVERRIDE_COMPOSE) in argv else ["n8n"]
            return subprocess.CompletedProcess(argv, self.up_rc, "", "")
        raise AssertionError(f"unexpected call {argv}")

    def argvs(self):
        return [a for a, _ in self.calls]


READY = {"login": True, "super": False, "createrole": False, "createdb": False, "replication": False, "bypassrls": False}


@pytest.fixture
def envs(tmp_path):
    gw = ".".join(["198", "51", "100", "7"])  # synthetic TEST-NET-2, assembled so no address sits in git
    base = _write(tmp_path / "n8n.env", f"N8N_PG_PASSWORD=a\nN8N_ENCRYPTION_KEY=b\nN8N_RELAY_GATEWAY={gw}\n")
    app = _write(tmp_path / "app.env", f"N8N_APP_PG_PASSWORD={PW}\n")
    return base, app


def test_dry_run_is_read_only_and_redacts(envs):
    fd = FakeDocker()
    out = role.plan(*envs, fd)
    assert out["ok"] and out["cutover_done"] and not out["role_ready"] and not out["switched"]
    assert "<verifier>" in out["apply_sql_preview"] and "SCRAM-SHA-256$" not in out["apply_sql_preview"]
    assert not [a for a in fd.argvs() if "up" in a]
    assert all("OWNER TO" not in (s or "") for _, s in fd.calls)


def test_apply_db_sends_only_a_verifier_on_stdin(envs, tmp_path):
    fd = FakeDocker()
    out = role.apply_db(envs[1], tmp_path / "r.json", fd)
    assert out["ok"], out
    for argv, stdin in fd.calls:
        assert PW not in " ".join(argv) and PW not in (stdin or "")
    (tx,) = [(a, s) for a, s in fd.calls if s and "OWNER TO n8n_app" in s]
    assert "-1" in tx[0]
    assert PW not in (tmp_path / "r.json").read_text()


def test_apply_db_failure_redacts_the_verifier(envs, tmp_path):
    out = role.apply_db(envs[1], tmp_path / "r.json", FakeDocker(psql_fail=True))
    assert out["ok"] is False and "SCRAM-SHA-256$" not in json.dumps(out) and "<verifier>" in out["psql_stderr_tail"]


def test_switch_refuses_before_the_cutover(envs, tmp_path):
    fd = FakeDocker(role_state=READY, cutover=False)
    out = role.switch(*envs, tmp_path / "r.json", fd, healthy=lambda: True, settle=lambda: None)
    assert out["ok"] is False and any("0.1a" in w for w in out["refused"])
    assert not [a for a in fd.argvs() if "up" in a]


def test_switch_refuses_before_the_role_is_ready(envs, tmp_path):
    fd = FakeDocker()
    out = role.switch(*envs, tmp_path / "r.json", fd, healthy=lambda: True, settle=lambda: None)
    assert out["ok"] is False and any("--apply-db" in w for w in out["refused"])


def test_switch_layers_the_override_and_checks_connections(envs, tmp_path):
    fd = FakeDocker(role_state=READY)
    out = role.switch(*envs, tmp_path / "r.json", fd, healthy=lambda: True, settle=lambda: None)
    assert out["ok"], out
    (up,) = [a for a in fd.argvs() if "up" in a]
    assert up.count("-f") == 2 and str(role.OVERRIDE_COMPOSE) in up and up.count("--env-file") == 2
    assert up[-1] == "n8n" and "--no-deps" in up
    assert out["n8n_connections"] == {"n8n_app": 2}


def test_switch_fails_when_a_workflow_goes_inactive(envs, tmp_path):
    fd = FakeDocker(role_state=READY, active=("17", "17", "16"))
    out = role.switch(*envs, tmp_path / "r.json", fd, healthy=lambda: True, settle=lambda: None)
    assert out["ok"] is False and out["active_after"] == 16


def test_verify_needs_every_refusal():
    assert role.verify(FakeDocker())["ok"]
    bad = role.verify(FakeDocker(verify_ok=False))
    assert bad["ok"] is False and not bad["create_role_refused"]


def test_rollback_uses_the_base_compose_only(envs, tmp_path):
    fd = FakeDocker(role_state=READY, conns=("n8n_app",))
    out = role.rollback(envs[0], tmp_path / "r.json", fd, healthy=lambda: True, settle=lambda: None)
    assert out["ok"], out
    (up,) = [a for a in fd.argvs() if "up" in a]
    assert str(role.OVERRIDE_COMPOSE) not in up and up.count("--env-file") == 1
    assert any(s and "NOLOGIN" in s for _, s in fd.calls)


def test_this_file_is_registered_in_a_ci_gate():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib import ci_gates  # noqa: PLC0415 -- needs ROOT on sys.path first

    assert "tests/test_n8n_db_role_20261106.py" in ci_gates.registry_text(ROOT)
