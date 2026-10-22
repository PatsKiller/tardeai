"""desk_session.py — the options desk's session label, gated on the NYSE calendar (2026-10-22).

The desk build stamps `market_session` with scripts/lib/canonical_observation.market_session, a coarse label on a
fixed -4h ET offset (wrong by an hour from November to March, blind to holidays). The quote refresh and the desk
staleness monitor need the gate to be right, so REGULAR here means scripts/lib/cio_market_session.is_rth (NYSE
calendar, DST-aware); any other moment keeps the coarse vocabulary, with a coarse REGULAR outside RTH read as CLOSED.
Pure; imports no broker, DB or network module.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROPOSALS_REL = ("data", "portfolios", "state", "options_proposals.json")


def proposals_path() -> Path:
    """The desk snapshot under the persistent-state root (lib.persistent_overlay, the resolver the holdings store uses),
    else the checkout's data/portfolios/state (dev). The writer, scripts/options_engine.py, writes the checkout path,
    which the served release symlinks to the persistent root."""
    try:
        from scripts.lib.persistent_overlay import overlay_data_source
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from lib.persistent_overlay import overlay_data_source  # type: ignore[no-redef]
    return Path(overlay_data_source(canonical_source=ROOT)).joinpath(*PROPOSALS_REL)


def market_session(at: datetime) -> str:
    try:
        from scripts.lib.canonical_observation import market_session as coarse
        from scripts.lib.cio_market_session import is_rth
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from lib.canonical_observation import market_session as coarse  # type: ignore[no-redef]
        from lib.cio_market_session import is_rth  # type: ignore[no-redef]
    if is_rth(at):
        return "REGULAR"
    label = coarse(at)
    return "CLOSED" if label == "REGULAR" else label
