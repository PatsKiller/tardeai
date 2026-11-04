"""FQ-075: the watchlist row states its state in plain words, never in screaming policy codes.

Registered as the CI gate's file, so the shard runner (pytest) executes it. It mirrors
``apps/command-center-v3/src/lib/watchlistPlainWords.view.test.mjs`` assertion for assertion; that file stays for a
developer running it directly with node.

Hermetic: reads the page source. No browser, no network, no data.

ANCHOR: WATCHLIST_PLAIN_WORDS_20261104
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "apps/command-center-v3/src/pages/WatchlistIntelligenceBoard.tsx").read_text(encoding="utf-8")


def test_the_raw_code_line_no_longer_renders():
    assert not re.search(r"Provider NONE · Model NONE · Policy NO_CALL", SRC), (
        "the raw code line still renders verbatim"
    )


def test_plain_wording_for_no_provider_and_not_scheduled():
    assert "No provider or model assigned" in SRC, 'plain wording for "no provider/model" missing'
    assert "not scheduled" in SRC, 'plain wording for "not scheduled" missing'


def test_unknown_codes_are_decoded_not_shouted():
    assert "export function plainReason" in SRC, "no plainReason mapping — an unknown code would still shout"
    match = re.search(r"const PLAIN_REASON: Record<string, string> = \{(.*?)\}", SRC, re.S)
    assert match, "PLAIN_REASON map missing"
    body = match.group(1)
    assert re.search(r"NOT_SCHEDULED: 'not scheduled'", body), "NOT_SCHEDULED not mapped"
    assert re.search(r"NO_CALL: 'no external call'", body), "NO_CALL not mapped"
