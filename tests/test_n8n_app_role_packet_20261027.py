"""n8n_app least-privilege packet (ANCHOR N8N_APP_ROLE_PACKET_20261027): AGENTS.md §23.5 / §23.10 P13.

The operator packet docs/ops/packets/n8n-app-role-20261027/ moves the n8n container off the bootstrap superuser `n8n`
onto the non-superuser `n8n_app`. The operator runs it on the host; nothing here touches a host. This file proves,
hermetically (tmp HOME, a fake `docker` and `curl` on PATH, a compose file rebuilt from the committed 2026-10-22
proposal), that:

* every numbered script exists, is executable, is strict bash and parses (`bash -n`);
* every mutating script defaults to a dry run: with no --apply it runs no `docker compose up`/`down`/`restart`,
  no `pg_dump`, no writable SQL, leaves the compose file byte-identical and creates no password file; every psql
  it runs directly is a read-only transaction;
* --apply without the operator's grant id refuses (exit 2) before any mutation;
* the scripts contain no `down -v`, no DROP of a role/database/table, no `rm`, no literal password, no read of a
  `.env`, and never run `docker compose config` without --quiet (that prints interpolated secrets);
* step 03 applies the reviewed FW-P2 diff (not a new one) and the candidate names n8n_app with the password by file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs" / "ops" / "packets" / "n8n-app-role-20261027"
HARDENING = ROOT / "docs" / "ops" / "packets" / "n8n-platform-hardening-20261022" / "compose"
FW_P2_DIFF = HARDENING / "fw-p2-n8n-app-role.compose.diff.proposed"
SCRIPTS = [
    "00_preflight.sh",
    "01_backup.sh",
    "02_create_app_role.sh",
    "03_switch_compose.sh",
    "04_verify.sh",
    "05_close_superuser_login.sh",
    "09_rollback.sh",
]
MUTATING = [
    "01_backup.sh",
    "02_create_app_role.sh",
    "03_switch_compose.sh",
    "05_close_superuser_login.sh",
    "09_rollback.sh",
]
GRANT_GATED = ["02_create_app_role.sh", "03_switch_compose.sh", "05_close_superuser_login.sh", "09_rollback.sh"]
ALL_SH = [*SCRIPTS, "_lib.sh"]


def _text(name: str) -> str:
    return (PACKET / name).read_text(encoding="utf-8")


def _code_lines(name: str) -> list[str]:
    """Lines that are not pure comments (heredoc SQL and python bodies included)."""
    return [ln for ln in _text(name).splitlines() if not ln.lstrip().startswith("#")]


# ── static ──────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_exists_is_executable_strict_bash(name):
    p = PACKET / name
    assert p.is_file(), name
    assert p.stat().st_mode & stat.S_IXUSR, f"{name} is not executable"
    text = p.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n"), name
    assert "\nset -euo pipefail\n" in text, name
    assert 'source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"' in text, name


@pytest.mark.parametrize("name", ALL_SH)
def test_bash_parses(name):
    r = subprocess.run(["bash", "-n", str(PACKET / name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("name", MUTATING)
def test_mutating_scripts_default_to_dry_run(name):
    text = _text(name)
    assert re.search(r"^APPLY=0$", text, re.M), f"{name}: APPLY must default to 0"
    assert "--apply)" in text and "DRY RUN" in text, name


@pytest.mark.parametrize("name", ALL_SH)
def test_no_destructive_or_secret_patterns(name):
    text = _text(name)
    code = "\n".join(_code_lines(name))
    assert not re.search(r"\bdown\b", code), f"{name}: no docker compose down at all"
    assert not re.search(r"\s-v\b[^\n]*\bdown\b|\bdown\b[^\n]*(\s-v\b|--volumes)", text), name
    assert not re.search(r"\bDROP\s+(ROLE|OWNED|DATABASE|TABLE|SCHEMA|USER)\b", text, re.I), name
    assert not re.search(r"(^|[\s;&|(])rm\s", code, re.M), f"{name}: never delete (AGENTS §0 rule 6)"
    assert not re.search(r"\bPASSWORD\s+'[^':$<]", text), f"{name}: literal SQL password"
    assert not re.search(r"\b(PG|POSTGRES_|N8N_PG_|N8N_APP_)PASSWORD=[\"']?[^\"'$\s]", text), name
    assert not re.search(r"DB_POSTGRESDB_PASSWORD:[ \t]+[^\s$#'\"]", text), f"{name}: literal compose password"
    assert not re.search(r"(\bcat|\bsource|\bless|\bhead|\btail|\bgrep)\s[^\n]*\.env\b", code), f"{name}: no .env read"
    assert "--env-file" not in code, name
    for ln in _code_lines(name):
        if re.search(r"\bcompose\b.*\bconfig\b", ln):
            assert "--quiet" in ln, f"{name}: compose config without --quiet prints secrets: {ln.strip()}"


def test_secret_values_never_leave_the_db_container():
    lib = _text("_lib.sh")
    # the only POSTGRES_PASSWORD uses are inside single-quoted `sh -c` / heredoc text evaluated in the container
    assert "\\getenv pw POSTGRES_PASSWORD" in lib
    assert "SET log_min_error_statement = 'panic';" in lib and "SET log_statement = 'none';" in lib
    assert 'PGPASSWORD="$POSTGRES_PASSWORD"' in lib
    # container env values are read only for an allowlist of non-secret keys
    allow = re.search(r"case \"\$key\" in\n\s+(.+?)\) ;;", lib).group(1)
    assert "PASSWORD)" not in allow and "DB_POSTGRESDB_PASSWORD |" not in allow
    assert set(re.findall(r"[A-Z_]+", allow)) == {
        "DB_POSTGRESDB_USER",
        "DB_POSTGRESDB_PASSWORD_FILE",
        "DB_POSTGRESDB_DATABASE",
        "DB_POSTGRESDB_HOST",
    }


def test_step_02_reuses_the_rehearsed_role_script_and_step_03_the_reviewed_diff():
    assert (ROOT / "scripts" / "ops" / "n8n_db_app_role.py").is_file()
    lib = _text("_lib.sh")
    assert 'ROLE_SCRIPT="$REPO_ROOT/scripts/ops/n8n_db_app_role.py"' in lib
    assert "n8n-platform-hardening-20261022/compose/fw-p2-n8n-app-role.compose.diff.proposed" in lib
    diff = FW_P2_DIFF.read_text(encoding="utf-8")
    assert "+      DB_POSTGRESDB_USER: n8n_app" in diff
    assert "-      DB_POSTGRESDB_PASSWORD: ${N8N_PG_PASSWORD}" in diff
    assert "+      DB_POSTGRESDB_PASSWORD_FILE: /run/secrets/n8n_app_pg_password" in diff
    assert "up -d --no-deps" in _text("03_switch_compose.sh") and "up -d --no-deps" in _text("09_rollback.sh")


def test_step_05_does_not_try_to_demote_the_bootstrap_superuser():
    text = _text("05_close_superuser_login.sh")
    code = "\n".join(_code_lines("05_close_superuser_login.sh"))
    assert "NOSUPERUSER" not in code  # PG16 refuses it for the bootstrap role; the README says why
    assert "ALTER ROLE $BOOTSTRAP_ROLE PASSWORD NULL;" in code
    assert "must have the SUPERUSER attribute" in text  # the PG16 refusal, quoted
    assert "--rollback" in text and "restore_bootstrap_password" in code
    assert "restore_bootstrap_password" in "\n".join(_code_lines("09_rollback.sh"))


def test_readme_covers_steps_grants_window_verify_rollback():
    text = (PACKET / "README.md").read_text(encoding="utf-8")
    for name in SCRIPTS:
        assert name in text, name
    for needle in (
        "config-write",
        "service",
        "db-write",
        "hh:07",
        "hh:37",
        "P13",
        "rolsuper",
        "N8N_APP_ROLE_GRANT",
        "last resort",
        "What to record",
    ):
        assert needle in text, needle


# ── behavioural: dry runs against a fake docker ────────────────────────────────────────────────────────────────────

FAKE_DOCKER = r"""#!PYTHON
import json, os, re, sys
argv = sys.argv[1:]
stdin = ""
if "exec" in argv[:1] and "-i" in argv[:4]:
    stdin = sys.stdin.read()
