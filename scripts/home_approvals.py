#!/usr/bin/env python3
"""home_approvals.py — CLI/API entry point for the Home v008 "Needs you" board.

    scripts/home_approvals.py --state-root <root> ask --type merge_pr \
        --title "Merge #2518" --why "..." --rule "AGENTS §9" --what-happens "..." \
        --risk "..." --undo "..." --requester cc-deepseek-5 --facts '{"pr": 2518, "head_sha": "<40-hex>"}'
    scripts/home_approvals.py --state-root <root> list
    scripts/home_approvals.py --state-root <root> approve <id> --actor operator \
        --operator-session --csrf-ok     # the Command Center server sets the last two

Agents create requests with `ask`; only the Command Center server may set `--operator-session` and `--csrf-ok`, and the
library refuses every decision without both. See scripts/lib/home_approvals.py for the rails and the closed action list.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.home_approvals import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
