"""Resolve the effective investment-policy files (operator 2026-11-06).

The ratified model portfolio and IPS live PRIVATELY under
``<root>/data/cio/policy/<name>`` (data/ is gitignored; in live releases
``data/cio`` is a symlink into persistent-state). The tracked
``config/<name>`` copies are the public template / fallback only. The repo is
public, so real values must never be committed — this module only chooses a
path; it never copies values.

Precedence: an explicit path/config_dir from the caller always wins (callers
handle that before asking here); otherwise the private file when it exists and
parses as a JSON object; otherwise the template.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_SUBDIR = Path("data") / "cio" / "policy"
TEMPLATE_SUBDIR = Path("config")
MODEL_PORTFOLIO = "model_portfolio.json"
IPS = "investment_policy_statement.json"


def _root(project_root: Optional[Path]) -> Path:
    return Path(project_root) if project_root is not None else PROJECT_ROOT


def _valid_private(path: Path) -> bool:
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def policy_path(name: str, project_root: Optional[Path] = None) -> Path:
    """Effective path for policy file ``name`` (e.g. ``model_portfolio.json``)."""
    root = _root(project_root)
    private = root / PRIVATE_SUBDIR / name
    if _valid_private(private):
        return private
    return root / TEMPLATE_SUBDIR / name


def policy_source(name: str, project_root: Optional[Path] = None) -> str:
    """``"private"`` or ``"template"`` — which file :func:`policy_path` picks."""
    root = _root(project_root)
    return "private" if policy_path(name, root) == root / PRIVATE_SUBDIR / name else "template"


def source_for_path(path: Path, project_root: Optional[Path] = None) -> str:
    """Provenance of an already-chosen path: private / template / explicit."""
    root = _root(project_root)
    p = Path(path)
    for kind, sub in (("private", PRIVATE_SUBDIR), ("template", TEMPLATE_SUBDIR)):
        if p.parent == root / sub:
            return kind
    return "explicit"


def policy_label(path: Path, project_root: Optional[Path] = None) -> str:
    """Repo-relative display label for a policy path (e.g. ``data/cio/policy/x.json``)."""
    p = Path(path)
    try:
        return p.relative_to(_root(project_root)).as_posix()
    except ValueError:
        return p.name


def review_overdue(doc: Any, today: Optional[date] = None) -> bool:
    """True when ``doc['_meta']['next_review']`` is a parseable date in the past."""
    meta = doc.get("_meta") if isinstance(doc, dict) else None
    raw = meta.get("next_review") if isinstance(meta, dict) else None
    if not raw:
        return False
    try:
        due = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00")).date()
    except ValueError:
        try:
            due = date.fromisoformat(str(raw).strip()[:10])
        except ValueError:
            return False
    return due < (today or date.today())
