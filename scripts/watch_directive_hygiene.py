#!/usr/bin/env python3
"""Watch Desk v2 (B2): weekly directive hygiene.

Sunday cron: auto-apply dedup tiers 1–2 (malformed + dead — reversible archives
by design), then dry-run tier 3 (family merges) and Telegram the plan for
one-tap operator review. Never applies tier 3 automatically.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _run(args: list[str]) -> str:
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "watch_directive_dedup.py"), *args],
                        capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    return (cp.stdout or "") + (cp.stderr or "")


def main() -> int:
    applied = _run(["--apply", "--tier", "1", "--tier", "2"])
    plan3 = _run(["--tier", "3"])

    def _summary(txt: str) -> str:
        for line in txt.splitlines():
            if line.startswith("Would") or line.startswith("Relabeled") or "archive" in line.lower():
                return line.strip()[:220]
        return (txt.strip().splitlines() or ["(no output)"])[-1][:220]

    merge_lines = [ln.strip() for ln in plan3.splitlines() if ln.strip().startswith("#") or "survivor" in ln][:10]
    msg = ("🧹 Watch-directive hygiene (Sunday)\n"
           f"Tiers 1–2 applied: {_summary(applied)}\n"
           "Tier-3 family merges awaiting operator approval:\n"
           + ("\n".join(f"  {ln[:100]}" for ln in merge_lines) if merge_lines else "  none")
           + "\nApprove via: python scripts/watch_directive_dedup.py --apply --tier 3")
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
