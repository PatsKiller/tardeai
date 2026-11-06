#!/usr/bin/env python3
"""Run n8n on a least-privilege database role (n8n program package 0.1e, 2026-11-06).

ANCHOR: N8N_DB_ROLE_20261106

n8n connects to its own Postgres (container ``m8m-n8n-db``) as ``n8n``, the container's bootstrap SUPERUSER: it can
create roles, read every database in the cluster and bypass row security. This tool moves n8n onto ``n8n_app``, a
LOGIN role with no SUPERUSER, CREATEROLE, CREATEDB, REPLICATION or BYPASSRLS, which owns n8n's objects in schema
``public`` (n8n runs its own migrations, so it must own its tables) and may connect only to database ``n8n``.

  (default)         dry run, read-only: role state, object owners, database grants, who n8n connects as, and the
                    SQL --apply-db would run (password redacted). Prints JSON.
  --prepare-secret  writes a fresh random N8N_APP_PG_PASSWORD to ~/.config/tradeai/n8n/n8n-app-role.env (O_EXCL,
                    0600, directory 0700). Never printed.
  --apply-db        one transaction: create/alter n8n_app, hand it n8n's objects in public, close CONNECT on the
                    other databases. n8n keeps running as before (the superuser can still use everything).
  --switch          recreates the n8n container from the base compose PLUS ops/n8n/docker-compose.n8n-app-role.yml
                    (DB user n8n_app), waits for /healthz, and fails unless the active-workflow count is unchanged and
                    n8n's connections are n8n_app. A restart: operator go-ahead, outside market hours, after the
                    0.1a cutover.
  --verify          as n8n_app over the container's local socket: not superuser, cannot create a role, cannot
                    connect to database postgres.
  --rollback        recreates n8n from the base compose only (back to the superuser), returns ownership to n8n,
                    reopens CONNECT, and sets n8n_app NOLOGIN (the role is kept, never dropped).

Secrets travel on psql's stdin, never in argv. No broker, no order path, no production database: MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import n8n_compose_cutover as cut  # noqa: E402 -- sibling module, needs the path above

OLD_ROLE = "n8n"  # the container's bootstrap superuser (POSTGRES_USER)
APP_ROLE = "n8n_app"
DATABASE = "n8n"
OTHER_DATABASES = ("postgres", "template1")
SECRET_KEY = "N8N_APP_PG_PASSWORD"
PASSWORD_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
OVERRIDE_COMPOSE = cut.ROOT / "ops" / "n8n" / "docker-compose.n8n-app-role.yml"
DEFAULT_APP_ENV = Path.home() / ".config" / "tradeai" / "n8n" / "n8n-app-role.env"
DB_CONTAINER = cut.SERVICES["n8n-db"]
N8N_CONTAINER = cut.SERVICES["n8n"]

Runner = Callable[..., subprocess.CompletedProcess]


def _run(argv: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), input=stdin, capture_output=True, text=True, timeout=180,  # noqa: S603 -- fixed argv list, no shell
                          check=False)


def _argv_only(run: Runner) -> Callable[[Sequence[str]], subprocess.CompletedProcess]:
    return lambda argv: run(argv)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- SQL --------------------------------------------------------------------------------------------------------


def _owner_loop(src: str, dst: str) -> str:
    """Hand every non-extension relation, function and free-standing type in ``public`` from ``src`` to ``dst``.

    Sequences owned by a table column move with their table (ALTER on them directly is an error), so only free
    sequences are altered on their own. Indexes and row types always follow their table.
    """
    return f"""DO $own$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.oid::regclass AS obj FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f')
             AND c.relowner = '{src}'::regrole
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e') LOOP
    EXECUTE format('ALTER TABLE %s OWNER TO {dst}', r.obj);
  END LOOP;
  FOR r IN SELECT c.oid::regclass AS obj FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind = 'S' AND c.relowner = '{src}'::regrole
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a','i','e')) LOOP
    EXECUTE format('ALTER SEQUENCE %s OWNER TO {dst}', r.obj);
  END LOOP;
  FOR r IN SELECT p.oid::regprocedure AS obj FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' AND p.proowner = '{src}'::regrole
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') LOOP
    EXECUTE format('ALTER ROUTINE %s OWNER TO {dst}', r.obj);
  END LOOP;
  FOR r IN SELECT t.oid::regtype AS obj FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
           WHERE n.nspname = 'public' AND t.typtype IN ('e','d') AND t.typowner = '{src}'::regrole
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = t.oid AND d.deptype = 'e') LOOP
    EXECUTE format('ALTER TYPE %s OWNER TO {dst}', r.obj);
  END LOOP;
