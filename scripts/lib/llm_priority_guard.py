"""The defer window ``scripts/llm_priority_guard.sh`` actually uses.

The shell defers a job when the America/New_York weekday is at most the parsed
``-le`` bound and the hour is in ``[START, END)``. START and END come from the
script's ``${VAR:-default}`` lines, then a crontab assignment of those same
variable names, then an explicit env mapping. Callers never read ``os.environ``:
cron's environment is the crontab header, not this process.

``LLM_GUARD_FORCE`` is not honoured. Cron does not set it, and treating a force
flag as "this slot was required" would hide a real miss. An unreadable or
unparseable script returns None, and callers then do not skip any fire (fail
toward alerting).

AUTHORITY: READ_ONLY_ADVISORY. No I/O except the guard script text. No broker,
credential, scheduler or sender import.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

#: Sentinel: the caller did not supply a window, so resolve one only if a lane is flagged.
AUTO = object()

_START_RE = re.compile(r'^START="\$\{([A-Za-z_][A-Za-z0-9_]*):-(\d+)\}"', re.M)
_END_RE = re.compile(r'^END="\$\{([A-Za-z_][A-Za-z0-9_]*):-(\d+)\}"', re.M)
_RULE_RE = re.compile(
    r'\[\s*"\$DOW"\s*-le\s+(\d+)\s*\]\s*&&\s*'
    r'\[\s*"\$\(\(10#\$H\)\)"\s*-ge\s*"\$START"\s*\]\s*&&\s*'
    r'\[\s*"\$\(\(10#\$H\)\)"\s*-lt\s*"\$END"\s*\]'
)
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\d+)\s*(?:#.*)?$")
_GUARD_SCRIPT = "llm_priority_guard.sh"


@dataclass(frozen=True)
class GuardWindow:
    start_hour: int
    end_hour: int
    max_isoweekday: int
    start_env: str
    end_env: str


def _digits(value: object) -> int | None:
    text = str(value).strip() if value is not None else ""
    if not text.isdigit():
        return None
    return int(text)


def _crontab_hours(crontab_text: str, start_env: str, end_env: str) -> tuple[int | None, int | None]:
    """Last full-line ``NAME=<digits>`` assignment of the script's own variable names.

    A trailing ``#`` comment is ignored. A commented line is not an assignment.
    Inline assignments on a cron command are not the crontab's environment.
    """
    start = end = None
    for line in (crontab_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGN_RE.match(stripped)
        if not match:
            continue
        name, raw = match.group(1), int(match.group(2))
        if name == start_env:
            start = raw
        elif name == end_env:
            end = raw
    return start, end


def _window(start: int, end: int, max_isoweekday: int, start_env: str, end_env: str) -> GuardWindow | None:
    if not (1 <= max_isoweekday <= 7):
        return None
    if not (0 <= start <= 23 and start < end <= 24):
        return None
    return GuardWindow(start_hour=start, end_hour=end, max_isoweekday=max_isoweekday,
                       start_env=start_env, end_env=end_env)


def parse_guard_window(text: str, *, crontab_text: str = "", env: dict | None = None) -> GuardWindow | None:
    """The window ``text`` (the guard script) defers, or None when it cannot be read safely."""
    if not isinstance(text, str) or not text:
        return None
    start_m = _START_RE.search(text)
    end_m = _END_RE.search(text)
    rule_m = _RULE_RE.search(text)
    if not start_m or not end_m or not rule_m:
        return None
    start_env, start = start_m.group(1), int(start_m.group(2))
    end_env, end = end_m.group(1), int(end_m.group(2))
    cron_start, cron_end = _crontab_hours(crontab_text, start_env, end_env)
    if cron_start is not None:
        start = cron_start
    if cron_end is not None:
        end = cron_end
    supplied = env or {}
    if start_env in supplied:
        parsed = _digits(supplied[start_env])
        if parsed is None:
            return None
        start = parsed
    if end_env in supplied:
        parsed = _digits(supplied[end_env])
        if parsed is None:
            return None
        end = parsed
    return _window(start, end, int(rule_m.group(1)), start_env, end_env)


def load_guard_window(path: Path | None = None, *, crontab_text: str = "",
                      env: dict | None = None) -> GuardWindow | None:
    """Parse the repo guard script. An unreadable file is None (callers then alert)."""
    script = path if path is not None else Path(__file__).resolve().parents[1] / _GUARD_SCRIPT
    try:
        text = Path(script).read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        return None
    return parse_guard_window(text, crontab_text=crontab_text, env=env)


def guard_defers(at: datetime, window: GuardWindow | None, *, tz: str = "America/New_York") -> bool:
    """Whether the shell would exit 1 at ``at``.

    The shell sets ``TZ=America/New_York`` itself; the lane's schedule timezone is not
    consulted. An unaware instant does not defer (fail toward alerting). ``date +%u``
    is ``datetime.isoweekday`` (Monday 1 .. Sunday 7), not ``datetime.weekday``.
    """
    if window is None or at.tzinfo is None:
        return False
    local = at.astimezone(ZoneInfo(tz))
    return local.isoweekday() <= window.max_isoweekday and window.start_hour <= local.hour < window.end_hour


def resolve_guard_window(guard_window, lanes) -> GuardWindow | None:
    """``AUTO`` loads the script only when a lane is flagged. An explicit None stays None."""
    if guard_window is not AUTO:
        return guard_window
    rows = lanes or []
    flagged = any(isinstance(row, dict) and row.get("watchdog_llm_priority_guard") is True for row in rows)
    return load_guard_window() if flagged else None


def _usable_token(match: object) -> str | None:
    token = str(match or "").strip()
    if len(token) < 8:
        return None
    if token.endswith(".py") or token.endswith(".sh") or "/" in token:
        return token
    return None


def lane_behind_llm_priority_guard(match, crontab_text: str = "", command_text: str = "") -> bool:
    """True only when every uncommented hit of ``match`` is wrapped by the guard.

    One uncommented line that runs the same script without the guard means the slot
    can still be required, so the lane is not stamped (fail toward alerting). A
    commented line does not count. With no crontab hit, the lane's own command text
    stamps only when it contains both the match and the guard script.
    """
    token = _usable_token(match)
    if token is None:
        return False
    hits = []
    for line in (crontab_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if token in stripped:
            hits.append(stripped)
    if hits:
        return all(_GUARD_SCRIPT in line for line in hits)
    command = str(command_text or "")
    return token in command and _GUARD_SCRIPT in command
