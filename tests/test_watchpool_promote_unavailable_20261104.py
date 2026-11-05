"""FQ-079 (codex P2660-R1): BOTH unavailable facts are explained, and neither disables Promote.

The audit's observed row is an UNAVAILABLE comparison badge beside a working Promote on a suggestion that DOES carry a
directive; the missing-directive case is a different fact. A first pass explained only the second.

cc-deepseek-3's review of #2660 at a098e91b: the earlier version of this file asserted strings in the page source, so it
passed while the producer's lowercase "unavailable" never matched an uppercase literal. The sentence now lives in a
component (`watchpoolPromoteNote.tsx`) and the RENDERED case is asserted by
`apps/command-center-v3/src/lib/watchpool.promoteNote.view.test.mjs`, which feeds the component the producer's own value.
This file keeps the page-level invariants: the page renders that component, and neither branch disables or re-gates Promote.

Hermetic: reads source. No browser, no network, no data.

ANCHOR: WATCHPOOL_PROMOTE_UNAVAILABLE_20261104
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "apps/command-center-v3/src/pages/WatchpoolHub.tsx").read_text(encoding="utf-8")
NOTE = (ROOT / "apps/command-center-v3/src/lib/watchpoolPromoteNote.tsx").read_text(encoding="utf-8")
VIEW_TEST = ROOT / "apps/command-center-v3/src/lib/watchpool.promoteNote.view.test.mjs"


def test_the_page_renders_the_extracted_note():
    assert "import { PromoteUnavailableNote } from '../lib/watchpoolPromoteNote'" in SRC, (
        "the page must render the extracted component, so the rendered test exercises what ships"
    )
    assert "<PromoteUnavailableNote directiveId={h.directive_id} divergence={h.divergence} />" in SRC


def test_the_note_normalises_the_producer_case():
    # The producer emits lowercase 'unavailable' (build_pro_analyst_read_model.py / directive_promotion).
    assert "String(divergence || '').toUpperCase() !== 'UNAVAILABLE'" in NOTE, (
        "the check must normalise case, or the producer's lowercase value slips through"
    )
    assert "Street comparison unavailable" in NOTE
    assert "against your book" not in NOTE, "the explanation must not call the Street divergence a book comparison"


def test_the_missing_directive_case_is_still_explained():
    assert "if (!directiveId)" in NOTE
    assert "no directive is attached to this suggestion" in NOTE


def test_neither_branch_disables_or_regates_promote():
    # The control keeps its original guard: busy, or no directive id. Divergence must not enter it.
    assert "disabled={busy || !h.directive_id}" in SRC
    assert "divergence" not in SRC.split("onClick={() => promote(")[1].split("</button>")[0]


def test_the_rendered_case_is_asserted_somewhere():
    assert VIEW_TEST.is_file(), "the rendered view test must exist"
    body = VIEW_TEST.read_text(encoding="utf-8")
    assert "divergence: 'unavailable'" in body, "the rendered test must feed the producer's own lowercase value"
    assert "PromoteUnavailableNote" in body
