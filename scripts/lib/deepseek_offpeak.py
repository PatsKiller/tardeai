"""Official DeepSeek peak/off-peak windows (UTC, half-open).

Peak: 01:00-04:00 and 06:00-10:00 UTC (same as scripts/hermes_llm_failover.py).
Used by the overnight watchlist-agent-jobs wrapper so tests can freeze time
without depending on the shell's wall clock.

READ_ONLY_ADVISORY. No broker / order / stop / risk / 2FA.
"""
from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Official DeepSeek peak windows (half-open, UTC).
# https://api-docs.deepseek.com/quick_start/pricing/
DEEPSEEK_PEAK_UTC = ((1, 4), (6, 10))
SOAK_DEFAULT_USD = 2.00
TRUTHY = {"1", "true", "yes", "on"}


def _as_utc(dt: datetime | None) -> datetime:
    if dt is None:
        raw = (os.getenv("TRADEAI_OFFPEAK_NOW_UTC") or "").strip()
        if raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return _as_utc(parsed)
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_deepseek_peak_utc(dt: datetime | None = None) -> bool:
    """True inside official DeepSeek peak hours (half-open intervals)."""
    when = _as_utc(dt)
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0
    for start, end in DEEPSEEK_PEAK_UTC:
        if start <= hour < end:
            return True
    return False


def allow_deepseek_peak() -> bool:
    """Honor Hermes override: HERMES_ALLOW_DEEPSEEK_PEAK=1 runs during peak."""
    return os.getenv("HERMES_ALLOW_DEEPSEEK_PEAK", "").strip().lower() in TRUTHY


def should_peak_skip(dt: datetime | None = None) -> bool:
    """True when the overnight wrapper should log PEAK_SKIP and exit 0."""
    if allow_deepseek_peak():
        return False
    return is_deepseek_peak_utc(dt)


def resolve_overnight_soak_cap(raw: str | None) -> dict[str, Any]:
    """Overnight-lane-only soak default.

    Unset / blank / non-positive → 2.00 (origin=soak).
    Already set and >0 → keep.
    Malformed / non-finite → fail-closed (ok=False).
    """
    if raw is None or str(raw).strip() == "":
        return {"ok": True, "cap": SOAK_DEFAULT_USD, "origin": "soak"}
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return {"ok": False, "cap": None, "origin": "invalid"}
    if not math.isfinite(value):
        return {"ok": False, "cap": None, "origin": "invalid"}
    if value <= 0:
        return {"ok": True, "cap": SOAK_DEFAULT_USD, "origin": "soak"}
    return {"ok": True, "cap": value, "origin": "keep"}


def _cli(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        args = ["--help"]
    if args[0] in {"-h", "--help"}:
        sys.stdout.write(
            "usage: deepseek_offpeak.py --gate | --resolve-cap\n"
            "  --gate         exit 10 if PEAK_SKIP, else 0\n"
            "  --resolve-cap  print origin=... cap=... ; exit 2 if invalid\n"
        )
        return 0
    if args[0] == "--gate":
        if should_peak_skip():
            sys.stdout.write("PEAK_SKIP\n")
            return 10
        sys.stdout.write("OFFPEAK\n")
        return 0
    if args[0] == "--resolve-cap":
        result = resolve_overnight_soak_cap(os.environ.get("LLM_GLOBAL_DAILY_USD_CAP"))
        if not result["ok"]:
            sys.stdout.write("origin=invalid\n")
            return 2
        sys.stdout.write(f"origin={result['origin']} cap={result['cap']:.2f}\n")
        return 0
    sys.stderr.write(f"unknown command: {args[0]}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
