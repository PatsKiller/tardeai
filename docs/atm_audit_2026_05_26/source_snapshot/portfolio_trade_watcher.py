"""portfolio_trade_watcher.py — Auto-trigger portfolio refresh on new Schwab CSV export.

HOW IT WORKS:
  Watches your Schwab CSV export folder. When a new CSV lands (after you
  export a trade from Schwab), it automatically fires run_portfolio_monthly.bat
  so the AI analysis reflects your actual current position immediately.

HOW TO USE:
  Option A — Run manually when you want watching active:
    python scripts\\portfolio_trade_watcher.py

  Option B — Add to Windows Task Scheduler (runs at login, silent background):
    Program:  venv\\Scripts\\python.exe
    Args:     scripts\\portfolio_trade_watcher.py
    Start in: C:\\Users\\john\\OneDrive\\AI_Skilss\\live_skills\\trade-ai-v12-rebuild

WHAT IT WATCHES:
  - Downloads folder + Documents folder + data\\imports folder
  - Any new CSV matching Schwab export naming patterns
  - Waits 5s after detection (ensures file is fully written before reading)
  - Debounce: will not fire more than once per 5 minutes

CONFIGURATION: Edit the PROJECT_ROOT and WATCH_FOLDERS variables below.
"""
from __future__ import annotations
import os, sys, re, time, subprocess
from pathlib import Path
from datetime import datetime, timedelta

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(
    r"C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"
)

WATCH_FOLDERS = [
    Path(os.path.expanduser("~")) / "Downloads",
    Path(os.path.expanduser("~")) / "Documents",
    PROJECT_ROOT / "data" / "imports",
]

# Any new CSV whose name matches one of these patterns fires the refresh
TRIGGER_PATTERNS = [
    r"(?i).*positions.*\.csv$",
    r"(?i).*transactions.*\.csv$",
    r"(?i).*schwab.*\.csv$",
    r"(?i).*individual.*\.csv$",
    r"(?i).*rollover.*\.csv$",
    r"(?i).*roth.*\.csv$",
    r"(?i).*portfolio.*\.csv$",
]

DEBOUNCE_SECONDS  = 300   # 5 min — prevents double-firing on rapid exports
POLL_INTERVAL     = 3     # seconds between folder scans
LOG_FILE          = PROJECT_ROOT / "logs" / "trade_watcher.log"

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _matches(name: str) -> bool:
    return any(re.match(p, name) for p in TRIGGER_PATTERNS)


def _fire_refresh() -> bool:
    bat = PROJECT_ROOT / "run_portfolio_monthly.bat"
    if not bat.exists():
        _log(f"ERROR  BAT not found: {bat}")
        return False
    _log(f"LAUNCH {bat.name}")
    try:
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen([str(bat)], cwd=str(PROJECT_ROOT), creationflags=flags)
        _log("OK     Portfolio refresh launched — AI analysis updates in ~2 min")
        return True
    except Exception as exc:
        _log(f"ERROR  Could not launch bat: {exc}")
        return False

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def watch() -> None:
    _log("START  Portfolio Trade Watcher")
    active = [f for f in WATCH_FOLDERS if f.exists()]
    _log(f"WATCH  {', '.join(str(f) for f in active)}")
    _log(f"CFG    debounce={DEBOUNCE_SECONDS}s  poll={POLL_INTERVAL}s")

    # Snapshot existing CSV mtimes so we only react to NEW/changed files
    known: dict[Path, float] = {}
    for folder in WATCH_FOLDERS:
        if folder.exists():
            for f in folder.glob("*.csv"):
                known[f] = f.stat().st_mtime

    last_fired = datetime.min

    while True:
        try:
            for folder in WATCH_FOLDERS:
                if not folder.exists():
                    continue
                for f in folder.glob("*.csv"):
                    mtime = f.stat().st_mtime
                    if f not in known or known[f] != mtime:
                        known[f] = mtime
                        if _matches(f.name):
                            _log(f"DETECT {f.name}")
                            elapsed = (datetime.now() - last_fired).total_seconds()
                            if elapsed >= DEBOUNCE_SECONDS:
                                _log("WAIT   5s for file to finish writing...")
                                time.sleep(5)
                                if _fire_refresh():
                                    last_fired = datetime.now()
                            else:
                                wait = int(DEBOUNCE_SECONDS - elapsed)
                                _log(f"SKIP   debounce active — next fire in {wait}s")
            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            _log("STOP   Watcher stopped by user")
            break
        except Exception as exc:
            _log(f"WARN   {exc}")
            time.sleep(10)


if __name__ == "__main__":
    watch()