state = os.environ.get("FAKE_STATE", "before")
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "stdin": stdin}) + "\n")
fmt = argv[argv.index("--format") + 1] if "--format" in argv else ""
def out(s):
    sys.stdout.write(s + ("\n" if s else ""))
    sys.exit(0)
if argv[:1] == ["inspect"]:
    m = re.search(r'"([A-Z_]+)"\}\}set', fmt)
    if m:
        key = m.group(1)
        sets = {"before": {"DB_POSTGRESDB_PASSWORD", "POSTGRES_PASSWORD"},
                "after": {"DB_POSTGRESDB_PASSWORD_FILE", "POSTGRES_PASSWORD"}}[state]
        out("set" if key in sets else "")
    if "DB_POSTGRESDB_USER" in fmt:
        out("DB_POSTGRESDB_USER=" + ("n8n" if state == "before" else "n8n_app"))
    if "Running" in fmt:
        out("true")
    if "com.docker.compose.project" in fmt:
        out("m8m-n8n")
    if fmt == "{{.Image}}":
        out("sha256:fake")
    if fmt == "{{.Config.Image}}":
        out("n8nio/n8n:2.43.0")
    out("")
if argv[:2] == ["volume", "inspect"]:
    out(argv[2])
if argv[:1] == ["exec"]:
    if "sh" in argv and "-c" in argv and "LOGIN_OK" in " ".join(argv):
        out("LOGIN_OK")
    if "'role_exists'" in stdin:
        out(json.dumps({"role_exists": False, "role": None, "role_memberships": [], "admin_rolsuper": True,
                        "owners": {"n8n:r": 157}, "functions": {"n8n:own": 2}, "not_owned_by_role": 157,
                        "functions_not_owned_by_role": 2, "db_connect": None, "schema_create": None,
                        "extensions": ["plpgsql", "uuid-ossp"], "password_encryption": "scram-sha-256",
                        "server_version": "16.15"}))
    m = re.search(r"-- q:(\w+)", stdin)
    canned = {
        "active_workflows": "tradeai-dispatcher\ntradeai-event-router",
        "role_rows": "n8n|t|t|t|t|t|t",
        "owners": "n8n:r|157",
        "migrations": "120|1760000000000",
        "extensions": "plpgsql,uuid-ossp",
        "hba": "1|local|all|all||trust",
        "sessions": "n8n|172.19.0.3|2",
        "public_tables": "157",
        "workflow_count": "18",
        "db_size": "39 MB",
        "bootstrap_password_null": "f",
        "connect_role": "t|t|t|t|t",
        "app_role": "",
    }
    out(canned.get(m.group(1), "") if m else "")
