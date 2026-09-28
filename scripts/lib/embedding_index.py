"""embedding_index.py — local embeddings for ladder step 7 (Wave 5 I-W5-1; 03 §3 step 7, 12 SW-1).

Uses the loopback Ollama endpoint through the existing ``ollama_embedding_policy`` (loopback only, one
allowed model, no cloud). Rows go to ``intelligence.embedding`` (pgvector column ``vec`` exists on
production). Everything is fail-soft and opt-in:

* ``available(env)`` — True only when the model answers on loopback (``TRADEAI_EMBEDDINGS=1`` and the
  policy accepts the endpoint); otherwise ladder step 7 keeps reporting ``not_installed``.
* ``index(ref, text, subject_guid)`` — embed + upsert (no-op when unavailable).
* ``semantic(question, subject_guid, k)`` — nearest refs by cosine distance for the subject (or global).

The operator installs the model (``ollama pull nomic-embed-text``, item I-W5-1, NEEDS_LOCAL); until then
this module only ever returns "not installed". Authority READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import os
from typing import Any

TENANT = "tradeai:tenant:primary"
DIMS = 768


def enabled(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("TRADEAI_EMBEDDINGS", "0")).lower() in ("1", "true", "on")


def _policy():
    try:
        import ollama_embedding_policy as oep  # type: ignore
    except ImportError:
        from scripts.lib import ollama_embedding_policy as oep  # type: ignore
    return oep


def embed(text: str, env: dict | None = None) -> list[float] | None:
    if not enabled(env):
        return None
    try:
        oep = _policy()
        vec = oep.embed(text)
        return list(vec) if vec else None
    except Exception:  # noqa: BLE001
        return None


def available(env: dict | None = None) -> bool:
    return embed("probe", env) is not None


def _conn():
    try:
        import db_adapter  # type: ignore
        c = db_adapter._get_conn()
        with c.cursor() as cur:
            cur.execute("SET app.tenant_id = %s", (TENANT,))
        return c
    except Exception:  # noqa: BLE001
        return None


def index(ref: str, text: str, *, subject_guid: str | None = None, source_changed_at: str | None = None,
          env: dict | None = None, conn: Any = None) -> dict:
    env = os.environ if env is None else env
    vec = embed(text, env)
    if vec is None:
        return {"pg": "not_installed", "ref": ref}
    c = conn or _conn()
    if c is None:
        return {"pg": "absent", "ref": ref}
    try:
        oep = _policy()
        model = getattr(oep, "ALLOWED_MODEL", "nomic-embed-text")
        with c.cursor() as cur:
            cur.execute("INSERT INTO intelligence.embedding (ref, tenant_id, subject_guid, model, dims, source_changed_at, vec) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s::vector) ON CONFLICT (ref) DO UPDATE SET subject_guid = EXCLUDED.subject_guid, "
                        "model = EXCLUDED.model, dims = EXCLUDED.dims, source_changed_at = EXCLUDED.source_changed_at, vec = EXCLUDED.vec, projected_at = now()",
                        (ref, TENANT, subject_guid, model, len(vec), source_changed_at, "[" + ",".join(f"{x:.6f}" for x in vec) + "]"))
        c.commit()
        return {"pg": "written", "ref": ref, "dims": len(vec)}
    except Exception as exc:  # noqa: BLE001
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"pg": "error", "ref": ref, "error": f"{type(exc).__name__}:{str(exc)[:120]}"}


def semantic(question: str, *, subject_guid: str | None = None, k: int = 5, env: dict | None = None, conn: Any = None) -> list[dict]:
    env = os.environ if env is None else env
    vec = embed(question, env)
    if vec is None:
        return []
    c = conn or _conn()
    if c is None:
        return []
    try:
        with c.cursor() as cur:
            q = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
            if subject_guid:
                cur.execute("SELECT ref, subject_guid, vec <=> %s::vector AS dist FROM intelligence.embedding WHERE subject_guid = %s ORDER BY dist LIMIT %s", (q, subject_guid, k))
            else:
                cur.execute("SELECT ref, subject_guid, vec <=> %s::vector AS dist FROM intelligence.embedding ORDER BY dist LIMIT %s", (q, k))
            rows = cur.fetchall()
        c.rollback()
        return [{"ref": r[0], "subject_guid": r[1], "distance": float(r[2])} for r in rows]
    except Exception:  # noqa: BLE001
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return []
