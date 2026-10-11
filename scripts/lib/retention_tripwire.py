"""Reader half of the row-archive tripwire (AGENTS.md §0 rule 6: archive with a tripwire that fires
if anything reads the archived path).

Writers, both already archive-first:
  * ``scripts/db_retention.py`` via ``scripts/lib/retention_archive.write_manifest`` — one
    ``RetentionArchiveTripwire@v1`` line per archived ``.jsonl.gz`` in
    ``<state>/archive/db_retention/<table>/TRIPWIRE.jsonl``, written BEFORE the DELETE;
  * ``scripts/db_trim.py`` — ``<state>/archive/db_trim/TRIPWIRE.jsonl`` (dropped indexes, tables,
    schemas, trimmed rows). Until 2026-10-11 nothing read either file.

This module is the reader. ``findings()`` returns ``DbHygieneReport@v1``-shaped findings that
``scripts/report_db_hygiene.py`` (nightly, platform-maintenance step) appends to its report; the
incident fan-in (``scripts/n8n_incident_fanin.py`` source ``db_hygiene``) turns each one into an open
incident and the SIEM bridge (``scripts/n8n_siem_bridge.py``) into a ``system_health_events`` row. No
new scheduler, no new sender.

  ARCHIVE_TRIPWIRE  P1  a live consumer names an archived path: a file under scripts/, config/ or
                        linux_launchers/, an uncommented user-crontab line, or a user systemd
                        ``.service`` unit. The writers and the two registries that DESCRIBE the archive
                        are the allowlist (they write it, they never read it back).
  ARCHIVE_MISSING   P2  a tripwire record names an archive file that no longer exists (rule 6: an
                        archive is evidence; losing it is a finding, not housekeeping).
  TRIPWIRE_UNREADABLE P3 a tripwire line does not parse.

Detection is by reference, the same shape as ``check_served_copy_split.archive_tripwire`` and
``cio_archive_mechanism``: it catches a reader that names the path, not one that builds it from
parts at runtime. File access times are not used: the nightly pg_dump / Drive sync read the state
tree and would trip it on every run.

AUTHORITY: READ_ONLY_ADVISORY. Reads files, ``crontab -l`` and unit files. Writes nothing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = "RetentionArchiveTripwire@v1"
TRIPWIRE_NAME = "TRIPWIRE.jsonl"

#: Path fragments that identify an archived store. Any live reference to one of these is a read.
NEEDLES: tuple[str, ...] = ("archive/db_retention", "archive/db_trim", "archive/file_prune")

#: Repo files that legitimately name the archive: its writers, this reader, and the registries that
#: document where the archive lives. Relative to the repo root.
ALLOWLIST_REL: frozenset[str] = frozenset({
    "scripts/db_retention.py",
    "scripts/db_trim.py",
    "scripts/report_db_hygiene.py",
    "scripts/lib/retention_archive.py",
    "scripts/lib/retention_tripwire.py",
    "config/data_retention_policy.json",
    "config/lane_registry.json",
})

SCAN_DIRS: tuple[str, ...] = ("scripts", "config", "linux_launchers")
SCAN_SUFFIXES = frozenset({".py", ".sh", ".json", ".yaml", ".yml", ".service", ".timer", ".js", ".ts", ".mjs"})
#: record keys that hold an archived file path (db_retention: archive; db_trim: archive / dump / ddl_file)
PATH_KEYS: tuple[str, ...] = ("archive", "dump", "ddl_file")


def tripwire_files(state_root: Path) -> list[Path]:
    base = Path(state_root) / "archive"
    out = sorted((base / "db_retention").glob(f"*/{TRIPWIRE_NAME}"))
    # 2026-10-11: file-prune archives (db_retention FILE_PRUNE, archive-then-unlink) and their tripwires.
    out += sorted((base / "file_prune").glob(f"*/{TRIPWIRE_NAME}"))
    trim = base / "db_trim" / TRIPWIRE_NAME
    if trim.is_file():
        out.append(trim)
    return out


def load_records(state_root: Path) -> tuple[list[dict], list[dict]]:
    """(records, unreadable) across every tripwire file under the state root."""
    records: list[dict] = []
    bad: list[dict] = []
    for f in tripwire_files(state_root):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            bad.append({"file": str(f), "line": 0, "error": str(exc)})
            continue
        for i, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if not isinstance(rec, dict):
                    raise ValueError("not an object")
            except ValueError as exc:
                bad.append({"file": str(f), "line": i, "error": str(exc)[:80]})
                continue
            rec["_tripwire_file"] = str(f)
            records.append(rec)
    return records, bad


def missing_archives(records: Iterable[dict]) -> list[dict]:
    out = []
    for rec in records:
        for k in PATH_KEYS:
            p = rec.get(k)
            if isinstance(p, str) and p and not Path(p).exists():
                out.append({"path": p, "kind": rec.get("kind") or "rows", "table": rec.get("table") or rec.get("name"),
                            "tripwire": rec.get("_tripwire_file")})
    return out


def _read_crontab() -> str:
    try:
        return subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001 — no crontab is "no references", never a crash of the nightly report
        return ""


def scan_references(repo: Path, *, crontab_text: Optional[str] = None, unit_dir: Optional[Path] = None,
                    needles: Iterable[str] = NEEDLES) -> list[dict]:
    """Every live place that names an archived path. An empty list is the only OK."""
    repo = Path(repo)
    needles = tuple(n.rstrip("/") for n in needles)
    hits: list[dict] = []
    for sub in SCAN_DIRS:
        base = repo / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in SCAN_SUFFIXES or "__pycache__" in p.parts:
                continue
            rel = p.relative_to(repo).as_posix()
            if rel in ALLOWLIST_REL:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n in needles:
                if n in text:
                    hits.append({"where": "repo", "ref": rel, "needle": n})
                    break
    if crontab_text is None:
        crontab_text = _read_crontab()
    for i, line in enumerate(crontab_text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for n in needles:
            if n in line:
                hits.append({"where": "crontab", "ref": f"line {i}", "needle": n})
                break
    unit_dir = unit_dir if unit_dir is not None else Path.home() / ".config" / "systemd" / "user"
    if unit_dir.is_dir():
        for u in sorted(unit_dir.glob("*.service")):
            try:
                text = u.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n in needles:
                if n in text:
                    hits.append({"where": "systemd", "ref": u.name, "needle": n})
                    break
    return hits


def findings(state_root: Path, repo: Path, *, crontab_text: Optional[str] = None,
             unit_dir: Optional[Path] = None) -> list[dict]:
    """DbHygieneReport@v1 findings: {code, item, severity, detail}."""
    out: list[dict] = []
    for h in scan_references(repo, crontab_text=crontab_text, unit_dir=unit_dir):
        out.append({"code": "ARCHIVE_TRIPWIRE", "item": f"{h['where']}:{h['ref']}", "severity": "P1",
                    "detail": f"names {h['needle']} — archived rows must not be read (AGENTS.md §0 rule 6); "
                              "restore through an operator-approved path instead"})
    records, bad = load_records(state_root)
    for m in missing_archives(records):
        out.append({"code": "ARCHIVE_MISSING", "item": m["path"], "severity": "P2",
                    "detail": f"{m['kind']} archive of {m['table']} recorded in {m['tripwire']} is gone"})
    for b in bad:
        out.append({"code": "TRIPWIRE_UNREADABLE", "item": f"{b['file']}:{b['line']}", "severity": "P3",
                    "detail": b["error"]})
    return out
