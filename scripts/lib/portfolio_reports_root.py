"""One resolver for ``data/portfolios/reports`` — the persistent home of generated reports.

Why this exists (2026-10-09): every report writer built its output dir as
``PROJECT_ROOT / "data" / "portfolios" / "reports"``. Cron runs from the release dir
(``portfolio-server/CURRENT``), where that path is a REAL per-release directory, not a
symlink into persistent-state. Reports were therefore stranded inside whichever release
was current when they were written, carried forward only by the next release's clone,
lost when a release was pruned, and the lane registry's ``output_signal`` (which reads
persistent-state) saw the producing lane as SILENT.

Writers and readers now resolve the directory here, from the same state root every other
durable store uses (``canonical_store_registry.production_state_root``). The served URL
prefix stays ``/data/portfolios/reports/`` — only the physical location moved.

``TRADEAI_PORTFOLIO_REPORTS_ROOT`` overrides the whole directory (tests, drills).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_OVERRIDE = "TRADEAI_PORTFOLIO_REPORTS_ROOT"
REPORTS_RELPATH = Path("data") / "portfolios" / "reports"
URL_PREFIX = "/" + REPORTS_RELPATH.as_posix() + "/"
_REL_PREFIX = REPORTS_RELPATH.as_posix() + "/"


def _state_root() -> Path:
    """Persistent state root.

    ``TRADEAI_ROOT`` is honoured by ``production_state_root`` but several units and
    launchers set it to the RELEASE tree (``portfolio-server/CURRENT``), which would put
    reports straight back into the release dir. When it names a release, follow that
    release's own ``data/portfolios/state`` link into persistent-state instead.
    """
    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        if os.environ.get(key):
            return Path(os.environ[key])
    code_root = os.environ.get("TRADEAI_ROOT")
    if code_root:
        state_link = Path(code_root) / "data" / "portfolios" / "state"
        if state_link.is_symlink():
            return state_link.resolve().parents[2]
    try:
        from scripts.lib.canonical_store_registry import production_state_root
    except Exception:  # pragma: no cover - run as scripts/<x>.py with scripts/ on sys.path
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
        except Exception:
            production_state_root = None  # type: ignore
    if production_state_root is not None:
        return Path(production_state_root())
    return Path(code_root) if code_root else Path(__file__).resolve().parents[2]


def portfolio_reports_root() -> Path:
    """Physical directory that holds ``data/portfolios/reports`` content."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override)
    return _state_root() / REPORTS_RELPATH


def state_root() -> Path:
    """Persistent state root as this module resolves it (see ``_state_root``)."""
    return _state_root()


def resolve_report_relpath(rel: str) -> Path:
    """Map a repo-relative ``data/portfolios/reports/...`` path/glob to its physical path.

    Anything outside that prefix is returned unchanged (as a relative Path) so callers
    can keep resolving it against their own project root.
    """
    rel = str(rel).lstrip("/")
    if rel == REPORTS_RELPATH.as_posix():
        return portfolio_reports_root()
    if rel.startswith(_REL_PREFIX):
        return portfolio_reports_root() / rel[len(_REL_PREFIX):]
    return Path(rel)


def is_report_relpath(rel: str) -> bool:
    rel = str(rel).lstrip("/")
    return rel == REPORTS_RELPATH.as_posix() or rel.startswith(_REL_PREFIX)


def glob_reports(pattern: str) -> list[Path]:
    """Glob a ``data/portfolios/reports/...`` pattern in the persistent location."""
    pattern = str(pattern).lstrip("/")
    if not pattern.startswith(_REL_PREFIX):
        raise ValueError(f"not a reports pattern: {pattern}")
    return list(portfolio_reports_root().glob(pattern[len(_REL_PREFIX):]))


def report_url(path: Path | str) -> str | None:
    """Served URL (``/data/portfolios/reports/...``) for a file under the reports root.

    Returns None — never raises — for a path outside it, including a symlink inside the
    root that points elsewhere: callers skip such entries rather than crash a listing.
    """
    p = Path(path)
    for base in (portfolio_reports_root(), portfolio_reports_root().resolve()):
        try:
            return URL_PREFIX + p.relative_to(base).as_posix()
        except ValueError:
            continue
    return None


