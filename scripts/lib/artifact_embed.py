"""Decouple artifact persistence from embedding.

Acquisition always persists first. HTTP 503 → ACQUIRED_EMBED_PENDING, never
discard / refetch / paid LLM.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError

AUTHORITY = "READ_ONLY_ADVISORY"
QUEUE = "data/cio/artifact_embed_retry.jsonl"
EMBEDDED = "EMBEDDED"
PENDING = "ACQUIRED_EMBED_PENDING"
ACQUIRED = "ACQUIRED"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def queue_path(root: Path | str) -> Path:
    return Path(root) / QUEUE


def persist_retry(root: Path | str, artifact_guid: str, error: str, attempt: int = 1) -> dict[str, Any]:
    rec = {
        "schema": "ArtifactEmbedRetry@v1",
        "artifact_guid": artifact_guid,
        "attempt": attempt,
        "last_error": str(error)[:240],
        "next_retry": (datetime.now(timezone.utc) + timedelta(minutes=min(30, 5 * attempt))).replace(microsecond=0).isoformat(),
        "status": PENDING,
        "authority": AUTHORITY,
        "as_of": _now(),
    }
    path = queue_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if artifact_guid in existing and f'"attempt": {attempt}' in existing:
        return rec  # idempotent
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def embed_artifact(
    root: Path | str,
    artifact: dict[str, Any],
    *,
    embed_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Attempt embedding after the artifact is already persisted."""
    guid = str(artifact.get("research_artifact_guid") or artifact.get("artifact_id") or "")
    text = " ".join(str(artifact.get(k) or "") for k in ("title", "summary", "symbol"))[:2000]
    if embed_fn is None:
        return {"status": ACQUIRED, "artifact_guid": guid, "note": "embed_deferred"}
    try:
        embed_fn(text)
        return {"status": EMBEDDED, "artifact_guid": guid}
    except HTTPError as e:
        if getattr(e, "code", None) == 503:
            rec = persist_retry(root, guid, f"HTTP 503:{e}")
            rec["acquired_artifact_preserved"] = True
            return rec
        rec = persist_retry(root, guid, str(e))
        rec["acquired_artifact_preserved"] = True
        return rec
    except Exception as e:
        rec = persist_retry(root, guid, f"{type(e).__name__}:{e}")
        rec["acquired_artifact_preserved"] = True
        return rec
