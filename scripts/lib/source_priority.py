"""Which source a scanner row is *labelled* with when several sources claim the symbol.

2026-09-28 (plan root cause 4): `api_v2` aggregated `watchlist_items.source` alphabetically and
took the first, so `ai_discovered` outranked `screener` for every symbol both had — the desk saw
27 "AI" rows and 9 "screener" rows for a universe the screener produced. The order is declared in
`assets/screeners.yaml::source_label_priority`; every source is still exposed as `sources_all`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

DEFAULT_PRIORITY = ["screener", "social", "ai_discovered", "topic_research", "portfolio", "manual"]
_ROOT = Path(__file__).resolve().parents[2]


def load_priority(config_path: Path | None = None) -> list[str]:
    path = config_path or (_ROOT / "assets" / "screeners.yaml")
    try:
        import yaml
        cfg = yaml.safe_load(path.read_text()) or {}
        pri = cfg.get("source_label_priority")
        if isinstance(pri, list) and pri:
            return [str(x) for x in pri]
    except Exception:
        pass
    return list(DEFAULT_PRIORITY)


def pick_primary_source(sources: Iterable[str] | None, priority: list[str] | None = None,
                        default: str = "screener") -> str:
    """Highest-priority known source; unknown sources rank after known ones, alphabetically."""
    pri = priority or load_priority()
    seen = [str(s) for s in (sources or []) if s]
    if not seen:
        return default
    rank = {name: i for i, name in enumerate(pri)}
    return sorted(set(seen), key=lambda s: (rank.get(s, len(pri)), s))[0]
