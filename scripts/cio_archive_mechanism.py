#!/usr/bin/env python3
"""cio_archive_mechanism.py — WAVE G4 archive mechanism (build only; archive nothing).

AGENTS.md §0.6: Never delete. Archive with a tripwire that fires if anything
reads the archived path.

Census Part 4 proposal (conceptual → now shipped as mechanism):
  * ``archive/`` tree preserves git history (``git mv`` when the operator approves)
  * ``archive/ARCHIVE_MANIFEST.json`` — one row per archived item
  * tripwire raises a finding if anything imports / invokes / reads an archived path
  * weekly quiet / trip / ``review_by`` report (CLI; not scheduled)

This wave builds the mechanism and ships an EMPTY manifest. **Archive nothing.**
The first batch is the operator's.

READ_ONLY_ADVISORY. MBI=0. No deploy. No crontab edits.

Usage:
  python3 scripts/cio_archive_mechanism.py schema
  python3 scripts/cio_archive_mechanism.py validate
  python3 scripts/cio_archive_mechanism.py tripwire [--root PATH]
  python3 scripts/cio_archive_mechanism.py report
"""

from __future__ import annotations

NO_CONSUMER_REASON = (
    "archive mechanism CLI + CI tripwire; first archive batch is operator-only "
    "(WAVE G4). Invoked by overnight suite and operator CLI — no production "
    "importer by design until an approved batch exists."
)

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "ArchiveManifest@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

REPO = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = REPO / "archive"
MANIFEST_PATH = ARCHIVE_DIR / "ARCHIVE_MANIFEST.json"

# Manifest item required fields (Census Part 4 / WAVE G4 brief).
REQUIRED_ITEM_FIELDS: tuple[str, ...] = (
    "path",            # archived path under archive/
    "verdict",         # DARK | ONE_SHOT | ORPHANED | SUPERSEDED | ...
    "evidence",        # why this was archived
    "date",            # archive date (YYYY-MM-DD)
    "review_by",       # revisit date (typically +30d)
    "restore_command", # exact restore instruction (usually git mv …)
)

ALLOWED_VERDICTS = frozenset(
    {
        "DARK",
        "ONE_SHOT",
        "ORPHANED",
        "ORPHANED_ROUTE",
        "SUPERSEDED",
    }
)

# Paths the tripwire itself and the empty tree may mention without tripping.
MECHANISM_ALLOWLIST_REL: frozenset[str] = frozenset(
    {
        "scripts/cio_archive_mechanism.py",
        "tests/test_overnight_g4_archive_mechanism.py",
        "docs/audits/overnight/G4_ARCHIVE_MECHANISM_2026-08-31.md",
        "archive/ARCHIVE_MANIFEST.json",
        "archive/.gitkeep",
    }
)

# File suffixes scanned for live references.
_SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".sh", ".json", ".yml", ".yaml"}

# Directories never scanned (noise / generated / the archive tree itself).
_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    "archive",  # archived tree is the subject, not a consumer
    "trade-ai-releases",
}


class ArchivedPathAccessFinding(RuntimeError):
    """Finding: live code imports, invokes, or reads an archived path.

    AGENTS.md §0.6 tripwire. Raised (never swallowed) so a read of archived
    material cannot look like success.
    """

    def __init__(self, findings: list["TripHit"]):
        self.findings = list(findings)
        n = len(self.findings)
        preview = "; ".join(
            f"{h.consumer} -> {h.archived_path} ({h.kind})" for h in self.findings[:5]
        )
        extra = "" if n <= 5 else f" … +{n - 5} more"
        super().__init__(
            f"ARCHIVE_TRIPWIRE: {n} live reference(s) to archived path(s): "
            f"{preview}{extra}"
        )


@dataclass(frozen=True)
class TripHit:
    consumer: str
    archived_path: str
    kind: str  # import | read | path_literal
    line: int
    snippet: str


@dataclass
class ManifestItem:
    path: str
    verdict: str
    evidence: str
    date: str
    review_by: str
    restore_command: str
    original_path: Optional[str] = None
    batch: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "path": self.path,
            "verdict": self.verdict,
            "evidence": self.evidence,
            "date": self.date,
            "review_by": self.review_by,
            "restore_command": self.restore_command,
        }
        if self.original_path:
            d["original_path"] = self.original_path
        if self.batch:
            d["batch"] = self.batch
        if self.extra:
            d.update(self.extra)
        return d


