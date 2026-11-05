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
* step 03 applies the reviewed FW-P2 diff (not a new one) and the candidate names n8n_app with the password by file;
* review 2026-10-28: 01 records `ok` and moves its pointer only on a good dump, 02 requires `ok` and the dump's
  sha256; 03 reverts automatically (backup back, recreate) when `compose up` or /healthz fails, writes a failure
  receipt and prints the 09 command; 03 checks the password file is readable by the container's uid; 09 picks the
  backup by the stamp in its name and is a no-op when already rolled back.
"""

from __future__ import annotations

import hashlib
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
GRANT = "cw-test svc-test db-test"


def _text(name: str) -> str:
    return (PACKET / name).read_text(encoding="utf-8")


def _code_lines(name: str) -> list[str]:
    """Lines that are not pure comments (heredoc SQL and python bodies included)."""
    return [ln for ln in _text(name).splitlines() if not ln.lstrip().startswith("#")]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


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
    for setting in (
        "SET log_statement = 'none';",
        "SET log_min_error_statement = 'panic';",
        "SET log_min_duration_statement = -1;",
    ):
        assert setting in lib, setting
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
    # 02 closes the other databases to PUBLIC; 09 --also-role gives them back
    assert "REVOKE CONNECT, TEMPORARY ON DATABASE $d FROM PUBLIC;" in _text("02_create_app_role.sh")
    assert "GRANT CONNECT, TEMPORARY ON DATABASE $d TO PUBLIC;" in _text("09_rollback.sh")


def test_step_05_does_not_try_to_demote_the_bootstrap_superuser():
    text = _text("05_close_superuser_login.sh")
    code = "\n".join(_code_lines("05_close_superuser_login.sh"))
    assert "NOSUPERUSER" not in code  # PG16 refuses it for the bootstrap role; the README says why
    assert "ALTER ROLE $BOOTSTRAP_ROLE PASSWORD NULL;" in code
    assert "must have the SUPERUSER attribute" in text  # the PG16 refusal, quoted
    assert "--rollback" in text and "restore_bootstrap_password" in code
    assert "restore_bootstrap_password" in "\n".join(_code_lines("09_rollback.sh"))


def test_step_03_reverts_through_an_exit_trap_and_09_picks_by_name():
    t03 = "\n".join(_code_lines("03_switch_compose.sh"))
    assert "trap revert_on_failure EXIT" in t03 and "switch_compose_failed.json" in t03
    assert "09_rollback.sh --apply" in t03
    assert 'BAK="$(newest_by_name ' in "\n".join(_code_lines("09_rollback.sh"))


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
        "uid 1000",
        "N8N_APP_ROLE_GRANT=<db-write id> bash 05_close_superuser_login.sh --apply",
        'N8N_APP_ROLE_GRANT="<config-write id> <service id>" bash 09_rollback.sh --apply',
        "no database change",
        "takes no new backup",
    ):
        assert needle in text, needle
    assert "a fresh database backup is taken first" not in text.lower()


# ── behavioural: a fake docker / curl ───────────────────────────────────────────────────────────────────────────────

FAKE_DOCKER = r"""#!PYTHON
import json, os, re, shutil, sys
argv = sys.argv[1:]
d = os.environ["FAKE_DIR"]
live = os.environ["FAKE_LIVE_COMPOSE"]
stdin = ""
if argv[:1] == ["exec"] and "-i" in argv[:4]:
    stdin = sys.stdin.buffer.read().decode("utf-8", "replace")
state = os.environ.get("FAKE_STATE", "before")
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "stdin": stdin[:4000]}) + "\n")
def counter(name, bump=False):
    p = os.path.join(d, name)
    n = int(open(p).read()) if os.path.exists(p) else 0
    if bump:
        n += 1
        open(p, "w").write(str(n))
    return n
def container_compose():
    # what the container was last created from: the snapshot of the last successful `up`, else the live file
    p = os.path.join(d, "container.yml")
    try:
        return open(p if os.path.exists(p) else live).read()
    except OSError:
        return ""
on_app = "DB_POSTGRESDB_USER: n8n_app" in container_compose()
fmt = argv[argv.index("--format") + 1] if "--format" in argv else ""
def out(s, rc=0):
    sys.stdout.write(s + ("\n" if s else ""))
    sys.exit(rc)
