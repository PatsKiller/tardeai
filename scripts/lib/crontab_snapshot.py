"""Read the user crontab, or a fresh cron-written snapshot when `crontab -l` is denied.

Why (R-03, 2026-09-26): the health agent runs under `NoNewPrivileges=true`, which
strips the setgid bit crontab needs, so `crontab -l` fails with "Permission
denied" and the agent skips every cron_missing check. A dead cron, a stale
cron and the P1 scheduler defects were all invisible to it.

The snapshot is written by cron itself (a plain `crontab -l > <path>` line; see
SNAPSHOT_CRON_LINE) into data/runtime, which CURRENT and the dev tree both link
to persistent-state. A snapshot older than MAX_AGE_S is reported as stale and
NOT used, so a dead writer cannot masquerade as a live crontab.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_REL = Path("data") / "runtime" / "crontab_snapshot.txt"
MAX_AGE_S = int(os.environ.get("TRADEAI_CRONTAB_SNAPSHOT_MAX_AGE_S", str(2 * 3600)))
SNAPSHOT_CRON_LINE = (
    "*/20 * * * * crontab -l > /home/johnclaw/trade-ai-releases/persistent-state/data/runtime/"
    "crontab_snapshot.txt.tmp 2>/dev/null && mv -f /home/johnclaw/trade-ai-releases/persistent-state/"
    "data/runtime/crontab_snapshot.txt.tmp /home/johnclaw/trade-ai-releases/persistent-state/data/runtime/"
    "crontab_snapshot.txt  # R-03: readable crontab snapshot for the hardened health agent"
)


@dataclass
class CrontabRead:
    text: str
    source: str            # "crontab" | "snapshot" | "none"
    age_s: Optional[float] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.source in ("crontab", "snapshot")


def snapshot_path(root: Path | None = None) -> Path:
    override = os.environ.get("TRADEAI_CRONTAB_SNAPSHOT_PATH")
    if override:
        return Path(override)
    return (root or ROOT) / SNAPSHOT_REL


def read_crontab(*, root: Path | None = None, max_age_s: int = MAX_AGE_S,
                 runner=None, now: Optional[float] = None) -> CrontabRead:
    """`crontab -l` when permitted; else the fresh snapshot; else an explicit failure.

    `runner` resolves to subprocess.run AT CALL TIME so tests that monkeypatch
    subprocess.run (the existing cron-sanity suites do) still take effect."""
    run = runner or subprocess.run
    try:
        proc = run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return CrontabRead(text=proc.stdout or "", source="crontab")
        err = (proc.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    denied = ("Permission denied" in err) or ("fopen" in err) or ("Operation not permitted" in err)
    snap = snapshot_path(root)
    if snap.is_file():
        age = (now if now is not None else time.time()) - snap.stat().st_mtime
        if age <= max_age_s:
            return CrontabRead(text=snap.read_text(encoding="utf-8", errors="replace"),
                               source="snapshot", age_s=age, error=err or None)
        return CrontabRead(text="", source="none", age_s=age,
                           error=f"crontab -l denied ({err[:80]}) and snapshot is stale ({age/3600:.1f}h > {max_age_s/3600:.1f}h): {snap}")
    return CrontabRead(text="", source="none",
                       error=(f"crontab -l denied ({err[:80]}) and no snapshot at {snap}" if denied
                              else f"crontab -l failed: {err[:120]}"))


__all__ = ["CrontabRead", "read_crontab", "snapshot_path", "SNAPSHOT_CRON_LINE", "MAX_AGE_S"]