def schema_document() -> dict[str, Any]:
    """ARCHIVE_MANIFEST schema (human + machine)."""
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mbi": MBI,
        "location": "archive/ARCHIVE_MANIFEST.json",
        "required_item_fields": list(REQUIRED_ITEM_FIELDS),
        "allowed_verdicts": sorted(ALLOWED_VERDICTS),
        "item_field_notes": {
            "path": "Repo-relative archived path under archive/ (git history preserved).",
            "verdict": "Archive-class adjudication: DARK | ONE_SHOT | ORPHANED | SUPERSEDED.",
            "evidence": "Why this was archived; cite census/as_of; never invent a reason.",
            "date": "Archive date YYYY-MM-DD (UTC calendar date of the move).",
            "review_by": "Revisit date YYYY-MM-DD; default date + 30 days.",
            "restore_command": "Exact restore, typically `git mv <archived> <original>`.",
            "original_path": "Optional pre-archive path (aids restore_command).",
            "batch": "Optional operator batch label (e.g. A).",
        },
        "tripwire": (
            "Raises ArchivedPathAccessFinding if any non-allowlisted live file "
            "imports, invokes, or reads an archived path."
        ),
        "rule": "Build mechanism; archive nothing without operator approval.",
    }


def default_review_by(archive_date: str, days: int = 30) -> str:
    d = date.fromisoformat(archive_date)
    return (d + timedelta(days=days)).isoformat()


def make_restore_command(archived_path: str, original_path: str) -> str:
    """Canonical restore instruction — git history preserved via git mv."""
    return f"git mv {archived_path} {original_path}"


def empty_manifest(*, as_of: Optional[str] = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "as_of": as_of,
        "note": (
            "Mechanism only (WAVE G4). Items empty by design — first archive "
            "batch is operator-only. Do not move files here without an approved "
            "manifest row."
        ),
        "items": [],
    }


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    if not path.is_file():
        return empty_manifest()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest root must be object: {path}")
    return data


def validate_manifest(data: dict[str, Any]) -> list[str]:
    """Return a list of validation errors (empty = ok)."""
    errors: list[str] = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got {data.get('schema')!r}")
    items = data.get("items")
    if not isinstance(items, list):
        errors.append("items must be a list")
        return errors
    seen: set[str] = set()
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            errors.append(f"items[{i}] must be an object")
            continue
        for key in REQUIRED_ITEM_FIELDS:
            if not str(raw.get(key) or "").strip():
                errors.append(f"items[{i}] missing required field {key!r}")
        path = str(raw.get("path") or "").strip()
        if path:
            if path in seen:
                errors.append(f"duplicate archived path: {path}")
            seen.add(path)
            if not path.startswith("archive/"):
                errors.append(f"items[{i}].path must be under archive/: {path}")
        verdict = str(raw.get("verdict") or "").strip()
        if verdict and verdict not in ALLOWED_VERDICTS:
            errors.append(
                f"items[{i}].verdict {verdict!r} not in {sorted(ALLOWED_VERDICTS)}"
            )
        for date_key in ("date", "review_by"):
            val = str(raw.get(date_key) or "").strip()
            if val:
                try:
                    date.fromisoformat(val)
                except ValueError:
                    errors.append(f"items[{i}].{date_key} not YYYY-MM-DD: {val}")
        restore = str(raw.get("restore_command") or "").strip()
        if restore and "git mv" not in restore and "restore" not in restore.lower():
            # Soft warning shape: still an error so a blank/garbage restore fails.
            errors.append(
                f"items[{i}].restore_command must be an explicit restore "
                f"(prefer `git mv <archived> <original>`): {restore!r}"
            )
    return errors


def archived_paths_from_manifest(data: dict[str, Any]) -> list[str]:
    items = data.get("items") or []
    out: list[str] = []
    for raw in items:
        if isinstance(raw, dict):
            p = str(raw.get("path") or "").strip()
            if p:
                out.append(p.replace("\\", "/"))
    return out


