#!/usr/bin/env python3
"""Daily TradeInView annotation reminder via Telegram (weekdays 18:30 ET)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def main():
    from api_v2 import _journal_reminder
    r = _journal_reminder()
    print(f"unannotated={r.get('unannotated')} total={r.get('total')}")


if __name__ == "__main__":
    main()