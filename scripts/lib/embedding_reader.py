"""embedding_reader — one switch between the jsonb embeddings and the pgvector column.

2026-10-08 (pgvector migration plan). `content_embeddings.embedding` is jsonb (1.31 M rows, 11 GB of
TOAST, all nomic-embed-text 768-d). Readers today pull up to 200 candidate rows by title/source and
score cosine similarity in Python. After `scripts/migrate_content_embeddings_pgvector.py --apply`
adds `embedding_vec vector(768)` + an HNSW index, the same readers can let Postgres rank by
`embedding_vec <=> query` instead. The backend is chosen by ONE environment flag so the switch is an
env flip and a restart, never a code change at cutover time:

    TRADEAI_EMBEDDINGS_BACKEND=jsonb      (default; behaviour unchanged, byte-for-byte the old SQL)
    TRADEAI_EMBEDDINGS_BACKEND=pgvector   (requires the column + index to exist; verified by --verify)

AUTHORITY: READ_ONLY_ADVISORY. This module only reads. No DDL, no writes.
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable, Optional

BACKEND_ENV = "TRADEAI_EMBEDDINGS_BACKEND"
BACKENDS = ("jsonb", "pgvector")
VEC_COLUMN = "embedding_vec"
DEFAULT_DIM = 768

_SQL_JSONB_CATEGORY = """
                SELECT ce.id, ce.source_type, ce.source_id, ce.title, ce.embedding, ce.created_at
                FROM content_embeddings ce
                WHERE (ce.title ILIKE %s OR ce.source_type IN ('news','youtube','research_finding'))
                  AND ce.created_at > NOW() - INTERVAL '365 days'
                ORDER BY ce.created_at DESC LIMIT 200
            """
_SQL_JSONB_SYMBOL = """
                SELECT id, source_type, source_id, title, embedding, created_at
                FROM content_embeddings
                WHERE title ILIKE %s
                  AND created_at > NOW() - INTERVAL '365 days'
                ORDER BY created_at DESC LIMIT 200
            """
# pgvector: Postgres ranks by cosine distance over the SAME candidate predicate, so the 200-row cap
# becomes "the 200 nearest", not "the 200 newest" — the recency factor is still applied by the caller.
_SQL_VEC_CATEGORY = f"""
                SELECT ce.id, ce.source_type, ce.source_id, ce.title, NULL::jsonb AS embedding, ce.created_at,
                       1 - (ce.{VEC_COLUMN} <=> %s::vector) AS cosine_sim
                FROM content_embeddings ce
                WHERE (ce.title ILIKE %s OR ce.source_type IN ('news','youtube','research_finding'))
                  AND ce.created_at > NOW() - INTERVAL '365 days'
                  AND ce.{VEC_COLUMN} IS NOT NULL
                ORDER BY ce.{VEC_COLUMN} <=> %s::vector LIMIT 200
            """
_SQL_VEC_SYMBOL = f"""
                SELECT id, source_type, source_id, title, NULL::jsonb AS embedding, created_at,
                       1 - ({VEC_COLUMN} <=> %s::vector) AS cosine_sim
                FROM content_embeddings
                WHERE title ILIKE %s
                  AND created_at > NOW() - INTERVAL '365 days'
                  AND {VEC_COLUMN} IS NOT NULL
                ORDER BY {VEC_COLUMN} <=> %s::vector LIMIT 200
            """


def backend(env: Optional[dict] = None) -> str:
    env = os.environ if env is None else env
    value = str(env.get(BACKEND_ENV, "jsonb") or "jsonb").strip().lower()
    return value if value in BACKENDS else "jsonb"


def vector_literal(vec: Iterable[float]) -> str:
    """pgvector's input form: '[0.1,0.2,...]'. Never a Python repr (no spaces, no numpy)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def fetch_candidates(cur: Any, *, query_vec: Optional[list[float]], term: str, is_category: bool,
                     env: Optional[dict] = None) -> tuple[list[dict], str]:
    """Return (rows, backend_used). jsonb rows carry `embedding` (jsonb) for Python scoring; pgvector
    rows carry `cosine_sim` already computed by Postgres and `embedding` = None."""
    use = backend(env)
    like = f"%{term}%"
    if use == "pgvector" and query_vec:
        lit = vector_literal(query_vec)
        if is_category:
            cur.execute(_SQL_VEC_CATEGORY, (lit, like, lit))
        else:
            cur.execute(_SQL_VEC_SYMBOL, (lit, like, lit))
        return list(cur.fetchall()), "pgvector"
    if is_category:
        cur.execute(_SQL_JSONB_CATEGORY, (like,))
    else:
        cur.execute(_SQL_JSONB_SYMBOL, (like,))
    return list(cur.fetchall()), "jsonb"


def decode_jsonb_vector(raw: Any) -> Optional[list[float]]:
    """The jsonb column as the readers have always decoded it (list, JSON string, or dict of values)."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [float(x) for x in raw]
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return [float(x) for x in v] if isinstance(v, list) else None
    if isinstance(raw, dict):
        return [float(x) for x in raw.values()]
    return None


def similarity(row: dict, query_vec: Optional[list[float]], cosine_sim_fn, backend_used: str) -> Optional[float]:
    """pgvector rows already carry cosine_sim; jsonb rows are scored in Python with the caller's function."""
    if backend_used == "pgvector":
        s = row.get("cosine_sim")
        return float(s) if s is not None else None
    vec = decode_jsonb_vector(row.get("embedding"))
    if not vec or not query_vec:
        return None
    return float(cosine_sim_fn(query_vec, vec))