if argv[:1] == ["inspect"]:
    m = re.search(r'"([A-Z_]+)"\}\}set', fmt)
    if m:
        sets = {"DB_POSTGRESDB_PASSWORD_FILE", "POSTGRES_PASSWORD"} if on_app else {"DB_POSTGRESDB_PASSWORD", "POSTGRES_PASSWORD"}
        out("set" if m.group(1) in sets else "")
    if "DB_POSTGRESDB_USER" in fmt:
        out("DB_POSTGRESDB_USER=" + ("n8n_app" if on_app else "n8n"))
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
if argv[:1] == ["logs"]:
    out("n8n container log line (fake)")
if argv[:1] == ["compose"]:
    if "up" in argv:
        n = counter("up_count", bump=True)
        if str(n) in os.environ.get("FAKE_UP_FAIL", "").split(","):
            out("Error response from daemon: fake up failure", rc=1)
        shutil.copy(live, os.path.join(d, "container.yml"))
        counter("up_ok_count", bump=True)
    out("")
if argv[:1] == ["exec"]:
    if "id" in argv and "-u" in argv:
        out(os.environ.get("FAKE_CONTAINER_UID", "1000"))
    if "pg_dump" in argv:
        out("PGDMP fake custom-format dump")
    if "pg_dumpall" in argv:
        out("CREATE ROLE n8n;\nALTER ROLE n8n WITH SUPERUSER LOGIN;")
    if "pg_restore" in argv:
        toc = {"good": "215; 0 16390 TABLE DATA public workflow_entity n8n\n216; 0 16400 TABLE DATA public execution_entity n8n",
               "empty": ""}[os.environ.get("FAKE_TOC", "good")]
        out(toc)
    if "sh" in argv and "-c" in argv and "LOGIN_OK" in " ".join(argv):
        out("LOGIN_OK")
    if "'role_exists'" in stdin:
        out(json.dumps({"role_exists": False, "role": None, "role_memberships": [], "admin_rolsuper": True,
                        "owners": {"n8n:r": 157}, "functions": {"n8n:own": 2}, "not_owned_by_role": 157,
                        "functions_not_owned_by_role": 2, "db_connect": None, "schema_create": None,
                        "extensions": ["plpgsql", "uuid-ossp"], "password_encryption": "scram-sha-256",
                        "server_version": "16.15"}))
    m = re.search(r"-- q:(\w+)", stdin)
    after02 = state in ("after02", "after")
    canned = {
        "active_workflows": "tradeai-dispatcher\ntradeai-event-router",
        "role_rows": "n8n|t|t|t|t|t|t" + ("\nn8n_app|f|f|f|f|f|t" if after02 else ""),
        "owners": "n8n_app:r|157" if after02 else "n8n:r|157",
        "migrations": "120|1760000000000",
        "extensions": "plpgsql,uuid-ossp",
        "hba": "1|local|all|all||trust",
        "sessions": "n8n_app|172.19.0.3|2" if on_app else "n8n|172.19.0.3|2",
        "public_tables": "157",
        "workflow_count": "18",
        "db_size": "39 MB",
        "bootstrap_password_null": "f",
        "connect_role": "f|f|f|f|f" if on_app else "t|t|t|t|t",
        "app_role": "f|t" if after02 else "",
        "app_connect_dbs": os.environ.get("FAKE_APP_CONNECT_DBS", "n8n" if after02 else ""),
        "db_acls": "n8n|(default: PUBLIC=Tc)\npostgres|(default: PUBLIC=Tc)\ntemplate1|(default: PUBLIC=Tc)",
    }
    out(canned.get(m.group(1), "") if m else "")
sys.exit(0)
"""

FAKE_CURL = r"""#!PYTHON
import os, sys
p = os.path.join(os.environ["FAKE_DIR"], "up_ok_count")
n = open(p).read().strip() if os.path.exists(p) else "0"
if n in os.environ.get("FAKE_HEALTH_DOWN_AFTER_UP", "").split(","):
    sys.exit(22)
