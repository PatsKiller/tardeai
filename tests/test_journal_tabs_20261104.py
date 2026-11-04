"""FQ-041: at phone width the journal tab row wraps instead of scrolling its last tab off-screen.

Registered as the CI gate's file so the shard runner (pytest) executes it; a `.mjs` file cannot be collected.
``apps/command-center-v3/src/lib/journalTabs.view.test.mjs`` mirrors it for a node run.

Hermetic: reads the stylesheet and the page source. No browser, no network, no data.

ANCHOR: JOURNAL_TABS_20261104
"""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "apps/command-center-v3/src"
CSS = (APP / "index.css").read_text(encoding="utf-8")
HUB = (APP / "pages/JournalHub.tsx").read_text(encoding="utf-8")


def _phone_block() -> str:
    match = re.search(r"@media[^{]*max-width:\s*4[0-9]{2}px[^{]*\{([\s\S]*?)\n\}", CSS)
    assert match, "no phone-width media query found in index.css"
    return match.group(1)


def test_the_phone_rule_makes_the_tab_row_wrap():
    block = _phone_block()
    rule = re.search(r"\.hub-tabs\s*\{([\s\S]*?)\}", block)
    assert rule, "the phone media query does not address .hub-tabs"
    body = rule.group(1)
    assert re.search(r"flex-wrap:\s*wrap", body), "phone .hub-tabs does not wrap"
    assert re.search(r"overflow-x:\s*visible", body), "phone .hub-tabs still creates a horizontal scroller"


def test_all_fifteen_tab_labels_are_still_rendered():
    tabs = re.search(r"const TABS = \[([\s\S]*?)\] as const", HUB)
    assert tabs, "TABS list not found — did the page change shape?"
    assert tabs.group(1).count("'") / 2 == 15, "expected 15 journal tabs, labels changed"
