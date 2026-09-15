"""R-09 (2026-09-15): auto-queued full analyses only for real securities."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
for _name in ("psycopg2", "psycopg2.extras", "dotenv", "requests"):
    if _name not in sys.modules:
        try:
            __import__(_name)
        except Exception:
            sys.modules[_name] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None,
                                                      extras=types.SimpleNamespace(RealDictCursor=object),
                                                      RealDictCursor=object)

import process_watchlist_agent_jobs as w  # noqa: E402

VALID = {"ACHV", "MYSZ", "VEEA", "ARMP", "DIVI", "CAST"}


def _validate(sym):
    return {"valid": sym in VALID}


def test_invalid_symbols_are_skipped_and_the_next_valid_ones_fill_the_batch():
    rows = [{"symbol": s} for s in ("AI_DEFENSE_TOPIC", "ACHV", "ZZZQ", "MYSZ", "VEEA", "ARMP", "DIVI", "CAST")]
    out = w.auto_queue_valid_symbols(rows, limit=5, validate=_validate)
    assert [r["symbol"] for r in out] == ["ACHV", "MYSZ", "VEEA", "ARMP", "DIVI"]


def test_a_validator_error_counts_as_invalid():
    def boom(sym):
        raise RuntimeError("db down")
    assert w.auto_queue_valid_symbols([{"symbol": "ACHV"}], validate=boom) == []


def test_the_query_widens_so_invalid_names_cannot_starve_the_batch():
    src = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text()
    assert "new_symbols = auto_queue_valid_symbols(cur.fetchall(), limit=5)" in src and "LIMIT 25" in src
