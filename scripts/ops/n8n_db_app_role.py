#!/usr/bin/env python3
"""n8n_db_app_role.py — give n8n a non-superuser database role, ``n8n_app`` (FW-P2). PLAN by default.

Why: AGENTS.md §23.23 "Workflow governance" (7) and §23.24 Logging (3): the n8n DB role is not superuser
(§23.10 P13; WS1b-12). Measured 2026-10-22 (read-only, ``pg_roles``): n8n connects as ``n8n``, the Postgres
image's bootstrap role — ``rolsuper``, ``rolcreaterole``, ``rolcreatedb``, ``rolreplication``, ``rolbypassrls``
all true, owner of every object in schema ``public`` (157 tables, 374 indexes, 25 column-owned sequences,
2 trigger functions; extensions plpgsql and uuid-ossp). The bootstrap role cannot stop being superuser (Postgres
requires one), so n8n gets its own role instead and the n8n container stops holding the superuser password.

What ``n8n_app`` gets — exactly what n8n needs to run and to migrate its own schema, nothing else:

* ``LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 40``;
* ``CONNECT, TEMPORARY`` on database ``n8n``; ``USAGE, CREATE`` on schema ``public`` (n8n migrations create tables);
* ownership of every non-extension relation, free-standing sequence, function and type in ``public`` (migrations
  ALTER existing tables, which only the owner may do; ALTER TABLE … OWNER carries its indexes and column-owned
  sequences). Extension members stay with the extension owner; EXECUTE on them is PUBLIC.

The password is generated here (``secrets.token_urlsafe(32)``) into a file the operator owns, mode 600 in a mode
700 directory (default ``~/.config/tradeai/n8n/n8n_app_pg_password``), and is never printed. Postgres receives
only its SCRAM-SHA-256 verifier (computed here), so the plaintext never reaches the server or its logs. n8n
reads the file through ``DB_POSTGRESDB_PASSWORD_FILE`` (n8n 2.43 ``@n8n/config`` reads ``<VAR>_FILE`` only when
``<VAR>`` is unset — the compose patch removes ``DB_POSTGRESDB_PASSWORD``).

    python3 scripts/ops/n8n_db_app_role.py                    # PLAN: read-only inventory + the SQL (verifier redacted)
    python3 scripts/ops/n8n_db_app_role.py --apply            # operator: password file + role + grants + ownership, one transaction
    python3 scripts/ops/n8n_db_app_role.py --verify           # read-only: rolsuper=f, ownership, privileges, what n8n connects as
    python3 scripts/ops/n8n_db_app_role.py --rollback         # PLAN of the rollback (NOLOGIN + ownership back to n8n)
    python3 scripts/ops/n8n_db_app_role.py --rollback --apply # operator: run it (never DROP ROLE, §0 rule 6)

Every DB statement goes through ``docker exec -i m8m-n8n-db psql -U n8n -d n8n`` (the lab's local-socket path;
no host port, no password on this side). Exit: 0 ok / plan printed, 1 verify failed, 2 cannot run or refused.
AUTHORITY: OPERATOR_APPLIED_DB_ROLE (§17: DB role changes are operator acts; an agent runs the plan and --verify
only). No n8n restart, no compose change, no broker. MBI_BEHAVIOR = 0.
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
from pathlib import Path
from typing import Callable, Optional

NO_CONSUMER_REASON = "operator-run ops script (packet n8n-platform-hardening-20261022, FW-P2); not scheduled"

DB_CONTAINER = "m8m-n8n-db"
N8N_CONTAINER = "m8m-n8n"
ADMIN = "n8n"  # the Postgres image's bootstrap superuser (POSTGRES_USER); local-socket trust inside the container
DB = "n8n"
ROLE = "n8n_app"
CONNECTION_LIMIT = 40
SCRAM_ITERATIONS = 4096
DEFAULT_PASSWORD_FILE = Path.home() / ".config" / "tradeai" / "n8n" / "n8n_app_pg_password"
REDACTED = "SCRAM-SHA-256$<redacted verifier>"
_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

Runner = Callable[..., tuple[int, str, str]]


def default_runner(argv: list[str], *, input_text: Optional[str] = None, timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, input=input_text, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return p.returncode, p.stdout, p.stderr


def psql_argv(*, read_only: bool, container: str = DB_CONTAINER) -> list[str]:
    env = ["-e", "PGOPTIONS=-c default_transaction_read_only=on"] if read_only else []
    return [
        "docker",
        "exec",
        "-i",
        *env,
        container,
        "psql",
        "-X",
        "-q",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        ADMIN,
        "-d",
        DB,
        "-tA",
    ]


# ── SCRAM-SHA-256 verifier (RFC 5802 / 7677, the format Postgres stores in pg_authid.rolpassword) ─────────────────


def scram_verifier(password: str, *, salt: Optional[bytes] = None, iterations: int = SCRAM_ITERATIONS) -> str:
    if not password or not password.isascii():
        raise ValueError("password must be non-empty ASCII (no SASLprep needed)")
    salt = salt if salt is not None else os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


# ── SQL ─────────────────────────────────────────────────────────────────────────────────────────────────────────

INVENTORY_SQL = """select json_build_object(
 'role_exists', exists(select 1 from pg_roles where rolname = '{role}'),
 'role', (select json_build_object('rolsuper', rolsuper, 'rolcreaterole', rolcreaterole, 'rolcreatedb', rolcreatedb,
          'rolreplication', rolreplication, 'rolbypassrls', rolbypassrls, 'rolcanlogin', rolcanlogin,
          'rolconnlimit', rolconnlimit) from pg_roles where rolname = '{role}'),
 'role_memberships', (select coalesce(json_agg(parent.rolname order by parent.rolname), '[]'::json)
                      from pg_auth_members m join pg_roles parent on parent.oid = m.roleid
                      join pg_roles member on member.oid = m.member where member.rolname = '{role}'),
 'admin_rolsuper', (select rolsuper from pg_roles where rolname = '{admin}'),
 'owners', (select coalesce(json_object_agg(k, n), '{{}}'::json) from (
     select pg_get_userbyid(c.relowner) || ':' || c.relkind::text as k, count(*) as n from pg_class c
     where c.relnamespace = 'public'::regnamespace group by 1) q),
 'functions', (select coalesce(json_object_agg(k, n), '{{}}'::json) from (
     select pg_get_userbyid(p.proowner) || ':' || (case when d.objid is null then 'own' else 'extension' end) as k,
            count(*) as n from pg_proc p left join pg_depend d on d.classid = 'pg_proc'::regclass
            and d.objid = p.oid and d.deptype = 'e' where p.pronamespace = 'public'::regnamespace group by 1) q),
 'not_owned_by_role', (select count(*) from pg_class c where c.relnamespace = 'public'::regnamespace
     and c.relkind in ('r','p','v','m','f') and pg_get_userbyid(c.relowner) <> '{role}'
     and not exists (select 1 from pg_depend d where d.classid = 'pg_class'::regclass and d.objid = c.oid
                     and d.deptype = 'e')),
 'functions_not_owned_by_role', (select count(*) from pg_proc p where p.pronamespace = 'public'::regnamespace
     and pg_get_userbyid(p.proowner) <> '{role}' and not exists (select 1 from pg_depend d
     where d.classid = 'pg_proc'::regclass and d.objid = p.oid and d.deptype = 'e')),
 'db_connect', case when exists(select 1 from pg_roles where rolname = '{role}')
     then has_database_privilege('{role}', '{db}', 'CONNECT') end,
 'schema_create', case when exists(select 1 from pg_roles where rolname = '{role}')
     then has_schema_privilege('{role}', 'public', 'USAGE,CREATE') end,
 'extensions', (select coalesce(json_agg(extname order by extname), '[]'::json) from pg_extension),
 'password_encryption', current_setting('password_encryption'),
 'server_version', current_setting('server_version'))"""


def inventory_sql() -> str:
    return " ".join(INVENTORY_SQL.format(role=ROLE, admin=ADMIN, db=DB).split())


OWNERSHIP_DO = f"""DO $do$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.oid::regclass AS obj, c.relkind FROM pg_class c
           WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r','p','v','m','f')
             AND pg_get_userbyid(c.relowner) <> '{ROLE}'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                             AND d.objid = c.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER %s %s OWNER TO {ROLE}',
                   CASE r.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                                  WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END, r.obj);
  END LOOP;
  -- free-standing sequences only: a column-owned sequence moves with its table
  FOR r IN SELECT c.oid::regclass AS obj FROM pg_class c
           WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'S'
             AND pg_get_userbyid(c.relowner) <> '{ROLE}'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                             AND d.deptype IN ('a', 'i', 'e'))
  LOOP
    EXECUTE format('ALTER SEQUENCE %s OWNER TO {ROLE}', r.obj);
  END LOOP;
  FOR r IN SELECT p.oid::regprocedure AS obj, p.prokind FROM pg_proc p
           WHERE p.pronamespace = 'public'::regnamespace AND pg_get_userbyid(p.proowner) <> '{ROLE}'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                             AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER %s %s OWNER TO {ROLE}',
                   CASE r.prokind WHEN 'p' THEN 'PROCEDURE' WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END, r.obj);
  END LOOP;
  -- enums, domains, ranges and free-standing composites (a table's row type moves with the table)
  FOR r IN SELECT t.oid::regtype AS obj, t.typtype FROM pg_type t
           WHERE t.typnamespace = 'public'::regnamespace AND t.typtype IN ('e','d','r','c') AND t.typelem = 0
             AND (t.typrelid = 0 OR (SELECT relkind FROM pg_class WHERE oid = t.typrelid) = 'c')
             AND pg_get_userbyid(t.typowner) <> '{ROLE}'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid
                             AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER %s %s OWNER TO {ROLE}', CASE r.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END, r.obj);
  END LOOP;
END
$do$;"""


def apply_sql(verifier: str, *, role_exists: bool) -> str:
    role_stmt = (
        f"ALTER ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT "
        f"CONNECTION LIMIT {CONNECTION_LIMIT} PASSWORD '{verifier}';"
        if role_exists
        else f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT "
        f"CONNECTION LIMIT {CONNECTION_LIMIT} PASSWORD '{verifier}';"
    )
    return "\n".join(
        [
            "BEGIN;",
            "SET LOCAL lock_timeout = '15s';",
            role_stmt,
            f"GRANT CONNECT, TEMPORARY ON DATABASE {DB} TO {ROLE};",
            f"GRANT USAGE, CREATE ON SCHEMA public TO {ROLE};",
            OWNERSHIP_DO,
            "COMMIT;",
        ]
    )


ROLLBACK_SQL = "\n".join(
    [
        "BEGIN;",
        "SET LOCAL lock_timeout = '15s';",
        f"ALTER ROLE {ROLE} NOLOGIN;",
        f"REASSIGN OWNED BY {ROLE} TO {ADMIN};",
        "COMMIT;",
    ]
)


# ── password file ───────────────────────────────────────────────────────────────────────────────────────────────


def write_password_file(path: Path) -> str:
    """Create the file with a fresh password (mode 600, dir 700). Refuses to overwrite. Returns the password."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    password = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(password)  # no trailing newline: n8n trims, but a clean file needs no warning
    return password


def read_password_file(path: Path) -> str:
    st = path.stat()
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise PermissionError(f"{path} is mode {oct(stat.S_IMODE(st.st_mode))}; must be 600")
    if st.st_uid != os.getuid():
        raise PermissionError(f"{path} is not owned by the operator running this")
    return path.read_text(encoding="ascii").strip()


def password_file_report(path: Path) -> dict:
    try:
        st = path.stat()
    except FileNotFoundError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "mode": oct(stat.S_IMODE(st.st_mode)),
        "owner_uid": st.st_uid,
        "length": st.st_size,
    }  # never the content