sys.exit(0)
"""

FAKE_CURL = '#!/bin/sh\nprintf \'{"status":"ok"}\\n\'\n'

MUTATING_DOCKER = re.compile(r"^(up|down|restart|stop|start|kill|rm|cp|pause|create|run)$")
WRITE_SQL = re.compile(
    r"^\s*(ALTER|CREATE|GRANT|REVOKE|REASSIGN|DROP|INSERT|UPDATE|DELETE|TRUNCATE|COPY)\b", re.I | re.M
)


@pytest.fixture
def env(tmp_path):
    if not shutil.which("patch"):
        pytest.skip("patch(1) not installed")
    home = tmp_path / "home"
    lab = home / "m8m-bakeoff-lab"
    backups = tmp_path / "backups"
    bindir = tmp_path / "bin"
    for d in (home, lab, backups, bindir):
        d.mkdir(parents=True)
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER.replace("#!PYTHON", "#!" + sys.executable), encoding="utf-8")
    docker.chmod(0o755)
    (bindir / "curl").write_text(FAKE_CURL, encoding="utf-8")
    (bindir / "curl").chmod(0o755)
    # the live compose file as it was before the 2026-10-22 patches: the proposal with the combined diff reversed
    live = lab / "docker-compose.n8n.yml"
    shutil.copy(HARDENING / "docker-compose.n8n.yml.proposed", live)
    with open(HARDENING / "fw-p1-p2-p5-combined.compose.diff.proposed", "rb") as fh:
        r = subprocess.run(["patch", "-R", "-p1", "-s", "-d", str(lab)], stdin=fh, capture_output=True)
    assert r.returncode == 0, r.stderr
    assert "DB_POSTGRESDB_USER: n8n\n" in live.read_text()
    relay = tmp_path / "relay_log.jsonl"
    at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    relay.write_text(json.dumps({"at": at, "op": "due", "state": "OK"}) + "\n", encoding="utf-8")
    e = {
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PY": sys.executable,
        "TRADE_AI_CI": "1",
        "N8N_BACKUP_DIR": str(backups),
        "TRADEAI_STATE_ROOT": str(tmp_path / "state"),
        "N8N_RELAY_LOG": str(relay),
        "N8N_APP_ROLE_EVIDENCE_DIR": str(tmp_path / "evidence"),
        "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
        "FAKE_STATE": "before",
    }
    return {"env": e, "tmp": tmp_path, "home": home, "lab": lab, "live": live, "log": tmp_path / "docker.log"}


def _run(env, name, *args):
    return subprocess.run(
        ["bash", str(PACKET / name), *args], env=env["env"], capture_output=True, text=True, timeout=120
    )


def _calls(env):
    if not env["log"].exists():
        return []
    return [json.loads(x) for x in env["log"].read_text(encoding="utf-8").splitlines() if x.strip()]


def _assert_no_mutation(env, before_sha):
    import hashlib

    for c in _calls(env):
        argv = c["argv"]
        assert not any(MUTATING_DOCKER.match(a) for a in argv[:8] if not a.startswith("-")), argv
        assert not any(a in ("pg_dump", "pg_dumpall") for a in argv), argv
        assert not WRITE_SQL.search(c["stdin"]), c["stdin"]
        if argv[:1] == ["exec"] and "psql" in argv and "sh" not in argv:
            assert "PGOPTIONS=-c default_transaction_read_only=on" in argv, argv
    assert hashlib.sha256(env["live"].read_bytes()).hexdigest() == before_sha
    assert not (env["home"] / ".config" / "tradeai" / "n8n" / "n8n_app_pg_password").exists()
    assert not list(env["lab"].glob("*.bak-*")) or env["env"]["FAKE_STATE"] == "after"
    assert not list(env["lab"].glob("*.rolledback-*"))


def _sha(p: Path) -> str:
    import hashlib

    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "name,args,codes",
    [
        ("00_preflight.sh", (), {0}),
        ("01_backup.sh", (), {0}),
        ("02_create_app_role.sh", (), {0}),
        ("03_switch_compose.sh", (), {0}),
        ("04_verify.sh", ("--wait", "0"), {1}),
        ("05_close_superuser_login.sh", (), {0}),
        ("05_close_superuser_login.sh", ("--rollback",), {0}),
        ("09_rollback.sh", (), {0}),
    ],
)
def test_dry_runs_change_nothing(env, name, args, codes):
    before = _sha(env["live"])
    r = _run(env, name, *args)
    assert r.returncode in codes, (r.returncode, r.stdout[-2000:], r.stderr[-2000:])
    _assert_no_mutation(env, before)
    assert "fake-" not in r.stdout + r.stderr


def test_preflight_snapshots_active_workflows_and_records_the_finding(env):
    r = _run(env, "00_preflight.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "n8n connects as n8n, rolsuper=t" in r.stdout
    assert "PREFLIGHT OK" in r.stdout
    ev = Path(env["env"]["N8N_APP_ROLE_EVIDENCE_DIR"])
    latest = (ev / "LATEST_PREFLIGHT").read_text().strip()
    assert (ev / latest / "active_workflows.txt").read_text() == "tradeai-dispatcher\ntradeai-event-router\n"
    receipt = json.loads((ev / latest / "preflight.json").read_text())
    assert receipt["connect_rolsuper"] == "t" and receipt["problems"] == "0"


def test_step_03_dry_run_builds_the_fw_p2_candidate_and_leaves_the_live_file(env):
    before = _sha(env["live"])
    r = _run(env, "03_switch_compose.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    ev = Path(env["env"]["N8N_APP_ROLE_EVIDENCE_DIR"])
    cand = next(ev.glob("*-switch-compose/candidate/docker-compose.n8n.yml")).read_text()
    assert "DB_POSTGRESDB_USER: n8n_app" in cand
    assert "DB_POSTGRESDB_PASSWORD_FILE: /run/secrets/n8n_app_pg_password" in cand
    assert not re.search(r"^\s+DB_POSTGRESDB_PASSWORD:", cand, re.M)
    assert "+      DB_POSTGRESDB_USER: n8n_app" in r.stdout and "DRY RUN" in r.stdout
    assert any(c["argv"][-2:] == ["config", "--quiet"] for c in _calls(env))
    assert _sha(env["live"]) == before


@pytest.mark.parametrize("name", GRANT_GATED)
def test_apply_without_grant_refuses_before_any_mutation(env, name):
    if name == "09_rollback.sh":  # give the rollback something to roll back: the post-03 state
        env["env"]["FAKE_STATE"] = "after"
        bak = env["lab"] / "docker-compose.n8n.yml.bak-20261027T000000Z-pre-n8n-app-role"
        shutil.copy(env["live"], bak)
        text = env["live"].read_text().replace("DB_POSTGRESDB_USER: n8n\n", "DB_POSTGRESDB_USER: n8n_app\n")
        env["live"].write_text(text)
    before = _sha(env["live"])
    r = _run(env, name, "--apply")
    assert r.returncode == 2, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
    assert "N8N_APP_ROLE_GRANT" in r.stderr
    _assert_no_mutation(env, before)


def test_unknown_arguments_are_refused(env):
    for name in MUTATING:
        r = _run(env, name, "--aply")
        assert r.returncode == 2 and "usage" in r.stderr, name
    assert _calls(env) == [] or all(c["argv"][:1] != ["compose"] for c in _calls(env))
