"""2026-10-08: pgvector migration of content_embeddings — plan/guards/batching and the reader switch.
Hermetic: stub measurements and a fake cursor; nothing connects, nothing writes."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import migrate_content_embeddings_pgvector as mig  # noqa: E402
import embedding_reader as er  # noqa: E402


def _m(**over) -> mig.Measurement:
    base = dict(rows=1_308_244, total_bytes=12_369_084_416, toast_bytes=11_810_000_000, index_bytes=156_000_000,
                dims={"768": 1_308_244}, rows_per_day=16_896.0, ext_version="0.8.6", column_present=False,
                index_present=False, disk_free_pct=14.3, disk_free_bytes=67_000_000_000)
    base.update(over)
    return mig.Measurement(**base)


def test_plan_emits_ddl_with_the_measured_dimension_and_never_writes():
    p = mig.plan(_m(), batch=2000)
    assert p["writes"] is False and p["authority"] == "READ_ONLY_ADVISORY"
    assert p["ddl"]["add_column"] == "ALTER TABLE content_embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector(768);"
    assert "CREATE INDEX CONCURRENTLY" in p["ddl"]["create_index"] and "vector_cosine_ops" in p["ddl"]["create_index"]
    assert "DROP" not in " ".join(v for k, v in p["ddl"].items() if k != "never_here")
    e = p["estimates"]
    assert e["dim"] == 768 and 4.0e9 < e["vector_column_bytes"] < 4.1e9
    assert e["net_after_jsonb_drop_bytes"] < 0          # the migration ends smaller than today


def test_apply_refuses_without_authorization_and_under_each_guard(monkeypatch):
    monkeypatch.delenv(mig.AUTH_ENV, raising=False)
    with pytest.raises(mig.Refused) as r:
        mig.refuse_unless_safe(_m(disk_free_pct=40.0), apply=True)
    assert r.value.code == "not_authorized"
    env = {mig.AUTH_ENV: "1"}
    with pytest.raises(mig.Refused) as r:
        mig.refuse_unless_safe(_m(disk_free_pct=14.3), apply=True, env=env)
    assert r.value.code == "disk_headroom"
    with pytest.raises(mig.Refused) as r:
        mig.refuse_unless_safe(_m(disk_free_pct=40.0, dims={"768": 10, "1024": 1}), apply=True, env=env)
    assert r.value.code == "dimension_not_uniform"
    with pytest.raises(mig.Refused) as r:
        mig.refuse_unless_safe(_m(disk_free_pct=40.0, ext_version=None), apply=True, env=env)
    assert r.value.code == "extension_missing"
    mig.refuse_unless_safe(_m(disk_free_pct=40.0), apply=True, env=env)   # all guards pass → no raise
    # the operator can lower the floor deliberately, never silently
    mig.refuse_unless_safe(_m(disk_free_pct=14.3), apply=True, env={mig.AUTH_ENV: "1", mig.MIN_FREE_ENV: "12"})


def test_backfill_batch_sql_is_keyset_bounded_and_dimension_checked():
    sql = mig.ddl(768, 2000)["backfill_batch"]
    assert "LIMIT 2000" in sql and "id > %(after_id)s" in sql and "ORDER BY id" in sql
    assert "embedding_vec IS NULL" in sql and "jsonb_array_length(embedding) = 768" in sql
    assert re.search(r"::vector\(768\)", sql) and "DELETE" not in sql.upper()


class _Cur:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return list(self.rows)


def test_reader_default_backend_is_jsonb_with_the_original_sql_and_python_scoring():
    cur = _Cur([{"id": 1, "embedding": [1.0, 0.0], "created_at": None}])
    rows, used = er.fetch_candidates(cur, query_vec=[1.0, 0.0], term="NVDA", is_category=False, env={})
    assert used == "jsonb" and rows and cur.calls[0][1] == ("%NVDA%",)
    assert "ORDER BY created_at DESC LIMIT 200" in cur.calls[0][0] and "<=>" not in cur.calls[0][0]
    cos = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert er.similarity(rows[0], [1.0, 0.0], cos, used) == 1.0
    assert er.backend({er.BACKEND_ENV: "nonsense"}) == "jsonb"


def test_reader_pgvector_backend_ranks_in_postgres_and_carries_cosine_sim():
    cur = _Cur([{"id": 1, "embedding": None, "cosine_sim": 0.93}])
    rows, used = er.fetch_candidates(cur, query_vec=[0.5, 0.25], term="news", is_category=True, env={er.BACKEND_ENV: "pgvector"})
    assert used == "pgvector"
    sql, params = cur.calls[0]
    assert "<=> %s::vector" in sql and "embedding_vec IS NOT NULL" in sql and "LIMIT 200" in sql
    assert params == ("[0.5,0.25]", "%news%", "[0.5,0.25]")
    assert er.similarity(rows[0], [0.5, 0.25], lambda a, b: 0.0, used) == 0.93
    # no query vector → falls back to jsonb even when pgvector is requested (embedding runtime down)
    cur2 = _Cur([])
    _, used2 = er.fetch_candidates(cur2, query_vec=None, term="x", is_category=False, env={er.BACKEND_ENV: "pgvector"})
    assert used2 == "jsonb"


def test_jsonb_decoding_matches_the_readers_historical_forms():
    assert er.decode_jsonb_vector([1, 2]) == [1.0, 2.0]
    assert er.decode_jsonb_vector("[1, 2]") == [1.0, 2.0]
    assert er.decode_jsonb_vector({"a": 1, "b": 2}) == [1.0, 2.0]
    assert er.decode_jsonb_vector("not json") is None and er.decode_jsonb_vector(None) is None


def test_rag_retrieval_imports_the_adapter_and_keeps_the_default():
    src = (ROOT / "scripts" / "rag_retrieval.py").read_text()
    assert "from lib.embedding_reader import fetch_candidates" in src
    assert "ORDER BY ce.created_at DESC LIMIT 200" not in src      # the SQL now lives in one place