print('{"status":"ok"}')
"""

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
    fake = tmp_path / "fake"
    for d in (home, lab, backups, bindir, fake):
        d.mkdir(parents=True)
    for name, src in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        (bindir / name).write_text(src.replace("#!PYTHON", "#!" + sys.executable), encoding="utf-8")
        (bindir / name).chmod(0o755)
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
        "N8N_HEALTHZ_WAIT": "0",
        "N8N_RELAY_WAIT": "0",
        "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
        "FAKE_DIR": str(fake),
        "FAKE_LIVE_COMPOSE": str(live),
        "FAKE_CONTAINER_UID": str(os.getuid()),
        "FAKE_STATE": "before",
    }
    return {
        "env": e,
        "tmp": tmp_path,
        "home": home,
        "lab": lab,
        "live": live,
        "log": tmp_path / "docker.log",
        "ev": tmp_path / "evidence",
        "backups": backups,
    }


def _run(env, name, *args, **extra):
    e = {**env["env"], **extra}
    return subprocess.run(["bash", str(PACKET / name), *args], env=e, capture_output=True, text=True, timeout=120)


def _calls(env):
    if not env["log"].exists():
        return []
    return [json.loads(x) for x in env["log"].read_text(encoding="utf-8").splitlines() if x.strip()]


def _ups(env):
    return [c for c in _calls(env) if c["argv"][:1] == ["compose"] and "up" in c["argv"]]


def _assert_no_mutation(env, before_sha):
    for c in _calls(env):
        argv = c["argv"]
        assert not any(MUTATING_DOCKER.match(a) for a in argv[:8] if not a.startswith("-")), argv
        assert not any(a in ("pg_dump", "pg_dumpall") for a in argv), argv
        assert not WRITE_SQL.search(c["stdin"]), c["stdin"]
        if argv[:1] == ["exec"] and "psql" in argv and "sh" not in argv:
            assert "PGOPTIONS=-c default_transaction_read_only=on" in argv, argv
    assert _sha(env["live"]) == before_sha
    assert not (env["home"] / ".config" / "tradeai" / "n8n" / "n8n_app_pg_password").exists()
    assert not list(env["lab"].glob("*.rolledback-*"))


def _after_step_02(env, *, uid=None):
    """State after a good step 02: n8n_app exists, a mode-600 password file, and a FW-P2 diff copy whose secret path
    is that file (the reviewed diff names the host path)."""
    env["env"]["FAKE_STATE"] = "after02"
    pw = env["home"] / ".config" / "tradeai" / "n8n" / "n8n_app_pg_password"
    pw.parent.mkdir(parents=True, mode=0o700)
    pw.write_text("not-a-real-password-just-43-characters-long", encoding="ascii")
    pw.chmod(0o600)
    diff = re.sub(r"(file: )\S+n8n_app_pg_password", lambda m: m.group(1) + str(pw), FW_P2_DIFF.read_text())
    copy = env["tmp"] / "fw-p2.diff"
    copy.write_text(diff, encoding="utf-8")
    env["env"].update(
        {
            "N8N_APP_PASSWORD_FILE": str(pw),
            "N8N_APP_ROLE_COMPOSE_DIFF": str(copy),
            "N8N_APP_ROLE_GRANT": GRANT,
            "FAKE_CONTAINER_UID": str(os.getuid() if uid is None else uid),
        }
    )
    r = _run(env, "00_preflight.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    return pw


# dry runs ───────────────────────────────────────────────────────────────────────────────────────────────────────────


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
    assert not list(env["lab"].glob("*.bak-*"))


def test_preflight_snapshots_active_workflows_and_records_the_finding(env):
    r = _run(env, "00_preflight.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "n8n connects as n8n, rolsuper=t" in r.stdout
    assert "PREFLIGHT OK" in r.stdout
    latest = (env["ev"] / "LATEST_PREFLIGHT").read_text().strip()
    assert (env["ev"] / latest / "active_workflows.txt").read_text() == "tradeai-dispatcher\ntradeai-event-router\n"
    receipt = json.loads((env["ev"] / latest / "preflight.json").read_text())
    assert receipt["connect_rolsuper"] == "t" and receipt["problems"] == "0"


def test_step_03_dry_run_builds_the_fw_p2_candidate_and_leaves_the_live_file(env):
    before = _sha(env["live"])
    r = _run(env, "03_switch_compose.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    cand = next(env["ev"].glob("*-switch-compose/candidate/docker-compose.n8n.yml")).read_text()
    assert "DB_POSTGRESDB_USER: n8n_app" in cand
    assert "DB_POSTGRESDB_PASSWORD_FILE: /run/secrets/n8n_app_pg_password" in cand
    assert not re.search(r"^\s+DB_POSTGRESDB_PASSWORD:", cand, re.M)
    assert "+      DB_POSTGRESDB_USER: n8n_app" in r.stdout and "DRY RUN" in r.stdout
    assert any(c["argv"][-2:] == ["config", "--quiet"] for c in _calls(env))
    assert _sha(env["live"]) == before


def test_step_02_dry_run_shows_the_public_revoke(env):
    r = _run(env, "02_create_app_role.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REVOKE CONNECT, TEMPORARY ON DATABASE postgres FROM PUBLIC;" in r.stdout
    assert "REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC;" in r.stdout


# grant gate ─────────────────────────────────────────────────────────────────────────────────────────────────────────


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
    assert _ups(env) == []


# step 01 / 02: backup receipt ───────────────────────────────────────────────────────────────────────────────────────


def test_backup_records_ok_and_moves_the_pointer_only_when_good(env):
    r = _run(env, "01_backup.sh", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    latest = (env["ev"] / "LATEST_BACKUP").read_text().strip()
    receipt = json.loads((env["ev"] / latest / "backup.json").read_text())
    assert receipt["ok"] == "true" and receipt["toc_has_workflow_entity"] == "1"
    dump = Path(receipt["dump"])
    assert dump.parent == env["backups"] and stat.S_IMODE(dump.stat().st_mode) == 0o600
    assert receipt["sha256"] == _sha(dump)
    manifest = json.loads(Path(receipt["manifest"]).read_text())
    assert manifest["ok"] == "true"


def test_suspect_backup_keeps_the_pointer_and_02_requires_ok(env):
    r = _run(env, "01_backup.sh", "--apply", FAKE_TOC="empty")
    assert r.returncode == 1 and "BACKUP SUSPECT" in r.stdout, r.stdout + r.stderr
    assert not (env["ev"] / "LATEST_BACKUP").exists()
    suspect = next(env["ev"].glob("*-backup/backup.json"))
    assert json.loads(suspect.read_text())["ok"] == "false"
    # even if a pointer named the suspect receipt, 02 refuses it before any role change
    assert _run(env, "00_preflight.sh").returncode == 0
    (env["ev"] / "LATEST_BACKUP").write_text(suspect.parent.name + "\n")
    r = _run(env, "02_create_app_role.sh", "--apply", "--ignore-window", N8N_APP_ROLE_GRANT=GRANT)
    assert r.returncode == 2 and "not ok:true" in r.stderr, r.stdout + r.stderr
    assert not (env["home"] / ".config" / "tradeai" / "n8n" / "n8n_app_pg_password").exists()


def test_02_refuses_when_the_dump_no_longer_matches_its_receipt(env):
    assert _run(env, "00_preflight.sh").returncode == 0
    assert _run(env, "01_backup.sh", "--apply").returncode == 0
    latest = (env["ev"] / "LATEST_BACKUP").read_text().strip()
    dump = Path(json.loads((env["ev"] / latest / "backup.json").read_text())["dump"])
    with open(dump, "a", encoding="utf-8") as fh:
        fh.write("tampered\n")
    r = _run(env, "02_create_app_role.sh", "--apply", "--ignore-window", N8N_APP_ROLE_GRANT=GRANT)
    assert r.returncode == 2 and "sha256" in r.stderr, r.stdout + r.stderr


# step 03: apply, automatic revert, password-file uid ────────────────────────────────────────────────────────────────


def test_03_apply_switches_then_09_rolls_back_then_09_is_a_noop(env):
    _after_step_02(env)
    original = _sha(env["live"])
    r = _run(env, "03_switch_compose.sh", "--apply", "--ignore-window")
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1500:]
    assert "DB_POSTGRESDB_USER: n8n_app" in env["live"].read_text()
    (bak,) = env["lab"].glob("docker-compose.n8n.yml.bak-*-pre-n8n-app-role")
    assert _sha(bak) == original
    assert (env["ev"] / "LATEST_SWITCH").exists()
    assert "09_rollback.sh --apply" in r.stdout and len(_ups(env)) == 1
    receipt = json.loads(next(env["ev"].glob("*-switch-compose/switch_compose.json")).read_text())
    assert receipt["connects_as"] == "n8n_app" and receipt["healthz"] == "ok"

    env["env"]["FAKE_STATE"] = "after"
    r = _run(env, "09_rollback.sh", "--apply")
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1500:]
    assert re.search(r"connects_as=n8n$", r.stdout, re.M) and _sha(env["live"]) == original
    assert list(env["lab"].glob("docker-compose.n8n.yml.rolledback-*")) and bak.exists()
    assert len(_ups(env)) == 2

    r = _run(env, "09_rollback.sh", "--apply")
    assert r.returncode == 0 and "already rolled back" in r.stdout, r.stdout + r.stderr
    assert len(_ups(env)) == 2


def test_03_reverts_when_compose_up_fails(env):
    _after_step_02(env)
    original = _sha(env["live"])
    r = _run(env, "03_switch_compose.sh", "--apply", "--ignore-window", FAKE_UP_FAIL="1")
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-1500:]
    assert "REVERTED" in r.stdout and "09_rollback.sh --apply" in r.stdout
    assert _sha(env["live"]) == original
    failed = json.loads(next(env["ev"].glob("*-switch-compose/switch_compose_failed.json")).read_text())
    assert failed["failed_stage"] == "compose_up" and failed["revert_up"] == "ok"
    assert failed["revert_healthz"] == "ok" and failed["connects_as"] == "n8n"
    assert not (env["ev"] / "LATEST_SWITCH").exists()
    assert len(_ups(env)) == 2  # the failed one and the revert


def test_03_reverts_when_healthz_stays_down(env):
    _after_step_02(env)
    original = _sha(env["live"])
    r = _run(env, "03_switch_compose.sh", "--apply", "--ignore-window", FAKE_HEALTH_DOWN_AFTER_UP="1")
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-1500:]
    assert "REVERTED" in r.stdout and "09_rollback.sh --apply" in r.stdout
    assert _sha(env["live"]) == original
    failed = json.loads(next(env["ev"].glob("*-switch-compose/switch_compose_failed.json")).read_text())
    assert failed["failed_stage"] == "healthz" and failed["revert_healthz"] == "ok"
    assert failed["connects_as"] == "n8n"
    assert next(env["ev"].glob("*-switch-compose/n8n-container-log-tail.txt")).read_text().strip()
    assert "n8n container log line" not in r.stdout  # saved, not printed


def test_03_refuses_a_password_file_the_container_uid_cannot_read(env):
    _after_step_02(env, uid=os.getuid() + 1)
    before = _sha(env["live"])
    r = _run(env, "03_switch_compose.sh", "--apply", "--ignore-window")
    assert r.returncode == 2 and "NOT readable by container uid" in r.stderr, r.stdout + r.stderr
    assert _sha(env["live"]) == before and _ups(env) == []


def test_04_databases_check_reports_a_drill_database_and_fails_on_postgres(env):
    _after_step_02(env)
    assert _run(env, "03_switch_compose.sh", "--apply", "--ignore-window").returncode == 0
    env["env"]["FAKE_STATE"] = "after"
    r = _run(env, "04_verify.sh", "--wait", "0", FAKE_APP_CONNECT_DBS="n8n,n8n_drill_20261028010101")
    assert "PASS databases" in r.stdout and "note: n8n_app may also connect to n8n_drill_20261028010101" in r.stdout
    assert "PASS rolsuper" in r.stdout and "PASS container_env" in r.stdout
    r = _run(env, "04_verify.sh", "--wait", "0", FAKE_APP_CONNECT_DBS="n8n,postgres")
    assert "FAIL databases" in r.stdout and r.returncode == 1


# step 09: backup choice and the no-op ──────────────────────────────────────────────────────────────────────────────


def test_09_picks_the_backup_by_the_stamp_in_its_name_not_by_mtime(env):
    older = env["lab"] / "docker-compose.n8n.yml.bak-20261027T000000Z-pre-n8n-app-role"
    newer = env["lab"] / "docker-compose.n8n.yml.bak-20261028T000000Z-pre-n8n-app-role"
    shutil.copy(env["live"], older)
    shutil.copy(env["live"], newer)
    os.utime(newer, (1_000_000_000, 1_000_000_000))  # `cp -p` keeps an old source time
    env["live"].write_text(
        env["live"].read_text().replace("DB_POSTGRESDB_USER: n8n\n", "DB_POSTGRESDB_USER: n8n_app\n")
    )
    r = _run(env, "09_rollback.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"restore source (newest by the <UTC> in its name): {newer}" in r.stdout


def test_09_is_a_noop_when_already_rolled_back(env):
    shutil.copy(env["live"], env["lab"] / "docker-compose.n8n.yml.bak-20261027T000000Z-pre-n8n-app-role")
    before = _sha(env["live"])
    r = _run(env, "09_rollback.sh", "--apply", N8N_APP_ROLE_GRANT=GRANT)
    assert r.returncode == 0 and "already rolled back" in r.stdout, r.stdout + r.stderr
    assert _sha(env["live"]) == before and _ups(env) == []
