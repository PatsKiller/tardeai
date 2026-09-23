"""Durable mirror for gateway cron jobs.json (Stage 4 residual).

Gateway 2026.6+ persists cron rows in its state SQLite and treats
``jobs.json`` as a store *key*, not a flushed file. Operators and Maria
reminders still expect a durable ``jobs.json`` on disk.

This helper:

1. Atomically flushes a jobs payload to ``jobs.json`` (tmp + os.replace).
2. On startup, if ``jobs.json`` is missing, recovers from ``.migrated`` /
   ``.bak*`` candidates — **without** auto-merging divergent copies
   (AGENTS.md §0.5): when more than one candidate exists with different
   content, report both and require an operator pick.

AUTHORITY: host infra only. No broker / MBI_BEHAVIOR writes.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

SCHEMA = "GatewayCronJobsMirror@v1"
DEFAULT_CRON_DIR = Path.home() / ".openclaw" / "cron"
PRIMARY_NAME = "jobs.json"


@dataclass
class RecoverReport:
    schema: str = SCHEMA
    ok: bool = False
    action: str = "noop"
    primary: Optional[str] = None
    recovered_from: Optional[str] = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    divergent: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_cron_dir(cron_dir: Optional[Path] = None) -> Path:
    return Path(cron_dir) if cron_dir is not None else DEFAULT_CRON_DIR


def primary_path(cron_dir: Optional[Path] = None) -> Path:
    return resolve_cron_dir(cron_dir) / PRIMARY_NAME


def list_recovery_candidates(cron_dir: Optional[Path] = None) -> list[Path]:
    """Prefer ``.migrated`` / ``.migrated.*``, then newest ``.bak*`` by mtime."""
    d = resolve_cron_dir(cron_dir)
    if not d.is_dir():
        return []
    out: list[Path] = []
    migrated = d / f"{PRIMARY_NAME}.migrated"
    if migrated.is_file():
        out.append(migrated)
    # Doctor may archive as jobs.json.migrated.2, .3, …
    out.extend(
        sorted(
            (p for p in d.glob(f"{PRIMARY_NAME}.migrated.*") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    )
    baks = sorted(
        (p for p in d.glob(f"{PRIMARY_NAME}.bak*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out.extend(baks)
    # Stable unique by resolved path
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def atomic_write_jobs_json(
    payload: dict[str, Any] | list[Any],
    *,
    cron_dir: Optional[Path] = None,
    path: Optional[Path] = None,
) -> Path:
    """Atomically flush jobs.json (write temp in same dir, then os.replace)."""
    target = Path(path) if path is not None else primary_path(cron_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    data = text.encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(
        prefix=".jobs.json.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def load_jobs_payload(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"version": 1, "jobs": raw}
    if isinstance(raw, dict):
        jobs = raw.get("jobs")
        if jobs is None:
            raise ValueError(f"unsupported jobs shape at {path}")
        if not isinstance(jobs, list):
            raise ValueError(f"jobs must be a list at {path}")
        out = dict(raw)
        out.setdefault("version", 1)
        return out
    raise ValueError(f"unsupported jobs JSON type at {path}")


def recover_jobs_json_if_missing(
    *,
    cron_dir: Optional[Path] = None,
    dry_run: bool = False,
    operator_pick: Optional[str] = None,
) -> RecoverReport:
    """If primary jobs.json is missing, restore from .migrated / .bak*.

    When multiple candidates disagree on content and no ``operator_pick`` is
    given, report ``divergent=True`` and do not write (AGENTS.md §0.5).
    """
    d = resolve_cron_dir(cron_dir)
    primary = primary_path(d)
    report = RecoverReport(primary=str(primary))
    if primary.is_file():
        report.ok = True
        report.action = "already_present"
        return report

    candidates = list_recovery_candidates(d)
    report.candidates = []
    payloads: list[tuple[Path, bytes, str, dict[str, Any]]] = []
    for c in candidates:
        try:
            blob = c.read_bytes()
            digest = _sha256_bytes(blob)
            payload = load_jobs_payload(c)
            payloads.append((c, blob, digest, payload))
            report.candidates.append(
                {
                    "path": str(c),
                    "sha256": digest,
                    "bytes": len(blob),
                    "mtime": c.stat().st_mtime,
                    "job_count": len(payload.get("jobs") or []),
                }
            )
        except Exception as exc:  # noqa: BLE001 — candidate inventory must not raise
            report.candidates.append({"path": str(c), "error": str(exc)})

    if not payloads:
        report.ok = False
        report.action = "missing_no_candidate"
        report.error = "jobs.json missing and no readable .migrated/.bak candidate"
        return report

    digests = {d for _p, _b, d, _pl in payloads}
    if len(digests) > 1 and not operator_pick:
        report.ok = False
        report.action = "divergent_candidates"
        report.divergent = True
        report.error = (
            "multiple recovery candidates with different content; "
            "pass operator_pick=<path> after reviewing both"
        )
        return report

    chosen: tuple[Path, bytes, str, dict[str, Any]]
    if operator_pick:
        pick = Path(operator_pick).expanduser().resolve()
        matched = [t for t in payloads if t[0].resolve() == pick]
        if not matched:
            report.ok = False
            report.action = "operator_pick_miss"
            report.error = f"operator_pick not among candidates: {pick}"
            return report
        chosen = matched[0]
    else:
        chosen = payloads[0]

    report.recovered_from = str(chosen[0])
    if dry_run:
        report.ok = True
        report.action = "would_recover"
        return report

    atomic_write_jobs_json(chosen[3], path=primary)
    report.ok = True
    report.action = "recovered"
    return report


def flush_jobs_mirror(
    jobs: list[dict[str, Any]] | dict[str, Any],
    *,
    cron_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Public create/update helper: atomically flush jobs.json after a job create."""
    if isinstance(jobs, list):
        payload: dict[str, Any] = {"version": 1, "jobs": jobs}
    else:
        payload = dict(jobs)
        payload.setdefault("version", 1)
        payload.setdefault("jobs", [])
    target = primary_path(cron_dir)
    if dry_run:
        return {
            "schema": SCHEMA,
            "ok": True,
            "dry_run": True,
            "would_write": str(target),
            "job_count": len(payload.get("jobs") or []),
        }
    written = atomic_write_jobs_json(payload, path=target)
    return {
        "schema": SCHEMA,
        "ok": True,
        "dry_run": False,
        "path": str(written),
        "job_count": len(payload.get("jobs") or []),
        "sha256": _sha256_bytes(written.read_bytes()),
    }


__all__ = [
    "SCHEMA",
    "DEFAULT_CRON_DIR",
    "RecoverReport",
    "atomic_write_jobs_json",
    "flush_jobs_mirror",
    "list_recovery_candidates",
    "load_jobs_payload",
    "primary_path",
    "recover_jobs_json_if_missing",
    "resolve_cron_dir",
]
