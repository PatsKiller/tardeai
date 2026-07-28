"""Factory for durable journal-backed fire performance replay."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


def tracker_from_gateway_snapshot(snapshot: dict[str, Any], cfg) -> Optional[Any]:
    journal = snapshot.get("journal") if isinstance(snapshot, dict) else None
    directory = (journal or {}).get("directory") if isinstance(journal, dict) else None
    if not directory:
        return None
    path = Path(str(directory)).expanduser()
    if not path.is_dir():
        return None
    try:
        from moomoo.gateway_journal import GatewayJournal, JournalBackedFirePerfTracker
    except ImportError:  # pragma: no cover
        from scripts.moomoo.gateway_journal import GatewayJournal, JournalBackedFirePerfTracker  # type: ignore
    return JournalBackedFirePerfTracker(GatewayJournal(path), cfg)
