"""FQ-078: research cards explain readiness in plain words; the raw enum stays in the provenance panel only.

This pytest file is registered as the CI gate's file so the shard runner executes it; a `.mjs` file cannot be
collected. It covers the rollback component **only**. The live route is covered by
``apps/command-center-v3/src/lib/watchlistReadinessWords.view.test.mjs``, which actually renders
``WatchIntelligenceUnified``, and which ``apps/command-center-v3/package.json``'s `build` step runs — that is the entry
that fails when the live page's expressions are reverted. This file is not that entry and must not claim to be:
cx-openai-4's R2 on #2611 reverted the live page and this file stayed green (3 passed), which is why the build-chain
wiring below is asserted rather than assumed.

Hermetic: reads the component source and the build script. No browser, no network, no data.

ANCHOR: WATCHLIST_READINESS_WORDS_20261104
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "apps/command-center-v3/src/components/rockville/WatchCardV2.tsx").read_text(encoding="utf-8")
BUILD_CMD = "node --experimental-strip-types src/lib/watchlistReadinessWords.view.test.mjs"


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


def test_the_build_chain_runs_the_live_page_regression():
    """The live-page entry must be invoked by CI, not merely present in the tree.

    Two failure modes this catches, both seen in this fleet: a regression file that exists and runs nowhere, and a
    build-line union merge that resolves by taking one side and silently drops the other's new step.
    """
    pkg = json.loads((ROOT / "apps/command-center-v3/package.json").read_text(encoding="utf-8"))
    build = pkg["scripts"]["build"]
    assert BUILD_CMD in build, (
        "apps/command-center-v3 `build` no longer runs the live-page regression "
        f"({BUILD_CMD}); a reverted WatchIntelligenceUnified would pass every registered check"
    )
    # It must run BEFORE the build artefacts are produced, so a broken page never reaches `tsc`/`vite build` as a pass.
    assert build.index(BUILD_CMD) < build.index("tsc && vite build"), (
        "the live-page regression runs after `tsc && vite build`; a failure there still emits a build"
    )
