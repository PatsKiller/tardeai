"""holdings_guard.py — the MANDATORY holdings / current-state wipe-guard import home.

Every code path that writes data/portfolios/state/holdings.json must go through
protected_holdings_write() so an empty/zeroed/failed/catastrophically-low payload fails closed
(prior snapshot kept) instead of wiping the file. The implementation is reused as-is from
schwab_position_sync (Gate B); this neutral module is where the general (non-Schwab) writers import it
so the guard reads correctly at the call sites.

General writers: protected_holdings_write(payload, source="<name>")           # protect_basis defaults False
Schwab sync:     protected_holdings_write(payload, source="schwab", protect_basis=True)
"""
from schwab_position_sync import (  # noqa: F401
    protected_holdings_write, sane_payload, canonical_assert, MIN_TOTAL, CATASTROPHIC_DROP_FRACTION,
)
