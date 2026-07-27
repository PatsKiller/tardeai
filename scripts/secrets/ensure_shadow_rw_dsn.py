#!/usr/bin/env python3
"""Ensure agentic_runtime_shadow_rw exists on the LAB DB and SHADOW_DSN is in Bitwarden SM.

Packet D needs SHADOW_DSN=agentic_runtime_shadow_rw@trade_ai_agentic_lab (not bare trade_ai).

Flow:
  1) Resolve LAB_DSN (tmpfs SM → env → disk .env) — never print it
  2) Refuse production database trade_ai
  3) Connect as LAB_DSN; ensure role agentic_runtime_shadow_rw + least-privilege grants
     matching migrations/agentic_runtime/0002_roles.up.sql intent
  4) Password: create if role missing; rotate only with --rotate if role already exists
  5) Upsert SM secret SHADOW_DSN via secrets_admin.set_secret → render_env --now
  6) Print ONLY: ok/fail, role_exists, secret_upserted, dsn_len, has_shadow_rw_user
     NEVER password or full DSN

Usage:
  .venv/bin/python scripts/secrets/ensure_shadow_rw_dsn.py
  .venv/bin/python scripts/secrets/ensure_shadow_rw_dsn.py --rotate
  .venv/bin/python scripts/secrets/ensure_shadow_rw_dsn.py --dry-run
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import string
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

SHADOW_ROLE = "agentic_runtime_shadow_rw"
SECRET_NAME = "SHADOW_DSN"
PACKET_D = ROOT / "scripts" / "operator_packets" / "packet_d_shadow_acceptance.py"


def _load_packet_d():
    spec = importlib.util.spec_from_file_location("packet_d_shadow_acceptance", PACKET_D)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resolve_lab_dsn() -> str:
    from resolve_secret import resolve_secret
    return (resolve_secret("LAB_DSN") or resolve_secret("TRADE_AI_LAB_DSN") or "").strip()


def _parse_dsn_parts(dsn: str) -> dict[str, Any]:
    """Parse host/port/db/user without logging values."""
    pd = _load_packet_d()
    db, user = pd._parse_dsn_identity(dsn)
    is_prod = pd._is_production_dbname(db)

    host = port = password = None
    low = dsn.lower()
    if low.startswith("postgres"):
        u = urlparse(dsn)
        host = u.hostname
        port = u.port or 5432
        password = unquote(u.password) if u.password else None
    else:
        for part in dsn.replace(";", " ").split():
            if "=" not in part:
                continue
            k, _, v = part.partition("=")
            k, v = k.strip().lower(), v.strip().strip("'\"")
            if k == "host":
                host = v
            elif k == "port":
                try:
                    port = int(v)
                except ValueError:
                    port = 5432
            elif k == "password":
                password = v
        port = port or 5432
    return {
        "dbname": db,
        "user": user,
        "host": host or "127.0.0.1",
        "port": int(port or 5432),
        "password": password,
        "is_production": is_prod,
    }


def _gen_password(n: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _connect(parts: dict[str, Any]):
    import psycopg2
    return psycopg2.connect(
        host=parts["host"],
        port=parts["port"],
        dbname=parts["dbname"],
        user=parts["user"],
        password=parts["password"] or "",
        connect_timeout=10,
    )


def _role_exists(cur, role: str) -> bool:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    return cur.fetchone() is not None


def _ensure_role_and_grants(cur, *, password: str | None, create: bool, set_password: bool) -> None:
    """CREATE ROLE if needed; apply 0002_roles-style grants. Password only when provided."""
    if create:
        cur.execute(
            f"""
            CREATE ROLE {SHADOW_ROLE} LOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
                PASSWORD %s
            """,
            (password,),
        )
    elif set_password and password:
        cur.execute(f"ALTER ROLE {SHADOW_ROLE} PASSWORD %s", (password,))

    # Grants match migrations/agentic_runtime/0002_roles.up.sql (idempotent)
    cur.execute("REVOKE ALL ON SCHEMA agentic_runtime FROM PUBLIC")
    cur.execute(f"GRANT USAGE ON SCHEMA agentic_runtime TO {SHADOW_ROLE}")
    cur.execute(f"REVOKE CREATE ON SCHEMA agentic_runtime FROM {SHADOW_ROLE}")
    cur.execute(
        f"GRANT SELECT, INSERT, UPDATE ON agentic_runtime.agent_runs TO {SHADOW_ROLE}"
    )
    for table in (
        "agent_artifacts",
        "agent_tool_calls",
        "agent_reviews",
        "agent_scores",
        "kb_lessons",
        "kb_cases",
        "kb_chunks",
    ):
        cur.execute(
            f"GRANT SELECT, INSERT ON agentic_runtime.{table} TO {SHADOW_ROLE}"
        )
    cur.execute(
        f"""
        ALTER DEFAULT PRIVILEGES IN SCHEMA agentic_runtime
            GRANT SELECT, INSERT ON TABLES TO {SHADOW_ROLE}
        """
    )


def _build_shadow_dsn(parts: dict[str, Any], password: str) -> str:
    user = quote(SHADOW_ROLE, safe="")
    pw = quote(password, safe="")
    host = parts["host"]
    port = parts["port"]
    db = parts["dbname"]
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


def _existing_shadow_dsn_ok() -> tuple[bool, int]:
    """Return (ok, dsn_len) if SM/tmpfs SHADOW_DSN already passes Packet D guard."""
    try:
        from resolve_secret import resolve_secret
        dsn = resolve_secret(SECRET_NAME)
        if not dsn:
            return False, 0
        pd = _load_packet_d()
        pd._shadow_dsn_guard(dsn)
        return True, len(dsn)
    except Exception:
        return False, 0


def run(*, dry_run: bool, rotate: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "role_exists": False,
        "secret_upserted": False,
        "dsn_len": 0,
        "has_shadow_rw_user": False,
        "error": None,
        "action": None,
    }
    lab = _resolve_lab_dsn()
    if not lab:
        out["error"] = "LAB_DSN not found (SM tmpfs / env / disk)"
        return out
    parts = _parse_dsn_parts(lab)
    if parts["is_production"] or (parts["dbname"] or "").lower() == "trade_ai":
        out["error"] = "LAB_DSN targets production trade_ai — refusing all writes"
        return out
    if not parts["dbname"]:
        out["error"] = "could not parse LAB_DSN database name"
        return out
    if not parts["user"]:
        out["error"] = "could not parse LAB_DSN user"
        return out

    try:
        conn = _connect(parts)
    except Exception as e:
        out["error"] = f"connect failed: {type(e).__name__}"
        return out

    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SELECT current_database()")
        current_db = cur.fetchone()[0]
        if str(current_db).lower() == "trade_ai":
            out["error"] = "connected database is production trade_ai — refusing"
            conn.rollback()
            return out

        exists = _role_exists(cur, SHADOW_ROLE)
        out["role_exists"] = exists
        password: str | None = None
        need_upsert = False

        if not exists:
            password = _gen_password()
            if dry_run:
                out["action"] = "would_create_role_and_upsert"
                out["has_shadow_rw_user"] = True
                out["ok"] = True
                conn.rollback()
                return out
            _ensure_role_and_grants(cur, password=password, create=True, set_password=True)
            need_upsert = True
            out["action"] = "created_role"
        elif rotate:
            password = _gen_password()
            if dry_run:
                out["action"] = "would_rotate_password_and_upsert"
                out["has_shadow_rw_user"] = True
                out["ok"] = True
                conn.rollback()
                return out
            _ensure_role_and_grants(cur, password=password, create=False, set_password=True)
            need_upsert = True
            out["action"] = "rotated_password"
        else:
            if dry_run:
                out["action"] = "would_refresh_grants_only"
                out["has_shadow_rw_user"] = True
                out["ok"] = True
                ok_sm, dlen = _existing_shadow_dsn_ok()
                if ok_sm:
                    out["dsn_len"] = dlen
                conn.rollback()
                return out
            _ensure_role_and_grants(cur, password=None, create=False, set_password=False)
            out["action"] = "grants_refreshed"
            conn.commit()
            ok_sm, dlen = _existing_shadow_dsn_ok()
            if ok_sm:
                out["dsn_len"] = dlen
                out["has_shadow_rw_user"] = True
                out["secret_upserted"] = False
                out["ok"] = True
                return out
            out["error"] = (
                "role exists but SHADOW_DSN missing/invalid in SM; re-run with --rotate "
                "to set a new password and upsert SHADOW_DSN (password cannot be recovered)"
            )
            return out

        conn.commit()

        if need_upsert and password:
            dsn = _build_shadow_dsn(parts, password)
            out["dsn_len"] = len(dsn)
            password = None
            try:
                import secrets_admin
                res = secrets_admin.set_secret(SECRET_NAME, dsn, actor="ensure_shadow_rw_dsn")
                out["secret_upserted"] = bool(res.get("ok"))
            except Exception as e:
                out["error"] = f"set_secret failed: {type(e).__name__}"
                dsn = ""
                return out
            dsn = ""
            out["has_shadow_rw_user"] = True
            out["ok"] = True
        return out
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        out["error"] = f"{type(e).__name__}"
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Ensure agentic_runtime_shadow_rw + SHADOW_DSN SM secret (never prints DSN)"
    )
    p.add_argument("--dry-run", action="store_true", help="no CREATE/ALTER/SM write")
    p.add_argument(
        "--rotate",
        action="store_true",
        help="rotate shadow_rw password and upsert SHADOW_DSN (required if role exists without secret)",
    )
    args = p.parse_args(argv)
    result = run(dry_run=args.dry_run, rotate=args.rotate)
    print(json.dumps({
        "ok": result["ok"],
        "role_exists": result["role_exists"],
        "secret_upserted": result["secret_upserted"],
        "dsn_len": result["dsn_len"],
        "has_shadow_rw_user": result["has_shadow_rw_user"],
        "action": result.get("action"),
        "error": result.get("error"),
        "note": "Packet D: SHADOW_DSN=agentic_runtime_shadow_rw@trade_ai_agentic_lab",
    }, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
