"""§6 budget: detail views are sampled per page, and every row is still covered within a week.

All rows on Home and on top lists (Best opportunities, Home top 5); up to 20 rows elsewhere, rotating every RUN so the
sampling is coverage over time rather than the same twenty rows forever.

cx-openai-4 R4 on #2648 found two ways the old code missed the contract while its own tests were green: the caller
passes the REAL route ("/", "/samples/opens") and only the bare alias "home" was recognised, so the home page's 55 rows
were capped at 20; and the rotation stepped once per ISO week, so the five runs in a week all re-opened the same twenty
rows and the rest of the table was never reached. Both are fixed here — routes are normalised to a page kind, and the
step is the lane's run slot — so ceil(n / cap) consecutive runs cover every row: three runs for a 55-row table, well
inside the five a week.
"""

from __future__ import annotations

DETAILS_PER_PAGE = 20

#: Pages whose every row is opened. Keys are normalised page kinds (see `page_kind`), never raw routes.
TOP_LIST_PAGES = frozenset({"home", "best_opportunities", "home_top5"})


def page_kind(route: str | None) -> str:
    """The page a sampled opener lives on, normalised from the real route.

    `/`, `/v3` and `home` are all the home page; `/samples/opens` and `best-opportunities` are different pages and
    neither is a top list. A query string or a fragment never changes the page.
    """
    parts = [p for p in str(route or "").split("?")[0].split("#")[0].strip("/").split("/") if p]
    if parts and parts[0].lower() == "v3":
        parts = parts[1:]
    return "_".join(parts).replace("-", "_").lower() if parts else "home"


def selected_indices(row_count: int, *, page: str, run_index: int, cap: int = DETAILS_PER_PAGE) -> list[int]:
    """Indices to open on this run, deterministic in (page, run_index).

    A top list takes every row. Every other page takes `cap` rows, chosen by walking the list from an offset that
    advances once per RUN — so successive runs start where the last one stopped and the whole list is covered.
    """
    n = max(0, int(row_count))
    if n == 0:
        return []
    if page_kind(page) in TOP_LIST_PAGES:
        return list(range(n))
    take = min(n, max(0, int(cap)))
    if take >= n:
        return list(range(n))
    start = (max(0, int(run_index)) * take) % n
    return [(start + i) % n for i in range(take)]


def runs_to_cover(row_count: int, cap: int = DETAILS_PER_PAGE) -> int:
    """How many runs cover every row once (0 rows → 0)."""
    n = max(0, int(row_count))
    take = max(1, int(cap))
    return 0 if n == 0 else -(-n // take)
