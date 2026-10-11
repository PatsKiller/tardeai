"""session13_db.py — credential-safe DB helper for Session 13 scripts."""
import os
_ENV_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def get_conn():
    # Importing a writer for its offline preview must not read credential files.
    # The shared loader also honours the executor's per-lane environment bound.
    try:
        from scripts.lib.env_bootstrap import load_env
    except ImportError:
        from lib.env_bootstrap import load_env
    load_env(names=_ENV_KEYS)
    import psycopg2

    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from process configuration")
    import sys
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
        # attribution in pg_stat_activity / idle-txn triage (these showed as app='' before)
        application_name=os.path.basename(sys.argv[0] or "python")[:63],
    )
