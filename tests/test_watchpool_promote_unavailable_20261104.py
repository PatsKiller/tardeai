"""FQ-079 (codex P2660-R1): BOTH unavailable facts are explained, and neither disables Promote.

The audit's observed row is an UNAVAILABLE comparison badge beside a working Promote on a suggestion that DOES carry a
directive; the missing-directive case is a different fact. A first pass explained only the second, so this file pins both,
and pins that the control itself is not disabled or re-gated by either branch.

Hermetic: reads the page source. No browser, no network, no data.

ANCHOR: WATCHPOOL_PROMOTE_UNAVAILABLE_20261104
"""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "apps/command-center-v3/src/pages/WatchpoolHub.tsx").read_text(
    encoding="utf-8"
)


def test_the_unavailable_comparison_is_explained_when_a_directive_exists():
    # cx-openai-2 F1: the producer emits lowercase 'unavailable' (directive_promotion.get_divergence_status);
    # site_payload_reads passes it through without normalisation, so the check must be case-insensitive.
    assert "String(h.divergence || '').toUpperCase() === 'UNAVAILABLE'" in SRC, (
        "the id-present / UNAVAILABLE check must normalise case, or the producer's lowercase value slips through"
    )
    assert "Street comparison unavailable" in SRC
    # cx-openai-2 F2: the field is the internal-vs-Street divergence, not a portfolio/book comparison.
    assert "against your book" not in SRC, "the explanation must not call the Street divergence a book comparison"


def test_the_missing_directive_case_is_still_explained():
    assert "{!h.directive_id && (" in SRC
    assert "no directive is attached to this suggestion" in SRC


def test_neither_branch_disables_or_regates_promote():
    # The control keeps its original guard: busy, or no directive id. Divergence must not enter it.
    assert "disabled={busy || !h.directive_id}" in SRC
    assert "divergence" not in SRC.split("onClick={() => promote(")[1].split("</button>")[0]
