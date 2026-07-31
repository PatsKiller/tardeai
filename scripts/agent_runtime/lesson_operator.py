"""Human-authorized lesson ratification (operator-only, separate from agent authority)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Tuple

from .operator_dispatch_http import OPERATOR_AUTH_ENV, _truthy
from .readiness import DISPATCH_DSN_ENV


def _blocker(env: Mapping[str, str]) -> str | None:
    if not _truthy(env, OPERATOR_AUTH_ENV):
        return "AGENT_RUNTIME_OPERATOR_AUTH is not set"
    if not str(env.get(DISPATCH_DSN_ENV, "")).strip():
        return "missing dispatch DSN"
    return None


def ratify_post(body: Mapping[str, Any] | None, *, root: Path, env: Mapping[str, str] | None = None) -> Tuple[int, dict[str, Any]]:
    env = os.environ if env is None else env
    blocker = _blocker(env)
    if blocker:
        return 403, {"ok": False, "contract": "agent-runtime-lesson-ratify-v1", "detail": blocker}
    if not body or not str(body.get("lesson_id") or "").strip():
        return 400, {"ok": False, "contract": "agent-runtime-lesson-ratify-v1", "detail": "lesson_id required"}
    lesson_id = str(body["lesson_id"]).strip()
    reviewer = str(body.get("reviewed_by") or "operator").strip()
    title = str(body.get("title") or f"Ratified {lesson_id}").strip()
    statement = str(body.get("statement") or "Operator-ratified lesson.").strip()
    try:
        from agent_runtime.persistence import PostgresPersistence

        dsn = str(env.get(DISPATCH_DSN_ENV, "")).strip()
        import importlib

        psycopg2 = importlib.import_module("psycopg2")

        def factory():
            conn = psycopg2.connect(dsn)
            conn.autocommit = False
            return conn

        persistence = PostgresPersistence(factory)
        persistence.record_lesson(
            lesson_id=lesson_id,
            lesson_version=int(body.get("lesson_version") or 1),
            lifecycle="RATIFIED",
            title=title,
            statement=statement,
            provenance={"ratified_via": "operator", "prior_lifecycle": "CANDIDATE"},
            created_by="reflection",
            reviewed_by=reviewer,
        )
        persistence.commit()
        return 200, {"ok": True, "contract": "agent-runtime-lesson-ratify-v1", "lesson_id": lesson_id, "lifecycle": "RATIFIED"}
    except Exception as exc:
        return 500, {"ok": False, "contract": "agent-runtime-lesson-ratify-v1", "detail": str(exc)}