END
$own$;
"""


VERIFIER_RE = re.compile(r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+")


def scram_verifier(password: str, salt: bytes | None = None, iterations: int = 4096) -> str:
    """The SCRAM-SHA-256 verifier Postgres stores (RFC 7677 / pg's scram_build_secret).

    Sending the verifier instead of the password keeps the plaintext out of psql's error echo and the server log.
    """
    if not PASSWORD_RE.fullmatch(password):
        raise ValueError(f"{SECRET_KEY} must match {PASSWORD_RE.pattern}")
    salt = salt if salt is not None else secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    stored = hashlib.sha256(hmac.new(salted, b"Client Key", hashlib.sha256).digest()).digest()
    server = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored)}:{b64(server)}"


def apply_sql(verifier: str) -> str:
    if not VERIFIER_RE.fullmatch(verifier):
        raise ValueError("apply_sql takes a SCRAM-SHA-256 verifier, never a plaintext password")
    attrs = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 40"
    others = ", ".join(OTHER_DATABASES)
    return f"""DO $role$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN CREATE ROLE {APP_ROLE}; END IF;
END $role$;
ALTER ROLE {APP_ROLE} {attrs} PASSWORD '{verifier}';
REVOKE ALL ON DATABASE {others} FROM PUBLIC;
REVOKE ALL ON DATABASE {DATABASE} FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE {DATABASE} TO {APP_ROLE};
GRANT USAGE, CREATE ON SCHEMA public TO {APP_ROLE};
{_owner_loop(OLD_ROLE, APP_ROLE)}"""


def rollback_sql() -> str:
    """Ownership back to the superuser, PUBLIC's default database grants back, n8n_app NOLOGIN (kept, never dropped)."""
    return f"""{_owner_loop(APP_ROLE, OLD_ROLE)}
GRANT CONNECT, TEMPORARY ON DATABASE {DATABASE}, postgres TO PUBLIC;
GRANT CONNECT ON DATABASE template1 TO PUBLIC;
REVOKE CREATE ON SCHEMA public FROM {APP_ROLE};
ALTER ROLE {APP_ROLE} NOLOGIN;
"""


STATE_SQL = f"""
SELECT json_build_object(
  'app_role', (SELECT json_build_object('login', rolcanlogin, 'super', rolsuper, 'createrole', rolcreaterole,
                 'createdb', rolcreatedb, 'replication', rolreplication, 'bypassrls', rolbypassrls)
               FROM pg_roles WHERE rolname = '{APP_ROLE}'),
  'old_role_super', (SELECT rolsuper FROM pg_roles WHERE rolname = '{OLD_ROLE}'),
  'owners', (SELECT json_object_agg(o, n) FROM (
               SELECT pg_get_userbyid(c.relowner) AS o, count(*) AS n FROM pg_class c
               JOIN pg_namespace s ON s.oid = c.relnamespace
               WHERE s.nspname = 'public' AND c.relkind IN ('r','p','S','v','m') GROUP BY 1) x),
  'database_acl', (SELECT json_object_agg(datname, COALESCE(datacl::text, 'default (PUBLIC may connect)'))
                   FROM pg_database WHERE datname IN ('{DATABASE}', 'postgres', 'template1')),
  'n8n_connections', (SELECT COALESCE(json_object_agg(u, n), '{{}}'::json) FROM (
               SELECT usename AS u, count(*) AS n FROM pg_stat_activity
               WHERE datname = '{DATABASE}' AND pid <> pg_backend_pid() GROUP BY 1) y)
);"""


def _psql(run: Runner, sql: str, user: str = OLD_ROLE, db: str = DATABASE, *, one_tx: bool = False):
    argv = ["docker", "exec", "-i", DB_CONTAINER, "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1",
            "-U", user, "-d", db, *(["-1"] if one_tx else []), "-f", "-"]
    return run(argv, stdin="\\set VERBOSITY terse\n" + sql)


def _redact(text: str | None) -> str:
    return re.sub(r"SCRAM-SHA-256\$[^\s']*", "<verifier>", text or "")


def db_state(run: Runner) -> dict | None:
    cp = _psql(run, STATE_SQL)
    try:
        return json.loads(cp.stdout.strip().splitlines()[-1]) if cp.returncode == 0 else None
    except (IndexError, ValueError):
        return None


# ---- the secret file --------------------------------------------------------------------------------------------


def app_env_problems(path: Path) -> list[str]:
    if not path.is_file():
        return [f"app env file missing: {path}"]
    probs = []
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        probs.append(f"app env file mode {oct(stat.S_IMODE(path.stat().st_mode))} is readable by others; need 0600")
    keys = cut._env_keys(path)  # noqa: SLF001 -- shared parser of the sibling tool
    if not PASSWORD_RE.fullmatch(keys.get(SECRET_KEY, "")):
        probs.append(f"app env file lacks a usable {SECRET_KEY}")
    extra = sorted(set(keys) - {SECRET_KEY})
    if extra:
        probs.append(f"app env file carries other keys: {', '.join(extra)}")
    return probs


def prepare_secret(path: Path, token: Callable[[], str] = lambda: secrets.token_urlsafe(32)) -> dict:
    if path.exists():
        probs = app_env_problems(path)
        return {"step": "prepare-secret", "ok": not probs, "written": False, "path": str(path),
                **({"problems": probs} if probs else {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"{SECRET_KEY}={token()}\n")
    return {"step": "prepare-secret", "ok": app_env_problems(path) == [], "written": True, "path": str(path)}


# ---- steps ------------------------------------------------------------------------------------------------------


def _cutover_done(run: Runner) -> bool:
    cp = run(["docker", "inspect", N8N_CONTAINER, "--format",
              '{{index .Config.Labels "com.docker.compose.project.config_files"}}'])
    return cp.returncode == 0 and str(cut.REPO_COMPOSE) in cp.stdout


def plan(base_env: Path, app_env: Path, run: Runner = _run) -> dict:
    res: dict = {"step": "dry-run", "measured_at": _now(), "app_env": str(app_env)}
    probs: list[str] = []
    state = db_state(run)
    res["db"] = state
    if state is None:
        probs.append(f"could not read role state from {DB_CONTAINER}")
    res["app_env_problems"] = app_env_problems(app_env)
    res["base_env_problems"] = cut.env_file_problems(base_env)
    res["cutover_done"] = _cutover_done(run)
    res["active_workflows"] = cut.active_workflows(_argv_only(run))
    res["apply_sql_preview"] = _redact(apply_sql(scram_verifier("x" * 32)))
    app = (state or {}).get("app_role") or {}
    res["role_ready"] = bool(app.get("login")) and not any(
        app.get(k) for k in ("super", "createrole", "createdb", "replication", "bypassrls"))
    res["switched"] = set(((state or {}).get("n8n_connections") or {})) == {APP_ROLE}
    res["problems"] = probs
    res["ok"] = not probs
    return res


def apply_db(app_env: Path, receipt: Path, run: Runner = _run) -> dict:
    probs = app_env_problems(app_env)
    if probs:
        return {"step": "apply-db", "ok": False, "refused": "; ".join(probs)}
    password = cut._env_keys(app_env)[SECRET_KEY]  # noqa: SLF001 -- shared parser of the sibling tool
    before = db_state(run)
    cp = _psql(run, apply_sql(scram_verifier(password)), one_tx=True)
    after = db_state(run)
    app = (after or {}).get("app_role") or {}
    ok = (cp.returncode == 0 and bool(app.get("login")) and not app.get("super")
          and set(((after or {}).get("owners") or {})) == {APP_ROLE})
    res = {"step": "apply-db", "ok": ok, "psql_rc": cp.returncode, "psql_stderr_tail": _redact(cp.stderr)[-400:],
           "before": before, "after": after, "finished_at": _now()}
    return _receipt(res, receipt)


def _compose(base_env: Path, app_env: Path | None, *rest: str) -> list[str]:
    argv = ["docker", "compose", "-p", cut.PROJECT, "-f", str(cut.REPO_COMPOSE)]
    if app_env is not None:
        argv += ["-f", str(OVERRIDE_COMPOSE)]
    argv += ["--env-file", str(base_env)]
    if app_env is not None:
        argv += ["--env-file", str(app_env)]
    return [*argv, *rest]


def _recreate(base_env: Path, app_env: Path | None, run: Runner, healthy: Callable[[], bool] | None,
              settle: Callable[[], None]) -> dict:
    before = cut.active_workflows(_argv_only(run))
    cp = run(_compose(base_env, app_env, "up", "-d", "--no-deps", "--force-recreate", "n8n"))
    is_up = cp.returncode == 0 and (healthy or (lambda: cut._healthy(180, time.sleep)))()  # noqa: SLF001 -- sibling ops module, same package 0.1a health probe
    if is_up:
        settle()
    after = cut.active_workflows(_argv_only(run)) if is_up else None
    state = db_state(run) if is_up else None
    return {"up_rc": cp.returncode, "up_stderr_tail": (cp.stderr or "")[-400:], "healthy": bool(is_up),
            "active_before": before, "active_after": after,
            "n8n_connections": (state or {}).get("n8n_connections"), "finished_at": _now()}


def switch(base_env: Path, app_env: Path, receipt: Path, run: Runner = _run,
           healthy: Callable[[], bool] | None = None, settle: Callable[[], None] = lambda: time.sleep(10)) -> dict:
    pre = plan(base_env, app_env, run)
    why = [*pre["problems"], *pre["app_env_problems"], *pre["base_env_problems"]]
    if not pre["cutover_done"]:
        why.append("the 0.1a cutover has not run: n8n was not started from the repo compose")
    if not pre["role_ready"]:
        why.append(f"{APP_ROLE} is not a least-privilege LOGIN role yet (run --apply-db)")
    if why:
        return {"step": "switch", "ok": False, "refused": why, "dry_run": pre}
    res = {"step": "switch", **_recreate(base_env, app_env, run, healthy, settle)}
    res["ok"] = (res["healthy"] and res["active_after"] == res["active_before"]
                 and set(res["n8n_connections"] or {}) == {APP_ROLE})
    return _receipt(res, receipt)


VERIFY_SQL = f"SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls FROM pg_roles WHERE rolname = '{APP_ROLE}';"


def verify(run: Runner = _run) -> dict:
    """Prove the limits as n8n_app itself (the container's local socket)."""
    privileged = _psql(run, VERIFY_SQL, user=APP_ROLE)
    create_role = _psql(run, "BEGIN; CREATE ROLE n8n_app_probe; ROLLBACK;", user=APP_ROLE)
    other_db = _psql(run, "SELECT 1;", user=APP_ROLE, db="postgres")
    own_db = _psql(run, "SELECT count(*) FROM workflow_entity;", user=APP_ROLE)
    res = {"step": "verify", "measured_at": _now(),
           "not_privileged": privileged.returncode == 0 and privileged.stdout.strip() == "f",
           "create_role_refused": create_role.returncode != 0 and "permission denied" in create_role.stderr,
           "other_database_refused": other_db.returncode != 0 and "permission denied" in other_db.stderr,
           "reads_own_tables": own_db.returncode == 0}
    res["ok"] = all(res[k] for k in ("not_privileged", "create_role_refused", "other_database_refused",
                                     "reads_own_tables"))
    return res


def rollback(base_env: Path, receipt: Path, run: Runner = _run, healthy: Callable[[], bool] | None = None,
             settle: Callable[[], None] = lambda: time.sleep(10)) -> dict:
    res = {"step": "rollback", **_recreate(base_env, None, run, healthy, settle)}
    cp = _psql(run, rollback_sql(), one_tx=True) if res["healthy"] else None
    res["psql_rc"] = None if cp is None else cp.returncode
    res["ok"] = res["healthy"] and cp is not None and cp.returncode == 0 and res["active_after"] == res["active_before"]
    return _receipt(res, receipt)


def _receipt(res: dict, receipt: Path) -> dict:
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    res["receipt"] = str(receipt)
    return res


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env-file", type=Path, default=cut.DEFAULT_NEW_ENV, help="the base n8n env file (0.1a)")
    ap.add_argument("--app-env", type=Path, default=DEFAULT_APP_ENV)
    ap.add_argument("--receipt", type=Path, default=None)
    g = ap.add_mutually_exclusive_group()
    for flag in ("--prepare-secret", "--apply-db", "--switch", "--verify", "--rollback"):
        g.add_argument(flag, action="store_true")
    a = ap.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def rcpt(step: str) -> Path:
        return a.receipt or Path.home() / ".cache" / "tradeai" / f"n8n-db-role-{step}-{stamp}.json"

    if a.prepare_secret:
        out = prepare_secret(a.app_env)
    elif a.apply_db:
        out = apply_db(a.app_env, rcpt("apply-db"))
    elif a.switch:
        out = switch(a.env_file, a.app_env, rcpt("switch"))
    elif a.verify:
        out = verify()
    elif a.rollback:
        out = rollback(a.env_file, rcpt("rollback"))
    else:
        out = plan(a.env_file, a.app_env)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
