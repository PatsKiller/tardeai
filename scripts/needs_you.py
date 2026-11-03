#!/usr/bin/env python3
"""needs_you.py — CLI/API entry point for the Home v008 "Needs you" board.

    scripts/needs_you.py --state-root <root> ask --type merge_pr --pr 2518 --head <sha> \
        --title "Merge #2518" --why "..." --approve-does "..." --requester cc-deepseek-5
    scripts/needs_you.py --state-root <root> list
    scripts/needs_you.py --state-root <root> approve <request_id> --approver operator \
        --operator-session --csrf-ok            # the Command Center server sets the last two

Agents create requests with `ask`; only the Command Center server may set `--operator-session` and `--csrf-ok`, and the
library refuses any approval without both. See scripts/lib/needs_you.py for the rails and the closed action list.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.needs_you import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
