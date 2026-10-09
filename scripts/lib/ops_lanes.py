"""Shared helpers for the read-only ops lanes (storage-watch, backup-verify, trade-ai-restore-drill).

Config comes from ``config/ops_lanes.json`` (``OpsLanesConfig@v1``); receipts go under the state root
(``$TRADEAI_STATE_ROOT`` else the canonical production root) with an atomic tmp+rename. Findings use the
incident fan-in shape of ``scripts/n8n_incident_fanin.py``: {source, item, severity, detail, artifact_rel,
store, detected_at}. Nothing here sends.

Postgres reads use a session with ``default_transaction_read_only=on`` and a statement timeout. Credentials
are read by key from the environment, then from ``<code root>/.env`` (never sourced — the file is not
shell-safe; same rule as linux_launchers/run_pg_backup.sh).

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

NO_CONSUMER_REASON = (
    "helper library imported by scripts/storage_watch.py, scripts/backup_verify.py and "
    "scripts/trade_ai_restore_drill.py; defines the config schema those lanes read"
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "ops_lanes.json"
CONFIG_SCHEMA = "OpsLanesConfig@v1"

Runner = Callable[..., subprocess.CompletedProcess]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def load_config(path: Optional[Path] = None) -> dict:
    doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    if doc.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"unexpected config schema {doc.get('schema')!r}")
    return doc


def expand(path: str, env: Optional[Mapping[str, str]] = None, env_key: Optional[str] = None) -> Path:
    """Expand ~ against the running user's home; an env override (when named and set) wins."""
    env = os.environ if env is None else env
    if env_key and env.get(env_key):
        return Path(env[env_key]).expanduser()
    return Path(os.path.expanduser(path))


def state_root(env: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_STATE_ROOT"):
        return Path(env["TRADEAI_STATE_ROOT"])
    try:
        from scripts.lib.canonical_store_registry import production_state_root

        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def finding(
    source: str,
    item: str,
    severity: str,
    detail: str,
    artifact_rel: str,
    *,
    detected_at: Optional[str] = None,
) -> dict:
    assert severity in ("P1", "P2", "P3"), severity
    return {
        "source": source,
        "item": item,
        "severity": severity,
        "detail": detail[:240],
        "artifact_rel": artifact_rel,
        "store": "data/runtime",
        "detected_at": detected_at or iso(utc_now()),
    }


def write_receipt(receipt: Mapping[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def fs_usage(path: str) -> dict:
    """df-equivalent numbers for the filesystem holding ``path`` (Use% = used / (used + avail))."""
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    free_root = st.f_bfree * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    used = total - free_root
    used_pct = round(100.0 * used / (used + avail), 2) if (used + avail) else 0.0
    inodes_total = st.f_files
    inodes_free = st.f_ffree
    inodes_used = inodes_total - inodes_free
    inode_pct = round(100.0 * inodes_used / inodes_total, 2) if inodes_total else 0.0
    return {
        "path": path,
        "total_bytes": total,
        "used_bytes": used,
        "avail_bytes": avail,
        "used_pct": used_pct,
        "free_pct": round(100.0 - used_pct, 2),
        "inodes_total": inodes_total,
        "inodes_used": inodes_used,
        "inodes_used_pct": inode_pct,
    }


def _env_file_value(key: str, env_file: Path) -> Optional[str]:
    try:
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def db_params(
    env: Optional[Mapping[str, str]] = None,
    *,
    user_env: Optional[str] = None,
    password_env: Optional[str] = None,
    env_file: Optional[Path] = None,
) -> dict:
    """host/port/dbname/user/password for trade_ai. Password is returned, never printed."""
    env = os.environ if env is None else env
    env_file = env_file or (ROOT / ".env")

    def val(key: str, default: Optional[str] = None) -> Optional[str]:
        return env.get(key) or _env_file_value(key, env_file) or default

    user = (env.get(user_env) if user_env else None) or val("DB_USER", "trade_ai")
    password = (env.get(password_env) if password_env else None) or val("DB_PASSWORD", "")
    return {
        "host": val("DB_HOST", "localhost"),
        "port": int(val("DB_PORT", "5432") or 5432),
        "dbname": val("DB_NAME", "trade_ai"),
        "user": user,
        "password": password,
    }


def pg_connect(params: Mapping[str, Any], *, dbname: Optional[str] = None, read_only: bool = True, timeout_ms: int = 120000):
    import psycopg2

    options = f"-c statement_timeout={int(timeout_ms)}"
    if read_only:
        options += " -c default_transaction_read_only=on"
    conn = psycopg2.connect(
        host=params["host"],
        port=params["port"],
        dbname=dbname or params["dbname"],
        user=params["user"],
        password=params["password"],
        options=options,
        application_name="tradeai-ops-lane",
        connect_timeout=10,
    )
    conn.autocommit = True
    return conn


def nice_prefix(nice: int = 19) -> list[str]:
    prefix = ["nice", "-n", str(int(nice))]
    if shutil.which("ionice"):
        prefix = ["ionice", "-c3", *prefix]
    return prefix


def run(argv: Sequence[str], *, timeout: int, runner: Optional[Runner] = None, **kw) -> subprocess.CompletedProcess:
    runner = runner or subprocess.run
    return runner(list(argv), capture_output=True, text=True, timeout=timeout, check=False, **kw)
