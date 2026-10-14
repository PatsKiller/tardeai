"""One resolver for the YouTube auth cookie jar (Netscape ``cookies.txt``).

Why this exists (2026-10-14): every reader and the Ops UI writer built the path as
``PROJECT_ROOT / "config" / "youtube_cookies.txt"``. Cron, the API and the ingesters run from
the served release (``portfolio-server/<sha>-.../`` via ``CURRENT``), and every promote creates
a new release directory from git, which never carries this gitignored secret. A cookie the
operator refreshed on 2026-10-13 was therefore stranded in the old release at the next promote
and the Command Center showed "YouTube cookies RED — no cookie file".

The canonical home is the host's durable operator-secret directory ``~/.config/tradeai/`` — the
established convention for secrets that must survive promotes (``scripts/broker_secrets.py``:
"~/.config/tradeai/broker_credentials.env (stable across promotes)"; also
``cio-telegram.env``, ``llm_global_daily_usd_cap.env``, ``agent-read-api.env``).
``TRADEAI_YOUTUBE_COOKIE_FILE`` overrides the canonical file (tests, drills, other hosts).

Read order: canonical -> legacy ``<project_root>/config/youtube_cookies.txt`` (so nothing
breaks before the one-time migration). A cookie found only at the legacy path is reported as
location ``legacy`` so health checks can flag it amber: it will be lost on the next release.
Writers always write the canonical path.

This module never opens the cookie file: it only resolves and stats paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_OVERRIDE = "TRADEAI_YOUTUBE_COOKIE_FILE"
FILENAME = "youtube_cookies.txt"
LEGACY_RELPATH = Path("config") / FILENAME
#: Display form of the canonical default, for operator-facing text (no user name baked in).
CANONICAL_DISPLAY = "~/.config/tradeai/" + FILENAME

LOCATION_CANONICAL = "canonical"
LOCATION_LEGACY = "legacy"
LOCATION_MISSING = "missing"

_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def canonical_cookie_path() -> Path:
    """Durable cookie path outside any release or checkout (env override wins)."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "tradeai" / FILENAME


def legacy_cookie_path(project_root: Path | str | None = None) -> Path:
    """Pre-2026-10-14 location inside the (release) tree. Read-only fallback."""
    root = Path(project_root) if project_root is not None else _DEFAULT_PROJECT_ROOT
    return root / LEGACY_RELPATH


@dataclass(frozen=True)
class CookieResolution:
    path: Path  # the file to read; equals ``canonical`` when nothing exists
    location: str  # canonical | legacy | missing
    canonical: Path
    legacy: Path

    @property
    def exists(self) -> bool:
        return self.location != LOCATION_MISSING

    @property
    def is_legacy(self) -> bool:
        return self.location == LOCATION_LEGACY

    def legacy_warning(self) -> str | None:
        """Operator-facing amber note when the jar lives only in the release tree."""
        if not self.is_legacy:
            return None
        return (
            f"cookie file is at the legacy release path {self.legacy} — will be lost on next release; "
            f"move it to {self.canonical} (cp -p, chmod 600)"
        )

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "location": self.location,
            "canonical": str(self.canonical),
            "legacy": str(self.legacy),
        }


def resolve_cookie_path(project_root: Path | str | None = None) -> CookieResolution:
    """Resolve where the cookie jar is read from: canonical, else legacy, else missing."""
    canonical = canonical_cookie_path()
    legacy = legacy_cookie_path(project_root)
    if canonical.is_file():
        return CookieResolution(canonical, LOCATION_CANONICAL, canonical, legacy)
    if legacy.is_file():
        return CookieResolution(legacy, LOCATION_LEGACY, canonical, legacy)
    return CookieResolution(canonical, LOCATION_MISSING, canonical, legacy)


def youtube_cookie_path(project_root: Path | str | None = None) -> Path:
    """Path to read the cookie jar from (canonical when nothing exists yet)."""
    return resolve_cookie_path(project_root).path
