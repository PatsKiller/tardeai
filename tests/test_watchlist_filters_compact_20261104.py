"""FQ-077: at phone width the filter stack collapses to a one-line summary; nothing is removed.

Registered as the CI gate's file so the shard runner (pytest) executes it; a `.mjs` file cannot be collected.
``apps/command-center-v3/src/lib/watchlistFiltersCompact.view.test.mjs`` mirrors it for a node run.

Hermetic: reads the page source. No browser, no network, no data.

ANCHOR: WATCHLIST_FILTERS_COMPACT_20261104
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "apps/command-center-v3/src/pages/WatchIntelligenceUnified.tsx").read_text(encoding="utf-8")


def test_the_filter_stack_collapses_to_a_named_summary():
    assert 'data-testid="filters-compact"' in SRC, "no compact filter summary on the phone"
    assert re.search(r'<details data-testid="filters-compact"', SRC), (
        "the summary is not a details/summary (filters not reachable)"
    )
    assert re.search(
        r"Filters\{activeChips\.length \? ` · \$\{activeChips\.length\} active` : ' · none active'\}", SRC
    ), "the summary does not state how many filters are active"


def test_the_summary_is_scoped_to_phone_width():
    assert "max-width: 760px" in SRC, "the compact summary is not scoped to phone width"


def test_every_filter_is_still_present():
    assert len(re.findall(r'data-filter="', SRC)) >= 4, "filters were removed rather than collapsed"
