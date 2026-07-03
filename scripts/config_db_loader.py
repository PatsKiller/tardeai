#!/usr/bin/env python3
"""
config_db_loader.py — DB-first config loader with file fallback.

Functions:
  get_config(config_key, fallback_path=None, required=False) → dict/list
  load_yaml_or_json_file(path) → dict/list
  upsert_config_document(config_key, content, config_type, source_path, notes)
"""
import hashlib, json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SECRET_KEYS = {"password", "token", "secret", "api_key", "cookie", "credential", "private_key"}


def _env(key, default=""):
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.getenv(key, default)


def _get_conn():
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))


def _checksum(content):
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _redact_log(msg):
    """Redact secret-like values from log messages."""
    for s in SECRET_KEYS:
        if s in msg.lower():
            return msg.split("=")[0] + "=***REDACTED***" if "=" in msg else msg
    return msg


def load_yaml_or_json_file(path):
    """Load a YAML or JSON file, return parsed content."""
    p = Path(path)
    if not p.exists():
        return None
    text = p.read_text(errors="replace")
    if p.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    else:
        return json.loads(text)


def get_config(config_key, fallback_path=None, required=False):
    """
    DB-first config read. Falls back to file if not in DB.

    Args:
        config_key: Unique key in config_documents table
        fallback_path: File path to read if not in DB (relative to PROJECT_ROOT)
        required: If True, raise error when both DB and file fail

    Returns:
        Parsed config (dict or list), or None
    """
    # Try DB first
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM config_documents WHERE config_key = %s AND active = true",
            (config_key,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return row[0] if isinstance(row[0], (dict, list)) else json.loads(row[0])
    except Exception:
        pass

    # Fallback to file
    if fallback_path:
        full_path = PROJECT_ROOT / fallback_path if not Path(fallback_path).is_absolute() else Path(fallback_path)
        try:
            content = load_yaml_or_json_file(str(full_path))
            if content is not None:
                return content
        except Exception:
            pass

    if required:
        raise FileNotFoundError(
            f"Config '{config_key}' not found in DB or file '{fallback_path}'"
        )
    return None


def upsert_config_document(config_key, content, config_type, source_path=None,
                            notes=None, changed_by="migration_script"):
    """
    Upsert a config document into DB. Records history if checksum changes.

    Returns: 'inserted', 'updated', 'unchanged'
    """
    checksum = _checksum(content)
    conn = _get_conn()
    cur = conn.cursor()

    # Check existing
    cur.execute(
        "SELECT id, checksum FROM config_documents WHERE config_key = %s",
        (config_key,)
    )
    existing = cur.fetchone()

    if existing:
        old_id, old_checksum = existing
        if old_checksum == checksum:
            conn.close()
            return "unchanged"
        # Record history
        cur.execute("""
            INSERT INTO config_document_history
                (config_key, source_path, config_type, old_checksum, new_checksum,
                 content, changed_by, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (config_key, source_path, config_type, old_checksum, checksum,
              json.dumps(content, default=str), changed_by, notes or "checksum changed"))
        # Update
        cur.execute("""
            UPDATE config_documents
            SET content = %s, checksum = %s, source_path = %s,
                updated_at = NOW(), notes = %s
            WHERE config_key = %s
        """, (json.dumps(content, default=str), checksum, source_path,
              notes, config_key))
        conn.commit()
        conn.close()
        return "updated"
    else:
        cur.execute("""
            INSERT INTO config_documents
                (config_key, source_path, config_type, content, checksum, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (config_key, source_path, config_type,
              json.dumps(content, default=str), checksum, notes))
        conn.commit()
        conn.close()
        return "inserted"


# mirror_holdings() retired 2026-07-03: it only ran via this module's __main__ smoke test, so the
# holdings_json_mirror table silently froze at 2026-05-09. Nothing consumed it; the canonical
# snapshot chain is holdings.json (+ raw_snapshots / ticker_snapshot_history for point-in-time reads).


if __name__ == "__main__":
    # Quick test
    print("Testing config_db_loader...")
    result = get_config("test_nonexistent", fallback_path="config/thesis.json")
    print(f"  Fallback test: {'OK' if result else 'FAILED'}")
    print("Done.")
