"""holdings_guard.py — the MANDATORY holdings / current-state wipe-guard import home.

Every code path that writes data/portfolios/state/holdings.json must go through
protected_holdings_write() so an empty/zeroed/failed/catastrophically-low payload fails closed
(prior snapshot kept) instead of wiping the file. The implementation is reused as-is from
schwab_position_sync (Gate B); this neutral module is where the general (non-Schwab) writers import it
so the guard reads correctly at the call sites.

General writers: protected_holdings_write(payload, source="<name>")           # protect_basis defaults False
Schwab sync:     protected_holdings_write(payload, source="schwab", protect_basis=True)
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(_ROOT / "lib"))
from schwab_position_sync import (  # noqa: E402, F401
    protected_holdings_write, sane_payload, canonical_assert, MIN_TOTAL, CATASTROPHIC_DROP_FRACTION,
)
from holdings_sanity import (  # noqa: F401
    validate_payload,
    REASON_VALID_COMPLETE,
    REASON_EMPTY_PAYLOAD,
    REASON_SCHEMA_INVALID,
    REASON_INCOMPLETE_ACCOUNTS,
    REASON_CASH_EXCLUDED,
    REASON_CATASTROPHIC_DROP,
    REASON_POSITION_COUNT_COLLAPSE,
    REASON_EMERGENCY_FLOOR,
)
