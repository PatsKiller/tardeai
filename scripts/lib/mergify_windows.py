"""Mergify ET windows — config + schedule helpers (Ops Controls / Releases page).

Reads ``config/mergify_windows.json``. Presets never open Mon–Fri 09:30–16:15 ET
(market freeze). Regenerating ``.mergify.yml`` schedule lines is
``render_schedule_yaml_fragment`` / ``apply_schedules_to_mergify_yml``.

AUTHORITY: READ_ONLY_ADVISORY for reads. Writing ``.mergify.yml`` is a local file
edit for a reviewed PR — never a live Mergify API call.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "mergify_windows.json"
MERGIFY_YML = ROOT / ".mergify.yml"
SCHEMA = "MergifyWindows@v1"
SETTING_KEY = "mergify.windows_preset"
MARKET_FREEZE_START = (9, 30)
MARKET_FREEZE_END = (16, 15)

_SCHEDULE_RE = re.compile(
    r"^(?P<days>[\w\-]+)\s+(?P<start>\d{1,2}:\d{2})-(?P<end>\d{1,2}:\d{2})"
    r"\[(?P<tz>[^\]]+)\]$"
)
# Schedule-bearing ``- or:`` blocks sit at conditions indent (6 spaces).
_OR_BLOCK_RE = re.compile(
    r"(      - or:\n(?:          - schedule=[^\n]+\n)+)",
    re.MULTILINE,
)


def load(path: Optional[Path] = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError(f"expected {SCHEMA} in {p}")
    return data


def active_preset(cfg: Optional[Mapping[str, Any]] = None) -> str:
    c = dict(cfg or load())
    return str(c.get("preset") or "after_hours")


def schedules_for(preset: Optional[str] = None, cfg: Optional[Mapping[str, Any]] = None) -> list[str]:
    c = dict(cfg or load())
    name = preset or active_preset(c)
    presets = c.get("presets") or {}
    row = presets.get(name)
    if not isinstance(row, Mapping):
        raise KeyError(f"unknown mergify windows preset: {name}")
    out = list(row.get("schedules") or [])
    if not out:
        raise ValueError(f"preset {name} has no schedules")
    for s in out:
        assert_not_market_hours(s)
    return out


def assert_not_market_hours(schedule: str) -> None:
    """Refuse a schedule line that overlaps Mon–Fri 09:30–16:15 ET."""
    m = _SCHEDULE_RE.match(schedule.strip())
    if not m:
        raise ValueError(f"unparseable schedule: {schedule!r}")
    days = m.group("days").lower()
    if days in ("sat-sun", "sat", "sun", "weekend"):
        return
    sh, sm = (int(x) for x in m.group("start").split(":"))
    eh, em = (int(x) for x in m.group("end").split(":"))
    start_m = sh * 60 + sm
    end_m = eh * 60 + em
    freeze_lo = MARKET_FREEZE_START[0] * 60 + MARKET_FREEZE_START[1]
    freeze_hi = MARKET_FREEZE_END[0] * 60 + MARKET_FREEZE_END[1]
    # Overlap if start < freeze_hi and end > freeze_lo (same-day windows only).
    if end_m > start_m and start_m < freeze_hi and end_m > freeze_lo:
        raise ValueError(
            f"schedule overlaps market freeze 09:30–16:15 ET: {schedule!r}"
        )


def schedule_condition_lines(preset: Optional[str] = None, cfg: Optional[Mapping[str, Any]] = None) -> list[str]:
    return [f"- schedule={s}" for s in schedules_for(preset, cfg)]


def render_or_block(preset: Optional[str] = None, cfg: Optional[Mapping[str, Any]] = None, *, indent: int = 6) -> str:
    pad = " " * indent
    lines = [f"{pad}- or:"]
    for s in schedules_for(preset, cfg):
        lines.append(f"{pad}    - schedule={s}")
    return "\n".join(lines) + "\n"


def apply_schedules_to_mergify_yml(
    text: Optional[str] = None,
    *,
    preset: Optional[str] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    path: Optional[Path] = None,
) -> str:
    """Replace every ``- or:`` schedule block in ``.mergify.yml`` with the preset's schedules."""
    src = text if text is not None else (path or MERGIFY_YML).read_text(encoding="utf-8")
    block = render_or_block(preset, cfg, indent=6)
    # Match the four schedule-bearing or-blocks (queue rules + pull_request_rules).
    matches = list(_OR_BLOCK_RE.finditer(src))
    if len(matches) < 1:
        raise ValueError(".mergify.yml has no schedule or-blocks to replace")
    out = src
    # Replace from the end so offsets stay valid.
    for m in reversed(matches):
        # Only replace blocks that already contain schedule= lines.
        if "schedule=" not in m.group(1):
            continue
        out = out[: m.start(1)] + block + out[m.end(1) :]
    return out


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _days_cover(token: str, weekday: int) -> bool:
    """weekday: Mon=0 … Sun=6."""
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    t = token.lower()
    if t in ("sat-sun",):
        return weekday >= 5
    if t in ("mon-fri",):
        return weekday < 5
    if t in ("tue-sat",):
        return weekday in (1, 2, 3, 4, 5)
    if "-" in t:
        a, b = t.split("-", 1)
        if a in names and b in names:
            i, j = names.index(a), names.index(b)
            if i <= j:
                return i <= weekday <= j
            return weekday >= i or weekday <= j
    if t in names:
        return weekday == names.index(t)
    return False


