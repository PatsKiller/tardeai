"""LQ-20261107-429: db_adapter connections turn JIT off (JIT compile was ~3 s of the /watchlist/items query)."""
from pathlib import Path


def test_connection_setup_turns_jit_off():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "db_adapter.py").read_text()
    i = src.index('_c.execute("SET jit = off")')
    assert src.index("SET statement_timeout") < i < src.index("conn.commit()", i)
