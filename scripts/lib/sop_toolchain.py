"""Shared SOP toolchain discovery (Ruff / ShellCheck / Python).

Single canonical resolver used by the changed-file quality gate and by
runtime exact-head attestation. Prefer repository-declared environments over
bare PATH so attestation cannot record MISSING when the quality gate passes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Keep in sync with agent-governance CI pin and pyproject comment.
PINNED_RUFF_VERSION = "0.16.2"

_HUB_RUFF = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/ruff")


def resolve_ruff_bin(*, root: Path | None = None) -> Path | None:
    """Return an executable Ruff binary, or None if absent.

    Search order:
    1. ``<root>/.venv/bin/ruff``
    2. directory of ``sys.executable``
    3. declared hub rebuild ``.venv`` (local operator layout)
    4. ``PATH`` via ``shutil.which``
    """
    root = (root or ROOT).resolve()
    candidates: list[Path] = [
        root / ".venv" / "bin" / "ruff",
        Path(sys.executable).resolve().parent / "ruff",
        _HUB_RUFF,
    ]
    which = shutil.which("ruff")
    if which:
        candidates.append(Path(which))
    seen: set[str] = set()
    for c in candidates:
        key = str(c)
        if key in seen:
            continue
        seen.add(key)
        try:
            if c.is_file() and os.access(c, os.X_OK):
                return c
        except OSError:
            continue
    return None


def ruff_version_string(bin_path: Path, *, cwd: Path | None = None) -> str:
    """Raw ``ruff --version`` stdout (e.g. ``ruff 0.16.2``)."""
    return subprocess.check_output(
        [str(bin_path), "--version"],
        cwd=str(cwd or ROOT),
        text=True,
    ).strip()


def parse_ruff_version(raw: str) -> str | None:
    """Extract ``X.Y.Z`` from a Ruff version string."""
    if not raw or raw == "MISSING":
        return None
    m = re.search(r"\b(\d+\.\d+\.\d+)\b", raw)
    return m.group(1) if m else None


def resolve_shellcheck_bin() -> Path | None:
    which = shutil.which("shellcheck")
    if which:
        p = Path(which)
        if p.is_file() and os.access(p, os.X_OK):
            return p
    for candidate in (Path("/usr/bin/shellcheck"), Path("/usr/local/bin/shellcheck")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def shellcheck_version_string(bin_path: Path | None = None) -> str:
    bin_path = bin_path or resolve_shellcheck_bin()
    if bin_path is None:
        return "MISSING"
    try:
        out = subprocess.check_output([str(bin_path), "--version"], text=True)
        return out.splitlines()[0].strip() if out.strip() else "MISSING"
    except (OSError, subprocess.CalledProcessError):
        return "MISSING"


def python_version_string() -> str:
    return sys.version.split()[0]


def collect_tool_versions(*, root: Path | None = None) -> dict[str, Any]:
    """Deterministic toolchain snapshot for runtime attestation."""
    root = root or ROOT
    ruff_bin = resolve_ruff_bin(root=root)
    if ruff_bin is None:
        ruff_raw = "MISSING"
        ruff_parsed = None
    else:
        try:
            ruff_raw = ruff_version_string(ruff_bin, cwd=root)
            ruff_parsed = parse_ruff_version(ruff_raw)
        except (OSError, subprocess.CalledProcessError):
            ruff_raw = "MISSING"
            ruff_parsed = None

    sc_bin = resolve_shellcheck_bin()
    sc_raw = shellcheck_version_string(sc_bin)

    return {
        "python": python_version_string(),
        "pinned_ruff": PINNED_RUFF_VERSION,
        "ruff": ruff_raw if ruff_parsed is None and ruff_raw == "MISSING" else (ruff_parsed or ruff_raw),
        "ruff_raw": ruff_raw,
        "ruff_bin": str(ruff_bin) if ruff_bin else None,
        "shellcheck": sc_raw,
        "shellcheck_bin": str(sc_bin) if sc_bin else None,
    }