def in_window(now: Optional[datetime] = None, *, cfg: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Whether ``now`` (ET) falls inside an active Mergify schedule."""
    n = (now or datetime.now(tz=ET)).astimezone(ET)
    c = dict(cfg or load())
    preset = active_preset(c)
    open_schedules: list[str] = []
    for sched in schedules_for(preset, c):
        m = _SCHEDULE_RE.match(sched.strip())
        if not m or not _days_cover(m.group("days"), n.weekday()):
            continue
        sh, sm = _parse_hhmm(m.group("start"))
        eh, em = _parse_hhmm(m.group("end"))
        start = n.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = n.replace(hour=eh, minute=em, second=0, microsecond=0)
        if start <= n < end:
            open_schedules.append(sched)
    freeze = market_freeze_active(n)
    return {
        "as_of": n.isoformat(),
        "timezone": "America/New_York",
        "preset": preset,
        "open": bool(open_schedules) and not freeze,
        "market_freeze": freeze,
        "matching_schedules": open_schedules,
    }


def market_freeze_active(now: Optional[datetime] = None) -> bool:
    n = (now or datetime.now(tz=ET)).astimezone(ET)
    if n.weekday() >= 5:
        return False
    mins = n.hour * 60 + n.minute
    return (MARKET_FREEZE_START[0] * 60 + MARKET_FREEZE_START[1]) <= mins < (
        MARKET_FREEZE_END[0] * 60 + MARKET_FREEZE_END[1]
    )


def upcoming_windows(
    now: Optional[datetime] = None,
    *,
    cfg: Optional[Mapping[str, Any]] = None,
    horizon_h: int = 36,
) -> list[dict[str, Any]]:
    """Next Mergify-open intervals in the next ``horizon_h`` hours (for the Releases page)."""
    n = (now or datetime.now(tz=ET)).astimezone(ET)
    c = dict(cfg or load())
    preset = active_preset(c)
    end = n + timedelta(hours=horizon_h)
    # Sample every minute would be heavy; walk schedule starts in the horizon.
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = n.replace(second=0, microsecond=0)
    while cursor < end:
        snap = in_window(cursor, cfg=c)
        if snap["open"]:
            key = f"{cursor.date().isoformat()}|{snap['matching_schedules'][0]}"
            if key not in seen:
                seen.add(key)
                sched = snap["matching_schedules"][0]
                m = _SCHEDULE_RE.match(sched)
                sh, sm = _parse_hhmm(m.group("start"))  # type: ignore[union-attr]
                eh, em = _parse_hhmm(m.group("end"))  # type: ignore[union-attr]
                start_dt = cursor.replace(hour=sh, minute=sm)
                end_dt = cursor.replace(hour=eh, minute=em)
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)
                state = "OPEN" if start_dt <= n < end_dt else "NEXT"
                if start_dt < n < end_dt:
                    state = "OPEN"
                elif start_dt > n:
                    state = "NEXT"
                else:
                    state = "PAST"
                starts_in = int((start_dt - n).total_seconds())
                rows.append({
                    "window_id": f"mergify-{start_dt.strftime('%Y%m%dT%H%M')}",
                    "local_time": f"{sh:02d}:{sm:02d}",
                    "ends_local": f"{eh:02d}:{em:02d}",
                    "starts_at": start_dt.isoformat(),
                    "ends_at": end_dt.isoformat(),
                    "starts_in_seconds": starts_in if starts_in > 0 else 0,
                    "enabled": True,
                    "role": "mergify",
                    "state": state if state != "PAST" else "NEXT",
                    "reason": f"preset {preset} · {sched}",
                    "note": "Mergify may merge when CI green + operator-merge label",
                    "schedule": sched,
                    "slot": f"{sh:02d}{sm:02d}",
                    "last_shadow_request_at": None,
                    "last_shadow_receipt_state": None,
                    "last_shadow": None,
                })
        cursor += timedelta(minutes=15)
    # De-dupe by starts_at, keep first 8
    uniq: list[dict[str, Any]] = []
    seen_starts: set[str] = set()
    for r in rows:
        if r["starts_at"] in seen_starts:
            continue
        seen_starts.add(r["starts_at"])
        if r["state"] == "PAST":
            continue
        uniq.append(r)
        if len(uniq) >= 8:
            break
    return uniq


def view_for_ops(now: Optional[datetime] = None, *, cfg: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Payload for Ops Controls Mergify panel and Releases windows section."""
    n = (now or datetime.now(tz=ET)).astimezone(ET)
    c = dict(cfg or load())
    preset = active_preset(c)
    presets = c.get("presets") or {}
    row = presets.get(preset) or {}
    snap = in_window(n, cfg=c)
    windows = upcoming_windows(n, cfg=c)
    return {
        "schema": SCHEMA,
        "as_of": n.isoformat(),
        "timezone": "America/New_York",
        "preset": preset,
        "preset_label": (row.get("label") if isinstance(row, Mapping) else None) or preset,
        "preset_description": (row.get("description") if isinstance(row, Mapping) else None),
        "schedules": schedules_for(preset, c),
        "open_now": snap["open"],
        "market_freeze": snap["market_freeze"],
        "matching_schedules": snap["matching_schedules"],
        "windows": windows,
        "setting_key": SETTING_KEY,
        "presets_available": [
            {"id": k, "label": (v or {}).get("label") or k, "description": (v or {}).get("description")}
            for k, v in presets.items() if isinstance(v, Mapping)
        ],
        "manual_path": (
            "Change preset under Ops → Controls → Flags (mergify.windows_preset), then open a PR that "
            "runs scripts/render_mergify_windows.py so .mergify.yml on main matches. Mergify only reads "
            "schedules from main's .mergify.yml. Market freeze Mon–Fri 09:30–16:15 ET never opens."
        ),
    }


def set_preset_in_config(preset: str, *, path: Optional[Path] = None) -> dict[str, Any]:
    """Update ``preset`` in config/mergify_windows.json (local edit for a PR)."""
    p = Path(path) if path else CONFIG_PATH
    c = load(p)
    if preset not in (c.get("presets") or {}):
        raise KeyError(f"unknown preset: {preset}")
    schedules_for(preset, c)  # validate freeze
    c["preset"] = preset
    p.write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
    return c
