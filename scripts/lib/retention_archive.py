"""Archive-then-delete in verified batches, for db_retention.py.

Same archive format as db_retention.archive_rows (one row_to_json per line, gzip, under
<state>/archive/db_retention/<table>/), plus a sidecar manifest per file carrying the row
count and the sha256 of the .jsonl.gz bytes (RetentionArchiveManifest@v1).

A batch is one transaction:
  1. lock the next <= batch_rows keys matching the predicate (ORDER BY key, FOR UPDATE);
  2. stream those rows to <stamp>-<label>-b<NNNN>.jsonl.gz (server-side cursor), fsync;
  3. write the manifest (rows, sha256, bytes, key range);
  4. VERIFY by re-reading the file from disk: sha256 equals the manifest, line count equals
     the locked key count, and the set of archived keys equals the locked key set;
  5. DELETE exactly those keys; the rowcount must equal the archived count;
  6. COMMIT. Any mismatch rolls the batch back and stops the run (typed ArchiveVerifyError).

Nothing here decides WHAT to delete: callers pass a predicate from the governed registry
(config/data_retention_policy.json) or an operator-invoked one-time mode.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

MANIFEST_SCHEMA = "RetentionArchiveManifest@v1"
COMPRESSLEVEL = 6


class ArchiveVerifyError(RuntimeError):
    """The archive re-read did not match what was locked; the batch was rolled back."""

    code = "ARCHIVE_VERIFY_FAILED"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_jsonl_gz(rows, path: Path) -> tuple[int, str, int]:
    """Write an iterable of (row_json,) tuples (or dicts) as gzip jsonl; fsync. Returns (rows, sha256, bytes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=COMPRESSLEVEL) as gz:
            text = io.TextIOWrapper(gz, encoding="utf-8")
            for row in rows:
                obj = row[0] if isinstance(row, (tuple, list)) else row
                text.write(json.dumps(obj, default=str) + "\n")
                n += 1
            text.flush()
            text.detach()
        raw.flush()
        os.fsync(raw.fileno())
    return n, _sha256_file(path), path.stat().st_size


def manifest_path(path: Path) -> Path:
    return Path(str(path) + ".manifest.json")


def write_manifest(path: Path, **fields: Any) -> dict:
    doc = {"schema": MANIFEST_SCHEMA, "file": path.name,
           "created_at": datetime.now(timezone.utc).isoformat(), **fields}
    mp = manifest_path(path)
    mp.write_text(json.dumps(doc, default=str, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return doc


def verify_archive(path: Path, *, expected_rows: int, expected_sha256: str,
                   key: str | None = None, expected_keys: Sequence[Any] | None = None) -> tuple[bool, str]:
    """Re-read the archive from disk. Returns (ok, reason)."""
    if not path.exists():
        return False, "archive file missing"
    sha = _sha256_file(path)
    if sha != expected_sha256:
        return False, f"sha256 mismatch {sha} != {expected_sha256}"
    mp = manifest_path(path)
    try:
        man = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"manifest unreadable: {exc}"
    if man.get("sha256") != expected_sha256 or int(man.get("rows", -1)) != int(expected_rows):
        return False, "manifest does not match the archive"
    n = 0
    seen = set()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                n += 1
                if key is not None:
                    seen.add(json.loads(line).get(key))
    except (OSError, ValueError, EOFError) as exc:
        return False, f"archive unreadable: {exc}"
    if n != int(expected_rows):
        return False, f"row count {n} != {expected_rows}"
    if key is not None and expected_keys is not None and seen != set(expected_keys):
        return False, "archived keys differ from the locked keys"
    return True, "ok"


def estimate(conn, *, table: str, where_sql: str, params: Sequence[Any] = (),
             key: str = "id", sample_rows: int = 500) -> dict:
    """Read-only: matching rows, stored bytes (pg_column_size), and an archive-size estimate
    from gzip-compressing a sample of matching rows in key order."""
    cur = conn.cursor()
    cur.execute(f"SELECT count(*), COALESCE(sum(pg_column_size(t.*)),0) FROM {table} t WHERE {where_sql}",
                tuple(params))
    rows, stored = cur.fetchone()
    est = None
    if rows and sample_rows > 0:
        cur.execute(f"SELECT row_to_json(t) FROM {table} t WHERE {where_sql} ORDER BY t.{key} LIMIT %s",
                    (*params, int(sample_rows)))
        sample = cur.fetchall()
        if sample:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=COMPRESSLEVEL) as gz:
                for (obj,) in sample:
                    gz.write((json.dumps(obj, default=str) + "\n").encode("utf-8"))
            est = int(len(buf.getvalue()) / len(sample) * int(rows))
    cur.close()
    return {"rows": int(rows or 0), "stored_bytes": int(stored or 0), "est_archive_bytes": est,
            "sample_rows": min(int(sample_rows), int(rows or 0))}


def archive_then_delete_batches(conn, *, table: str, where_sql: str, params: Sequence[Any] = (),
                                label: str, archive_dir: Path, batch_rows: int, max_rows: int,
                                key: str = "id", stamp: str | None = None) -> dict:
    """Apply mode. Returns a result dict; raises ArchiveVerifyError after rolling back a bad batch."""
    if batch_rows <= 0 or max_rows <= 0:
        raise ValueError("batch_rows and max_rows must be positive")
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = Path(archive_dir)
    out: dict = {"table": table, "label": label, "batches": [], "rows_archived": 0, "rows_deleted": 0}
    done = 0
    idx = 0
    while done < max_rows:
        want = min(batch_rows, max_rows - done)
        cur = conn.cursor()
        cur.execute(f"SELECT t.{key} FROM {table} t WHERE {where_sql} ORDER BY t.{key} LIMIT %s FOR UPDATE",
                    (*params, want))
        keys = [r[0] for r in cur.fetchall()]
        if not keys:
            conn.rollback()
            break
        idx += 1
        path = archive_dir / f"{stamp}-{label}-b{idx:04d}.jsonl.gz"
        named = conn.cursor(name=f"retention_archive_{label}_{idx}")
        named.itersize = 1000
        named.execute(f"SELECT row_to_json(t) FROM {table} t WHERE t.{key} = ANY(%s) ORDER BY t.{key}", (keys,))
        n, sha, nbytes = write_jsonl_gz(named, path)
        named.close()
        write_manifest(path, table=table, label=label, batch=idx, rows=n, sha256=sha, bytes=nbytes,
                       key=key, key_min=min(keys), key_max=max(keys), predicate=where_sql,
                       params=[str(p) for p in params])
        ok, why = (False, f"archived {n} != locked {len(keys)}") if n != len(keys) else verify_archive(
            path, expected_rows=n, expected_sha256=sha, key=key, expected_keys=keys)
        if not ok:
            conn.rollback()
            out["status"] = "verify_failed"
            out["error"] = why
            raise ArchiveVerifyError(f"{label} batch {idx}: {why} (archive {path}); delete refused, rolled back")
        cur.execute(f"DELETE FROM {table} t WHERE t.{key} = ANY(%s)", (keys,))
        if cur.rowcount != n:
            conn.rollback()
            out["status"] = "delete_mismatch"
            raise ArchiveVerifyError(f"{label} batch {idx}: deleted {cur.rowcount} != archived {n}; rolled back")
        conn.commit()
        cur.close()
        out["batches"].append({"batch": idx, "rows": n, "bytes": nbytes, "sha256": sha, "path": str(path)})
        out["rows_archived"] += n
        out["rows_deleted"] += n
        done += n
        if n < want:
            break
    out["status"] = "ok"
    out["cap_reached"] = done >= max_rows
    return out