# ── actions ─────────────────────────────────────────────────────────────────────────────────────────────────────


def read_inventory(run: Runner, container: str = DB_CONTAINER) -> dict:
    rc, out, err = run(psql_argv(read_only=True, container=container), input_text=inventory_sql() + ";\n")
    if rc != 0:
        raise RuntimeError(f"inventory read failed: exit {rc}: {err.strip()[:200]}")
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"inventory read returned no JSON: {out.strip()[:120]}") from exc


def n8n_connects_as(run: Runner, container: str = N8N_CONTAINER) -> Optional[str]:
    rc, out, _ = run(
        [
            "docker",
            "inspect",
            container,
            "--format",
            '{{range .Config.Env}}{{if eq (index (split . "=") 0) "DB_POSTGRESDB_USER"}}{{println .}}{{end}}{{end}}',
        ]
    )
    if rc != 0:
        return None
    for line in out.splitlines():
        if line.startswith("DB_POSTGRESDB_USER="):
            return line.split("=", 1)[1].strip()
    return None


def verify(inv: dict, *, connects_as: Optional[str]) -> list[str]:
    problems = []
    role = inv.get("role") or {}
    if not inv.get("role_exists"):
        return [f"role {ROLE} does not exist"]
    for k in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication", "rolbypassrls"):
        if role.get(k):
            problems.append(f"{ROLE}.{k} = t")
    if not role.get("rolcanlogin"):
        problems.append(f"{ROLE} cannot log in")
    memberships = inv.get("role_memberships") or []
    if memberships:
        problems.append(f"{ROLE} is a member of elevated or inherited role(s): {', '.join(sorted(memberships))}")
    if inv.get("not_owned_by_role"):
        problems.append(f"{inv['not_owned_by_role']} public relation(s) not owned by {ROLE}")
    if inv.get("functions_not_owned_by_role"):
        problems.append(f"{inv['functions_not_owned_by_role']} public function(s) not owned by {ROLE}")
    if inv.get("db_connect") is not True:
        problems.append(f"{ROLE} lacks CONNECT on {DB}")
    if inv.get("schema_create") is not True:
        problems.append(f"{ROLE} lacks USAGE,CREATE on schema public")
    if connects_as != ROLE:
        problems.append(f"n8n container connects as {connects_as!r}, not {ROLE!r} (compose switch pending)")
    return problems