def archived_paths_on_disk(archive_dir: Path = ARCHIVE_DIR) -> list[str]:
    """Every file under archive/ except keep/manifest scaffolding."""
    if not archive_dir.is_dir():
        return []
    skip_names = {".gitkeep", "ARCHIVE_MANIFEST.json"}
    out: list[str] = []
    root = archive_dir.parent
    for p in sorted(archive_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.name in skip_names and p.parent == archive_dir:
            continue
        rel = p.relative_to(root).as_posix()
        out.append(rel)
    return out


def effective_archived_paths(
    data: Optional[dict[str, Any]] = None,
    *,
    root: Path = REPO,
) -> list[str]:
    data = data if data is not None else load_manifest(root / "archive" / "ARCHIVE_MANIFEST.json")
    paths = set(archived_paths_from_manifest(data))
    paths.update(archived_paths_on_disk(root / "archive"))
    return sorted(paths)


_PATH_ARCHIVE_RE = re.compile(
    r"""(?<![A-Za-z0-9_])(?:['"])((?:\.?/)?archive/[^'"]+)['"]""",
)


def _iter_scan_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        # Skip anything under excluded directory names.
        parts = set(p.relative_to(root).parts)
        if parts & _SKIP_DIR_NAMES:
            continue
        yield p


def _line_snippet(text: str, lineno: int, width: int = 160) -> str:
    lines = text.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()[:width]
    return ""


def _match_archived(ref: str, archived: set[str]) -> Optional[str]:
    """Return the archived path ``ref`` touches, or None.

    Accepts repo-relative paths (``archive/foo/bar.py``) and dotted module
    names (``archive.foo.bar``).
    """
    ref = ref.lstrip("./").replace("\\", "/")
    if not ref:
        return None
    candidates = {ref}
    if "/" not in ref and ref.startswith("archive"):
        dotted_as_path = ref.replace(".", "/")
        candidates.add(dotted_as_path)
        candidates.add(dotted_as_path + ".py")
    elif "." in ref and ref.startswith("archive."):
        dotted_as_path = ref.replace(".", "/")
        candidates.add(dotted_as_path)
        candidates.add(dotted_as_path + ".py")
    for cand in candidates:
        for ap in archived:
            if cand == ap:
                return ap
            # Package / directory prefix either way.
            if cand.startswith(ap.rstrip("/") + "/") or ap.startswith(cand.rstrip("/") + "/"):
                return ap
            if ap.endswith(".py") and cand == ap[:-3]:
                return ap
    return None


def _python_import_hits(rel: str, text: str, archived: set[str]) -> list[TripHit]:
    """AST-based import detection — only against known archived paths."""
    if not archived:
        return []
    hits: list[TripHit] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return hits
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        for mod in mods:
            if not (mod == "archive" or mod.startswith("archive.")):
                continue
            matched = _match_archived(mod, archived)
            if matched is None and mod == "archive":
                # `import archive` / `from archive import …` against any archived
                # tree rooted at archive/ is a trip when archived paths exist.
                matched = sorted(archived)[0]
            if matched is None:
                continue
            hits.append(
                TripHit(
                    consumer=rel,
                    archived_path=matched,
                    kind="import",
                    line=getattr(node, "lineno", 0) or 0,
                    snippet=_line_snippet(text, getattr(node, "lineno", 0) or 0),
                )
            )
    return hits


def _path_literal_hits(rel: str, text: str, archived: set[str]) -> list[TripHit]:
    """String path literals that name a known archived path."""
    if not archived:
        return []
    hits: list[TripHit] = []
    for m in _PATH_ARCHIVE_RE.finditer(text):
        raw = m.group(1).lstrip("./")
        matched = _match_archived(raw, archived)
        if matched is None:
            continue
        line = text.count("\n", 0, m.start()) + 1
        snippet = _line_snippet(text, line)
        kind = (
            "read"
            if any(
                tok in snippet.lower()
                for tok in (
                    "open(",
                    "read_text",
                    "read_bytes",
                    "path(",
                    "joinpath",
                    "load",
                    "importlib",
                    "runpy",
                )
            )
            else "path_literal"
        )
        hits.append(
            TripHit(
                consumer=rel,
                archived_path=matched,
                kind=kind,
                line=line,
                snippet=snippet,
            )
        )
    return hits


def scan_archived_path_references(
    *,
    root: Path = REPO,
    archived: Optional[Iterable[str]] = None,
    allowlist: Optional[Iterable[str]] = None,
) -> list[TripHit]:
    """Scan live tree for imports/reads of archived paths. Does not raise.

    With an empty archived set (WAVE G4 default) this returns []. The tripwire
    arms only when the manifest or ``archive/`` tree lists real archived paths.
    """
    root = root.resolve()
    arch_set = {
        p.replace("\\", "/")
        for p in (archived if archived is not None else effective_archived_paths(root=root))
    }
    allow = set(allowlist if allowlist is not None else MECHANISM_ALLOWLIST_REL)
    allow.update(MECHANISM_ALLOWLIST_REL)

    hits: list[TripHit] = []
    if not arch_set:
        return hits

    for path in _iter_scan_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in allow:
            continue
        # Overnight / project audit docs may discuss archive/ without consuming it.
        if rel.startswith("docs/audits/") or rel.startswith("docs/project/"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.suffix == ".py":
            hits.extend(_python_import_hits(rel, text, arch_set))
        hits.extend(_path_literal_hits(rel, text, arch_set))
    uniq: dict[tuple, TripHit] = {}
    for h in hits:
        uniq[(h.consumer, h.archived_path, h.kind, h.line)] = h
    return sorted(uniq.values(), key=lambda h: (h.consumer, h.line, h.archived_path))


def assert_no_archived_reads(
    *,
    root: Path = REPO,
    archived: Optional[Iterable[str]] = None,
    allowlist: Optional[Iterable[str]] = None,
) -> None:
    """Tripwire: raise ArchivedPathAccessFinding if live code touches archive."""
    hits = scan_archived_path_references(
        root=root, archived=archived, allowlist=allowlist
    )
    if hits:
        raise ArchivedPathAccessFinding(hits)


def build_report(
    *,
    root: Path = REPO,
    now: Optional[date] = None,
) -> dict[str, Any]:
    """Weekly-style quiet / trip / review_by report (CLI; not scheduled)."""
    now = now or datetime.now(timezone.utc).date()
    manifest = load_manifest(root / "archive" / "ARCHIVE_MANIFEST.json")
    errors = validate_manifest(manifest)
    hits = scan_archived_path_references(root=root)
    items = manifest.get("items") or []
    due: list[dict[str, Any]] = []
    quiet: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        rb = str(raw.get("review_by") or "")
        row = {
            "path": raw.get("path"),
            "verdict": raw.get("verdict"),
            "review_by": rb,
        }
        try:
            due_date = date.fromisoformat(rb)
        except ValueError:
            due.append({**row, "status": "INVALID_REVIEW_BY"})
            continue
        if due_date <= now:
            due.append({**row, "status": "REVIEW_DUE"})
        else:
            quiet.append({**row, "status": "QUIET"})
    return {
        "schema": "ArchiveMechanismReport@v1",
        "as_of": now.isoformat(),
        "manifest_schema": manifest.get("schema"),
        "item_count": len(items),
        "validation_errors": errors,
        "trip_count": len(hits),
        "trips": [asdict(h) for h in hits],
        "review_due": due,
        "quiet": quiet,
        "authority": AUTHORITY,
        "archived_nothing": len(items) == 0 and not archived_paths_on_disk(root / "archive"),
    }


def _cmd_schema(_: argparse.Namespace) -> int:
    print(json.dumps(schema_document(), indent=2, sort_keys=False))
    return 0


def _cmd_validate(_: argparse.Namespace) -> int:
    data = load_manifest()
    errors = validate_manifest(data)
    out = {
        "ok": not errors,
        "path": str(MANIFEST_PATH.relative_to(REPO)),
        "item_count": len(data.get("items") or []),
        "errors": errors,
    }
    print(json.dumps(out, indent=2))
    return 0 if not errors else 1


def _cmd_tripwire(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else REPO
    try:
        assert_no_archived_reads(root=root)
    except ArchivedPathAccessFinding as exc:
        print(json.dumps({"ok": False, "error": str(exc), "findings": [asdict(h) for h in exc.findings]}, indent=2))
        return 1
    print(json.dumps({"ok": True, "trip_count": 0, "root": str(root)}, indent=2))
    return 0


def _cmd_report(_: argparse.Namespace) -> int:
    report = build_report()
    print(json.dumps(report, indent=2))
    return 1 if report["validation_errors"] or report["trip_count"] else 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_schema = sub.add_parser("schema", help="Print ARCHIVE_MANIFEST schema")
    p_schema.set_defaults(func=_cmd_schema)

    p_val = sub.add_parser("validate", help="Validate archive/ARCHIVE_MANIFEST.json")
    p_val.set_defaults(func=_cmd_validate)

    p_trip = sub.add_parser("tripwire", help="Scan for live reads of archived paths")
    p_trip.add_argument("--root", default=None, help="Repo root to scan (default: this checkout)")
    p_trip.set_defaults(func=_cmd_tripwire)

    p_rep = sub.add_parser("report", help="Quiet / trip / review_by report")
    p_rep.set_defaults(func=_cmd_report)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
