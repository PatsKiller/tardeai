"""Private storage layout for prospectuses, plus the index, queue and universe files.

    <state>/data/prospectus/<SYMBOL>/<UTC-stamp>/{prospectus.json, .html, .pdf, .docx, charts/*.png}
    <state>/data/prospectus/<SYMBOL>/versions.json   [{version, generated_at, model, cost_usd}] newest first
    <state>/data/prospectus/index.json               latest per symbol (ProspectusIndex@v1)
    <state>/data/prospectus/queue.json               pending rewrites (ProspectusQueue@v1)
    <state>/data/prospectus/universe.json            holdings + watch symbols seen by the last planning run

Every write is atomic (temp + rename) and every read here is one small file, so the portfolio server's
index/list reads never load all prospectuses (MemoryHigh 1.6 GB). Nothing is ever deleted.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Iterator

from . import INDEX_SCHEMA, QUEUE_SCHEMA

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")
STAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")
FILE_KINDS = {"html": "prospectus.html", "pdf": "prospectus.pdf", "docx": "prospectus.docx"}
STATUSES = ("ready", "partial", "queued", "running", "failed", "missing", "blocked_data")


def norm_symbol(symbol: Any) -> str | None:
    sym = str(symbol or "").strip().upper()
    return sym if SYMBOL_RE.match(sym) else None


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def base_dir(state_root: Path | str, cfg: dict | None = None) -> Path:
    return Path(state_root) / str((cfg or {}).get("storage_rel") or "data/prospectus")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def locked(base: Path, name: str = ".lock") -> Iterator[None]:
    base.mkdir(parents=True, exist_ok=True)
    with (base / name).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# ── versions ──────────────────────────────────────────────────────────────────────────────────────────────────
def write_version(base: Path, symbol: str, version: str, doc: dict, files: dict[str, bytes]) -> Path:
    """Write one complete version directory atomically, then record it in versions.json."""
    sym = norm_symbol(symbol)
    if not sym or not STAMP_RE.match(version):
        raise ValueError("invalid symbol or version")
    final = base / sym / version
    if final.exists():
        raise FileExistsError(str(final))
    tmp = base / sym / f".{version}.partial"
    if tmp.exists():
        shutil.move(str(tmp), str(base / sym / f".{version}.abandoned.{os.getpid()}"))  # never deleted
    (tmp / "charts").mkdir(parents=True)
    (tmp / "prospectus.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
                                         encoding="utf-8")
    for rel, data in files.items():
        target = tmp / rel
        if target.resolve().parent not in {tmp.resolve(), (tmp / "charts").resolve()}:
            raise ValueError("file outside version directory")
        target.write_bytes(data)
    os.replace(tmp, final)
    with locked(base / sym, ".versions.lock"):
        rows = versions(base, sym)
        rows.insert(0, {"version": version, "generated_at": doc.get("generated_at"), "model": doc.get("model"),
                        "cost_usd": doc.get("cost_usd"), "mode": doc.get("mode")})
        write_json(base / sym / "versions.json", rows)
    return final


def versions(base: Path, symbol: str) -> list[dict]:
    sym = norm_symbol(symbol)
    if not sym:
        return []
    rows = _read_json(base / sym / "versions.json", [])
    return [r for r in rows if isinstance(r, dict) and STAMP_RE.match(str(r.get("version") or ""))]


def version_dir(base: Path, symbol: str, version: str | None = None) -> Path | None:
    sym = norm_symbol(symbol)
    if not sym:
        return None
    if version is None:
        rows = versions(base, sym)
        version = rows[0]["version"] if rows else None
    if not version or not STAMP_RE.match(str(version)):
        return None
    path = base / sym / str(version)
    return path if (path / "prospectus.json").is_file() else None


def read_prospectus(base: Path, symbol: str, version: str | None = None) -> dict | None:
    path = version_dir(base, symbol, version)
    return _read_json(path / "prospectus.json", None) if path else None


def file_path(base: Path, symbol: str, kind: str, version: str | None = None) -> Path | None:
    """The on-disk file for one rendered format, confined to the version directory."""
    name = FILE_KINDS.get(kind)
    path = version_dir(base, symbol, version)
    if not name or path is None:
        return None
    target = (path / name).resolve()
    if target.parent != path.resolve() or not target.is_file():
        return None
    return target


# ── index ─────────────────────────────────────────────────────────────────────────────────────────────────────
def read_index(base: Path) -> dict:
    doc = _read_json(base / "index.json", None)
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        return {"schema": INDEX_SCHEMA, "updated_at": None, "items": {}}
    return doc


def update_index(base: Path, symbol: str, **fields: Any) -> dict:
    sym = norm_symbol(symbol)
    if not sym:
        raise ValueError("invalid symbol")
    with locked(base):
        doc = read_index(base)
        row = dict(doc["items"].get(sym) or {"symbol": sym})
        row.update(fields)
        doc["items"][sym] = row
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(base / "index.json", doc)
        return row


# ── universe ──────────────────────────────────────────────────────────────────────────────────────────────────
def write_universe(base: Path, rows: list[dict]) -> None:
    write_json(base / "universe.json", {"schema": "ProspectusUniverse@v1",
                                        "written_at": datetime.now(timezone.utc).isoformat(), "items": rows})


def read_universe(base: Path) -> list[dict]:
    doc = _read_json(base / "universe.json", {})
    items = doc.get("items") if isinstance(doc, dict) else None
    return [r for r in items or [] if isinstance(r, dict) and norm_symbol(r.get("symbol"))]


# ── queue ─────────────────────────────────────────────────────────────────────────────────────────────────────
def read_queue(base: Path) -> dict:
    doc = _read_json(base / "queue.json", None)
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        return {"schema": QUEUE_SCHEMA, "items": []}
    return doc


def enqueue(base: Path, rows: list[dict], *, now: datetime | None = None) -> int:
    """Add or upgrade queued rewrites. One row per symbol; a lower ``priority`` number runs first."""
    now = now or datetime.now(timezone.utc)
    added = 0
    with locked(base):
        doc = read_queue(base)
        by_sym = {r["symbol"]: r for r in doc["items"] if norm_symbol(r.get("symbol"))}
        for row in rows:
            sym = norm_symbol(row.get("symbol"))
            if not sym:
                continue
            current = by_sym.get(sym)
            if current is None:
                by_sym[sym] = {"symbol": sym, "scope": row.get("scope", "watch"), "priority": int(row.get("priority", 500)),
                               "premium": bool(row.get("premium")), "mode": row.get("mode", "full"),
                               "reason": row.get("reason", "scheduled"), "requested_by": row.get("requested_by", "schedule"),
                               "requested_at": now.isoformat(), "attempts": 0, "last_error": None, "state": "queued"}
                added += 1
            else:
                current["priority"] = min(int(current.get("priority", 500)), int(row.get("priority", 500)))
                current["premium"] = bool(current.get("premium") or row.get("premium"))
                if row.get("mode") == "full":
                    current["mode"] = "full"
                if current.get("state") in ("failed", "blocked_data"):  # re-requested: the gate runs again
                    current["state"] = "queued"
                current["reason"] = row.get("reason", current.get("reason"))
        doc["items"] = sorted(by_sym.values(), key=lambda r: (int(r.get("priority", 500)), r["symbol"]))
        write_json(base / "queue.json", doc)
    return added


def mark(base: Path, symbol: str, *, state: str, error: str | None = None, done: bool = False) -> None:
    """Move a queue row to running / queued / failed, or drop it from the queue when done."""
    sym = norm_symbol(symbol)
    with locked(base):
        doc = read_queue(base)
        kept = []
        for row in doc["items"]:
            if row.get("symbol") == sym:
                if done:
                    continue
                row["state"] = state
                if state == "running":
                    row["attempts"] = int(row.get("attempts", 0)) + 1
                    row["started_at"] = datetime.now(timezone.utc).isoformat()
                if error is not None:
                    row["last_error"] = error
            kept.append(row)
        doc["items"] = kept
        write_json(base / "queue.json", doc)


# ── per-job Brave allowance (≤ N/day reserved for this job) ─────────────────────────────────────────────────
def search_allowance(base: Path, limit: int, *, now: datetime | None = None, take: bool = False) -> int:
    """Remaining job searches today (UTC); with ``take`` consume one and return what is left (−1 = refused)."""
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    path = base / "search_budget.json"
    with locked(base, ".search.lock"):
        doc = _read_json(path, {})
        used = int((doc.get("days") or {}).get(day, 0)) if isinstance(doc, dict) else 0
        if not take:
            return max(0, limit - used)
        if used >= limit:
            return -1
        days = {k: v for k, v in ((doc.get("days") or {}) if isinstance(doc, dict) else {}).items()}
        days[day] = used + 1
        write_json(path, {"schema": "ProspectusSearchBudget@v1", "limit": limit, "days": days})
        return limit - used - 1
