"""Archive-then-delete in verified batches, for db_retention.py.

Same archive format as db_retention.archive_rows (one row_to_json per line, gzip, under
<state>/archive/db_retention/<table>/), plus a sidecar manifest per file carrying the row
count and the sha256 of the .jsonl.gz bytes (RetentionArchiveManifest@v1).

A batch is one transaction:
  1. lock the next <= batch_rows keys matching the predicate (ORDER BY key, FOR UPDATE);
  2. stream those rows to <stamp>-<label>-b<NNNN>.jsonl.gz (server-side cursor), fsync;
  3. write the manifest (rows, sha256, bytes, key range) and append a tripwire record to
     <archive_dir>/TRIPWIRE.jsonl (RetentionArchiveTripwire@v1; reader: lib/retention_tripwire.py);
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
    """Write the sidecar manifest, then the tripwire record (both BEFORE the caller's DELETE).

    Every caller (db_retention.archive_rows, archive_then_delete_batches) goes through here, so this
    is the one place the tripwire half of AGENTS.md §0 rule 6 is written. A tripwire write that
    fails raises: the caller rolls back and the rows are not deleted.
    """
    writer = str(fields.pop("writer", None) or "db_retention")
    doc = {"schema": MANIFEST_SCHEMA, "file": path.name, "writer": writer,
           "created_at": datetime.now(timezone.utc).isoformat(), **fields}
    mp = manifest_path(path)
    mp.write_text(json.dumps(doc, default=str, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    write_tripwire_record(path, manifest=mp, table=fields.get("table"), rows=fields.get("rows"),
                          sha256=fields.get("sha256"), label=fields.get("label"), writer=writer,
                          kind=str(fields.get("kind") or "rows"))
    return doc


# ── Tripwire (2026-10-11) ────────────────────────────────────────────────────
# One RetentionArchiveTripwire@v1 line per archive file, appended to <archive_dir>/TRIPWIRE.jsonl
# (i.e. <state>/archive/db_retention/<table>/TRIPWIRE.jsonl). The reader is
# scripts/lib/retention_tripwire.py, run nightly by scripts/report_db_hygiene.py: any live reference
# to the archive becomes an ARCHIVE_TRIPWIRE P1 incident through the existing fan-in.
TRIPWIRE_SCHEMA = "RetentionArchiveTripwire@v1"
TRIPWIRE_NAME = "TRIPWIRE.jsonl"


def tripwire_path(archive_file: Path) -> Path:
    return Path(archive_file).parent / TRIPWIRE_NAME


def write_tripwire_record(archive_file: Path, *, manifest: Path | None = None, table: Any = None, rows: Any = None,
                          sha256: Any = None, label: Any = None, writer: str = "db_retention",
                          kind: str = "rows") -> dict:
    rec = {"schema": TRIPWIRE_SCHEMA, "kind": kind, "writer": writer, "table": table, "label": label,
           "archive": str(archive_file), "manifest": str(manifest) if manifest else None, "rows": rows,
           "sha256": sha256, "archived_at": datetime.now(timezone.utc).isoformat(),
           "fires_on": "any live reference to archive/db_retention or archive/file_prune (scripts/lib/retention_tripwire.py, "
                       "read nightly by report_db_hygiene.py -> incident fan-in)"}
    tp = tripwire_path(archive_file)
    with open(tp, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rec


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
                                key: str = "id", stamp: str | None = None, writer: str = "db_retention") -> dict:
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
                       params=[str(p) for p in params], writer=writer)
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


# ── Archive roots (2026-10-11, retention-all-managed) ────────────────────────
# One place that knows where archives live, so every writer (db_retention, the hermes librarian, file
# prunes) lands under the tripwire reader's roots (lib/retention_tripwire.py) without naming the path.
def state_root() -> Path:
    base = os.getenv("TRADEAI_STATE_ROOT")
    return Path(base) if base else Path.home() / "trade-ai-releases" / "persistent-state"


def archive_root() -> Path:
    """<state>/archive/db_retention — row archives, one sub-directory per table."""
    return state_root() / "archive" / "db_retention"


def file_archive_root() -> Path:
    """<state>/archive/file_prune — file-prune archives, one sub-directory per prune label."""
    return state_root() / "archive" / "file_prune"


# ── File prunes: archive-then-unlink (2026-10-11) ────────────────────────────
# A FILE_PRUNE target is tarred (gzip) with a per-member sha256 manifest and a tripwire record, the tar
# is re-read and every member re-hashed against the source file, and only then is the source unlinked.
# A mismatch unlinks nothing (ArchiveVerifyError). Same rule-6 shape as the row archives.
FILE_MANIFEST_SCHEMA = "FilePruneArchiveManifest@v1"


def _sha256_bytes_of(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def archive_files_then_unlink(files: Sequence[Path], *, base_dir: Path, archive_dir: Path, label: str,
                              stamp: str | None = None, writer: str = "db_retention") -> dict:
    """Tar + verify + unlink. Returns {archive, files, bytes, sha256, unlinked}. Raises ArchiveVerifyError."""
    import tarfile

    files = [Path(f) for f in files]
    out: dict = {"label": label, "files": 0, "unlinked": 0, "archive": None}
    if not files:
        return out
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{stamp}-{label}.tar.gz"
    members = []
    base_dir = Path(base_dir)
    with open(path, "wb") as raw:
        with tarfile.open(fileobj=raw, mode="w:gz", compresslevel=COMPRESSLEVEL) as tar:
            for f in files:
                arc = f.relative_to(base_dir).as_posix() if f.is_relative_to(base_dir) else f.name
                sha, size = _sha256_bytes_of(f)
                st = f.stat()
                tar.add(str(f), arcname=arc, recursive=False)
                members.append({"name": arc, "source": str(f), "sha256": sha, "bytes": size,
                                "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
        raw.flush()
        os.fsync(raw.fileno())
    sha = _sha256_file(path)
    nbytes = path.stat().st_size
    write_manifest(path, table=None, label=label, kind="files", rows=len(members), sha256=sha, bytes=nbytes,
                   base_dir=str(base_dir), members=members, schema_files=FILE_MANIFEST_SCHEMA, writer=writer)
    ok, why = verify_file_archive(path, expected_sha256=sha, members=members)
    if not ok:
        raise ArchiveVerifyError(f"{label}: {why} (archive {path}); unlink refused")
    for m in members:
        Path(m["source"]).unlink()
    out.update(archive=str(path), files=len(members), bytes=nbytes, sha256=sha, unlinked=len(members),
               source_bytes=sum(m["bytes"] for m in members))
    return out


def verify_file_archive(path: Path, *, expected_sha256: str, members: Sequence[dict]) -> tuple[bool, str]:
    """Re-read the tar from disk: archive sha256, member set, and every member's sha256."""
    import tarfile

    if not Path(path).exists():
        return False, "archive file missing"
    if _sha256_file(path) != expected_sha256:
        return False, "archive sha256 mismatch"
    want = {m["name"]: m["sha256"] for m in members}
    seen: dict = {}
    try:
        with tarfile.open(path, mode="r:gz") as tar:
            for ti in tar:
                fh = tar.extractfile(ti)
                if fh is None:
                    continue
                seen[ti.name] = hashlib.sha256(fh.read()).hexdigest()
    except (OSError, tarfile.TarError, EOFError) as exc:
        return False, f"archive unreadable: {exc}"
    if set(seen) != set(want):
        return False, "archived member set differs from the selected files"
    bad = [n for n in want if seen[n] != want[n]]
    if bad:
        return False, f"member sha256 mismatch: {bad[:3]}"
    return True, "ok"


# ── Projection and growth (2026-10-11) ───────────────────────────────────────
def gz_bytes_per_row(rows: Sequence[Any]) -> float | None:
    """Compressed archive bytes per row for a sample of row_to_json values (same codec/level as the archive)."""
    rows = list(rows)
    if not rows:
        return None
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=COMPRESSLEVEL) as gz:
        for r in rows:
            obj = r[0] if isinstance(r, (tuple, list)) else r
            gz.write((json.dumps(obj, default=str) + "\n").encode("utf-8"))
    return len(buf.getvalue()) / len(rows)


