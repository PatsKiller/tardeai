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
from pathlib import Path

ENV_OVERRIDE = "TRADEAI_PORTFOLIO_REPORTS_ROOT"
REPORTS_RELPATH = Path("data") / "portfolios" / "reports"
URL_PREFIX = "/" + REPORTS_RELPATH.as_posix() + "/"
_REL_PREFIX = REPORTS_RELPATH.as_posix() + "/"


def _state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
    except Exception:  # pragma: no cover - run as scripts/<x>.py with scripts/ on sys.path
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
        except Exception:
            production_state_root = None  # type: ignore
    if production_state_root is not None:
        return Path(production_state_root())
    env = os.environ.get("TRADEAI_STATE_ROOT") or os.environ.get("TRADEAI_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def portfolio_reports_root() -> Path:
    """Physical directory that holds ``data/portfolios/reports`` content."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override)
    return _state_root() / REPORTS_RELPATH


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


def report_url(path: Path | str) -> str:
    """Served URL (``/data/portfolios/reports/...``) for a file under the reports root."""
    rel = Path(path).resolve().relative_to(portfolio_reports_root().resolve())
    return URL_PREFIX + rel.as_posix()


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