def main(argv: Optional[list[str]] = None, *, run: Runner = default_runner) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="read-only verification")
    mode.add_argument("--rollback", action="store_true", help="the rollback (plan unless --apply)")
    ap.add_argument("--apply", action="store_true", help="perform the change (operator only); default is the plan")
    ap.add_argument("--password-file", default=str(DEFAULT_PASSWORD_FILE))
    ap.add_argument(
        "--reuse-password-file",
        action="store_true",
        help="the password file already exists (an earlier --apply): set the role's verifier from it instead of refusing",
    )
    ap.add_argument("--db-container", default=DB_CONTAINER, help="Postgres container (a scratch copy for rehearsal)")
    ap.add_argument("--n8n-container", default=N8N_CONTAINER)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    pw_path = Path(a.password_file).expanduser()
    try:
        inv = read_inventory(run, a.db_container)
    except RuntimeError as exc:
        print(f"n8n_db_app_role CANNOT RUN: {exc}", file=sys.stderr)
        return 2

    if a.verify:
        connects = n8n_connects_as(run, a.n8n_container)
        problems = verify(inv, connects_as=connects)
        out = {
            "verify": "PASS" if not problems else "FAIL",
            "problems": problems,
            "role": inv.get("role"),
            "n8n_connects_as": connects,
            "password_file": password_file_report(pw_path),
        }
        print(
            json.dumps(out, indent=1)
            if a.json
            else f"verify {out['verify']}: {ROLE} "
            + (
                f"rolsuper={'t' if (inv.get('role') or {}).get('rolsuper') else 'f'}; "
                if inv.get("role_exists")
                else "absent; "
            )
            + f"n8n connects as {connects}; "
            + ("; ".join(problems) or "all checks pass")
        )
        return 0 if not problems else 1

    if a.rollback:
        print(
            ("ROLLBACK APPLY" if a.apply else "ROLLBACK PLAN (nothing executed)")
            + f" — role {ROLE} exists: {inv.get('role_exists')}"
        )
        print(ROLLBACK_SQL)
        print(
            "Then restore the archived compose file and recreate n8n (packet README FW-P2 rollback). "
            f"{ROLE} is never dropped (§0 rule 6); the password file is archived by rename, not deleted."
        )
        if not a.apply:
            return 0
        if not inv.get("role_exists"):
            print(f"nothing to roll back: {ROLE} does not exist")
            return 0
        rc, _out, err = run(psql_argv(read_only=False, container=a.db_container), input_text=ROLLBACK_SQL + "\n")
        print("rollback " + ("OK" if rc == 0 else f"FAILED exit {rc}: {err.strip()[:200]}"))
        return 0 if rc == 0 else 2

    exists = bool(inv.get("role_exists"))
    plan = {
        "role": ROLE,
        "role_exists": exists,
        "admin_rolsuper": inv.get("admin_rolsuper"),
        "owners_by_kind": inv.get("owners"),
        "functions": inv.get("functions"),
        "extensions": inv.get("extensions"),
        "password_encryption": inv.get("password_encryption"),
        "server_version": inv.get("server_version"),
        "password_file": password_file_report(pw_path),
    }
    if not a.apply:
        print(json.dumps(plan, indent=1) if a.json else "PLAN (read-only; nothing written, nothing executed)")
        if not a.json:
            for k, v in plan.items():
                print(f"  {k}: {v}")
            print("SQL that --apply runs in ONE transaction (the verifier is computed at apply time; shown redacted):")
            print(apply_sql(REDACTED, role_exists=exists))
            if pw_path.exists() and not a.reuse_password_file:
                print(f"NOTE: {pw_path} exists; --apply will refuse unless --reuse-password-file")
            if exists and not a.reuse_password_file:
                print(f"NOTE: role {ROLE} exists; --apply will refuse unless --reuse-password-file")
        return 0

    # ── apply (operator) ──
    if (pw_path.exists() or exists) and not a.reuse_password_file:
        print(
            f"REFUSED: {'password file ' + str(pw_path) + ' exists' if pw_path.exists() else ''}"
            f"{' and ' if pw_path.exists() and exists else ''}{'role ' + ROLE + ' exists' if exists else ''}; "
            "re-run with --reuse-password-file to set the role from the existing file (never overwritten)",
            file=sys.stderr,
        )
        return 2
    try:
        if pw_path.exists():
            password = read_password_file(pw_path)
            made = False
        else:
            password = write_password_file(pw_path)
            made = True
    except (OSError, PermissionError, ValueError) as exc:
        print(f"REFUSED: password file: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    sql = apply_sql(scram_verifier(password), role_exists=exists)
    del password
    rc, _out, err = run(psql_argv(read_only=False, container=a.db_container), input_text=sql + "\n")
    if rc != 0:
        # nothing committed (single transaction); a password file this run created is archived, not deleted
        if made:
            archived = pw_path.with_name(pw_path.name + ".unused-" + secrets.token_hex(3))
            pw_path.rename(archived)
            print(
                f"apply FAILED (rolled back by Postgres): exit {rc}: {err.strip()[:200]}; "
                f"unused password file archived to {archived}",
                file=sys.stderr,
            )
        else:
            print(f"apply FAILED (rolled back by Postgres): exit {rc}: {err.strip()[:200]}", file=sys.stderr)
        return 2
    after = read_inventory(run, a.db_container)
    problems = [p for p in verify(after, connects_as=ROLE) if "connects as" not in p]
    print(
        f"apply OK: {ROLE} {'updated' if exists else 'created'}; password file {password_file_report(pw_path)}; "
        f"rolsuper={'t' if (after.get('role') or {}).get('rolsuper') else 'f'}; "
        + ("; ".join(problems) or "ownership and privileges verified")
        + ". NEXT: apply the compose patch (DB_POSTGRESDB_USER=n8n_app + DB_POSTGRESDB_PASSWORD_FILE) and recreate n8n."
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
