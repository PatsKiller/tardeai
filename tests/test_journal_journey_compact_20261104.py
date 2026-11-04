"""FQ-042: on a phone the journal journey list is dated summaries with the full row behind a toggle.

Registered as the CI gate's file so the shard runner (pytest) executes it; a `.mjs` file cannot be collected.
``apps/command-center-v3/src/lib/journalJourneyCompact.view.test.mjs`` mirrors it for a node run.

Hermetic: reads the page source. No browser, no network, no data.

ANCHOR: JOURNAL_JOURNEY_COMPACT_20261104
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "apps/command-center-v3/src/pages/TradeJourney.tsx").read_text(
    encoding="utf-8"
)


def test_the_row_has_a_compact_mode():
    assert re.search(r"compact\?:\s*boolean", SRC), "Row has no compact prop"


def test_the_compact_row_is_a_dated_summary_with_details_on_demand():
    assert re.search(r'<details[^>]*data-testid="tj-row"', SRC), (
        "the compact row is not a details/summary (no details-on-demand)"
    )
    assert "<summary" in SRC, "no summary line in the compact row"


def test_the_compact_summary_keeps_a_real_tappable_primary_action():
    # The phone proof locates the primary action through [data-testid="tj-row"], which in compact mode is the details;
    # a collapsed grid is not tappable, so the summary must carry the button.
    assert re.search(r'<summary[\s\S]{0,600}data-testid="tj-open-journey"', SRC), (
        "the compact summary has no tappable primary action"
    )
    assert re.search(r"data-testid=\{compact \? 'tj-row-full' : 'tj-row'\}", SRC), (
        "exactly one node per journey must answer to tj-row"
    )
    assert re.search(r"data-testid=\{compact \? 'tj-open-journey-full' : 'tj-open-journey'\}", SRC), (
        "exactly one node per journey must answer to tj-open-journey (two broke the phone proof)"
    )


def test_the_list_passes_compact_on_a_phone():
    assert re.search(r"compact=\{phone\}", SRC), "the list does not pass compact on phone"


def test_nothing_is_removed():
    assert re.search(r'const grid = \(\s*<div className="tradeinview-journey-row"', SRC), (
        "the original full row was not preserved"
    )
    assert re.search(r"if \(!compact\) return grid", SRC), "desktop no longer renders the full row"
