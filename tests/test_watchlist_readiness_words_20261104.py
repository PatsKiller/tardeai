"""FQ-078: research cards explain readiness in plain words; the raw enum stays in the provenance panel only.

Registered as the CI gate's file so the shard runner (pytest) executes it; a `.mjs` file cannot be collected.
``apps/command-center-v3/src/lib/watchlistReadinessWords.view.test.mjs`` mirrors it for a node run.

Hermetic: reads the component source. No browser, no network, no data.

ANCHOR: WATCHLIST_READINESS_WORDS_20261104
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "apps/command-center-v3/src/components/rockville/WatchCardV2.tsx").read_text(encoding="utf-8")


def test_the_plain_words_mapping_covers_the_states_the_audit_saw():
    assert re.search(r"export function freshnessWords", SRC), "no plain-words mapping"
    assert "CURRENT: 'up to date'" in SRC, "CURRENT not mapped to words"
    assert "AFTER_HOURS_CURRENT: 'up to date after the close'" in SRC, "AFTER_HOURS_CURRENT not mapped"
    assert "DATA_UNAVAILABLE: 'unavailable — no recent read succeeded'" in SRC, "DATA_UNAVAILABLE not mapped"


def test_the_main_line_uses_words_not_the_enum():
    match = re.search(r"data-provenance-line[\s\S]{0,300}", SRC)
    main = match.group(0) if match else ""
    assert re.search(r"\{freshnessWords\(freshnessState\)\}", main), "the main reading line still prints the raw enum"
    assert not re.search(r"\{freshnessState \|\| 'DATA_UNAVAILABLE'\}", main), (
        "the main line still falls back to the raw code"
    )


def test_the_provenance_panel_keeps_the_raw_enum():
    assert re.search(r"<div>freshness: \{freshnessState \|\| '—'\}</div>", SRC), (
        "the provenance panel lost the raw enum"
    )