ARCHIVE_USAGE_SCHEMA = "RetentionArchiveUsage@v1"


def archive_usage(root: Path | None = None, *, now: datetime | None = None, window_days: int = 30) -> dict:
    """Read-only size/age report of <state>/archive/{db_retention,file_prune,db_trim,comms_lifecycle}: per store bytes, files,
    oldest/newest mtime, and bytes written in the last ``window_days``. Never deletes anything."""
    root = Path(root) if root is not None else state_root() / "archive"
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    cutoff = now_ts - window_days * 86400
    stores: dict = {}
    for top in ("db_retention", "file_prune", "db_trim", "comms_lifecycle"):
        base = root / top
        if not base.is_dir():
            continue
        for sub in sorted(p for p in base.iterdir() if p.is_dir()) or [base]:
            key = f"{top}/{sub.name}" if sub != base else top
            s = {"bytes": 0, "files": 0, "bytes_recent": 0, "oldest": None, "newest": None}
            for f in sub.rglob("*"):
                if not f.is_file():
                    continue
                st = f.stat()
                s["bytes"] += st.st_size
                s["files"] += 1
                if st.st_mtime >= cutoff:
                    s["bytes_recent"] += st.st_size
                s["oldest"] = st.st_mtime if s["oldest"] is None else min(s["oldest"], st.st_mtime)
                s["newest"] = st.st_mtime if s["newest"] is None else max(s["newest"], st.st_mtime)
            for k in ("oldest", "newest"):
                if s[k] is not None:
                    s[k] = datetime.fromtimestamp(s[k], timezone.utc).isoformat()
            stores[key] = s
    total = sum(s["bytes"] for s in stores.values())
    recent = sum(s["bytes_recent"] for s in stores.values())
    return {"schema": ARCHIVE_USAGE_SCHEMA, "root": str(root), "window_days": window_days, "stores": stores,
            "total_bytes": total, "recent_bytes": recent,
            "recent_gb_per_month": round(recent / 1e9 * 30.0 / window_days, 3)}