def served_url(path: Path | str, project_root: Path | str) -> str:
    """URL for a file under the reports root (``/data/portfolios/reports/...``) or under
    ``project_root`` (``/<rel>``). Anything else is returned as ``str(path)``, unchanged —
    the behaviour every caller had before the reports root moved."""
    p = Path(path)
    bases = ((portfolio_reports_root(), URL_PREFIX), (Path(project_root), "/"))
    for candidate in (p, p.resolve()):
        for base, prefix in bases:
            for b in (base, base.resolve()):
                try:
                    return prefix + candidate.relative_to(b).as_posix()
                except ValueError:
                    continue
    return str(path)


def resolve_served_path(path_str: str, project_root: Path | str) -> Path:
    """Inverse of :func:`served_url`: a served/repo-relative path to its physical file."""
    s = str(path_str).lstrip("/")
    if is_report_relpath(s):
        return resolve_report_relpath(s)
    return Path(project_root) / s


# ── promote -> migrate window ────────────────────────────────────────────────
# Between promoting this code and running migrate_portfolio_reports_to_state_root.py
# --apply, history still sits only in the release-local dir. Readers fall back to it so
# nothing served goes missing; writers never do.

_FALLBACK_LOGGED: set[str] = set()


def legacy_reports_dir(project_root: Path | str) -> Path:
    """The release-local ``<project_root>/data/portfolios/reports`` (pre-2026-10-09 home)."""
    return Path(project_root) / REPORTS_RELPATH


def _log_fallback_once(what: str) -> None:
    if what not in _FALLBACK_LOGGED:
        _FALLBACK_LOGGED.add(what)
        print(f"[portfolio_reports_root] LEGACY_FALLBACK {what} served from the release-local "
              f"reports dir; run migrate_portfolio_reports_to_state_root.py --apply", file=sys.stderr)


def contained(base: Path | str, rel: str) -> Path | None:
    """``base / rel`` resolved, or None when it would escape ``base`` (``..``, absolute
    components, symlinks pointing outside)."""
    base_r = Path(base).resolve()
    try:
        cand = (base_r / str(rel).lstrip("/")).resolve()
    except (OSError, RuntimeError):
        return None
    if cand == base_r or base_r in cand.parents:
        return cand
    return None


def resolve_report_file(rel: str, project_root: Path | str) -> Path | None:
    """Physical file for a path relative to the reports root: the persistent root first,
    then the release-local legacy dir (logged once). None when neither holds a file or
    the path would escape its root."""
    primary = contained(portfolio_reports_root(), rel)
    if primary is not None and primary.is_file():
        return primary
    legacy_base = legacy_reports_dir(project_root)
    if legacy_base.resolve() == portfolio_reports_root().resolve():
        return None
    legacy = contained(legacy_base, rel)
    if legacy is not None and legacy.is_file():
        _log_fallback_once(str(rel))
        return legacy
    return None


def union_glob(subdir_pattern: str, project_root: Path | str) -> list[Path]:
    """Glob ``subdir_pattern`` (relative to the reports root) in the persistent root and the
    legacy release dir. The persistent copy wins on the same relative name."""
    root = portfolio_reports_root()
    seen: dict[str, Path] = {}
    for p in root.glob(subdir_pattern):
        seen[p.relative_to(root).as_posix()] = p
    legacy_base = legacy_reports_dir(project_root)
    if legacy_base.is_dir() and legacy_base.resolve() != root.resolve():
        added = False
        for p in legacy_base.glob(subdir_pattern):
            key = p.relative_to(legacy_base).as_posix()
            if key not in seen:
                seen[key] = p
                added = True
        if added:
            _log_fallback_once(f"glob:{subdir_pattern}")
    return list(seen.values())


def url_for_report_file(path: Path | str, project_root: Path | str) -> str | None:
    """Served URL for a file found by :func:`union_glob` (either root), or None."""
    url = report_url(path)
    if url is not None:
        return url
    p = Path(path)
    legacy = legacy_reports_dir(project_root)
    for base in (legacy, legacy.resolve()):
        try:
            return URL_PREFIX + p.relative_to(base).as_posix()
        except ValueError:
            continue
    return None
