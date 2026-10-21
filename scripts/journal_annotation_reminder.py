#!/usr/bin/env python3
"""Daily TradeInView annotation reminder via Telegram (weekdays 18:30 ET)."""
from __future__ import annotations
import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (the bare scheduled run (it always sends)). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "journal-annotation-reminder"
    _dr_would = (
        "load the .env, count unannotated TradeInView journal entries via api_v2._journal_reminder and send "
        "the reminder through the Telegram chokepoint"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="unannotated_trade"))
    raise SystemExit(0)

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