def archive_growth_findings(usage: dict, *, cap_gb_month: float | None, total_budget_gb: float | None = None,
                            disk_free_bytes: int | None = None, disk_floor_gb: float = 20.0) -> list[dict]:
    """DbHygieneReport@v1 findings for the archive store. Report only: archives are never deleted here
    (AGENTS.md §0 rule 6); moving them off-box is an operator decision (§17, §18)."""
    out: list[dict] = []
    win = float(usage.get("window_days") or 30)
    rate = float(usage.get("recent_bytes") or 0) / 1e9 * 30.0 / win
    total_gb = float(usage.get("total_bytes") or 0) / 1e9
    if cap_gb_month and rate > float(cap_gb_month):
        top = sorted(usage.get("stores", {}).items(), key=lambda kv: -kv[1]["bytes_recent"])[:3]
        out.append({"code": "ARCHIVE_GROWTH", "item": "archive", "severity": "P2",
                    "detail": f"{rate:.2f} GB/month over the last {usage.get('window_days')} d > cap {cap_gb_month} GB/month; "
                              "top: " + ", ".join(f"{k} {v['bytes_recent']/1e9:.2f} GB" for k, v in top)})
    if total_budget_gb and total_gb > float(total_budget_gb):
        out.append({"code": "ARCHIVE_GROWTH", "item": "archive_total", "severity": "P2",
                    "detail": f"archive holds {total_gb:.2f} GB > budget {total_budget_gb} GB on the DB disk; "
                              "off-box copy is an operator decision (AGENTS.md §17)"})
    if disk_free_bytes is not None and disk_free_bytes < disk_floor_gb * 1e9:
        out.append({"code": "ARCHIVE_GROWTH", "item": "disk_free", "severity": "P2",
                    "detail": f"{disk_free_bytes/1e9:.1f} GB free < {disk_floor_gb} GB floor; archives share the DB disk"})
    return out


# ── One call for every registered purge (2026-10-11, retention-all-managed) ──
# Any job that deletes rows by age or condition calls this instead of a bare DELETE: a dry run only
# counts (SELECT), an apply archives + verifies + deletes in batches (archive_then_delete_batches), and
# ``archive=False`` keeps the inherited hard DELETE as an explicit, logged rollback lever. The owner and
# class of every caller is declared in config/data_retention_policy.json ``purge_paths``.
DEFAULT_MANAGED_MAX_ROWS = 500000


def managed_purge(conn, *, table: str, where_sql: str, params: Sequence[Any] = (), label: str, writer: str,
                  apply: bool, archive: bool = True, key: str = "id", batch_rows: int = 20000,
                  max_rows: int = DEFAULT_MANAGED_MAX_ROWS, archive_dir: Path | None = None) -> dict:
    """``where_sql`` uses the alias ``t``. Returns {table, label, eligible, deleted, archived, mode, ...}."""
    cur = conn.cursor()
    cur.execute(f"SELECT count(*) FROM {table} t WHERE {where_sql}", tuple(params))
    eligible = int(cur.fetchone()[0] or 0)
    out = {"table": table, "label": label, "writer": writer, "eligible": eligible, "deleted": 0, "archived": 0,
           "archive": bool(archive), "mode": "apply" if apply else "dry_run"}
    if not apply or eligible == 0:
        return out
    if archive:
        res = archive_then_delete_batches(conn, table=table, where_sql=where_sql, params=params, label=label,
                                          archive_dir=Path(archive_dir) if archive_dir else archive_root() / table,
                                          batch_rows=batch_rows, max_rows=max_rows, key=key, writer=writer)
        out.update(deleted=res["rows_deleted"], archived=res["rows_archived"], batches=len(res["batches"]),
                   cap_reached=res.get("cap_reached", False),
                   archives=[b["path"] for b in res["batches"]])
        return out
    cur.execute(f"DELETE FROM {table} t WHERE {where_sql}", tuple(params))
    out["deleted"] = int(cur.rowcount)
    conn.commit()
    return out
