"""session13_db.py — credential-safe DB helper for Session 13 scripts."""
import os
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')


def get_conn():
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
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
