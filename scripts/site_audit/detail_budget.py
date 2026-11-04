"""§6 budget: detail views are sampled per page, and every row is still covered within a week.

All rows on Home and on top lists (Best opportunities, Home top 5); up to 20 rows elsewhere, rotating weekly so the
sampling is coverage over time rather than the same twenty rows forever.
"""

from __future__ import annotations

DETAILS_PER_PAGE = 20
TOP_LIST_PAGES = frozenset({"home", "best_opportunities", "home_top5"})


def selected_indices(row_count: int, *, page: str, week_index: int, cap: int = DETAILS_PER_PAGE) -> list[int]:
    """Indices to open this week, deterministic in (page, week_index).

    A top list takes every row. Every other page takes `cap` rows, chosen by walking the list from an offset that
    advances once per week — so successive weeks start where the last one stopped and the whole list is covered.
    """
    n = max(0, int(row_count))
    if n == 0:
        return []
    if str(page) in TOP_LIST_PAGES:
        return list(range(n))
    take = min(n, max(0, int(cap)))
    if take >= n:
        return list(range(n))
    start = (max(0, int(week_index)) * take) % n
    return [(start + i) % n for i in range(take)]


def weeks_to_cover(row_count: int, cap: int = DETAILS_PER_PAGE) -> int:
    """How many weekly runs cover every row once (0 rows → 0)."""
    n = max(0, int(row_count))
    take = max(1, int(cap))
    return 0 if n == 0 else -(-n // take)
