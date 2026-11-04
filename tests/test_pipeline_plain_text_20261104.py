"""FQ-033: the work pipeline leads in words; checkout paths and shell errors sit behind Technical.

Registered as the CI gate's file so the shard runner (pytest) executes it; a `.mjs` file cannot be collected.
``apps/command-center-v3/src/lib/pipelinePlainText.view.test.mjs`` mirrors it for a node run.

Hermetic: reads the panel source. No browser, no network, no data.

ANCHOR: PIPELINE_PLAIN_TEXT_20261104
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "apps/command-center-v3/src/pages/WorkPipelinePanel.tsx").read_text(encoding="utf-8")


def test_the_technical_disclosure_exists_and_is_closed_by_default():
    assert re.search(
        r'function Technical\(\{ label, children \}[^)]*\) \{[\s\S]*?<details data-testid="technical-details"', SRC
    ), "no Technical disclosure component (a closed <details>) in the panel"
    assert re.search(r"<summary style=\{\{ \.\.\.small, cursor: 'pointer' \}\}>", SRC), (
        "the disclosure summary is not tappable"
    )


def test_the_checkout_path_is_not_inline():
    assert not re.search(r"· \{it\.where\.worktree\}", SRC), (
        "the raw checkout path is still printed inline in the Where cell"
    )
    assert re.search(
        r'<Technical label="Technical: where the work is checked out">\{it\.where\.worktree\}</Technical>', SRC
    ), "the checkout path is not rendered under Technical"


def test_the_census_banner_leads_with_a_sentence():
    assert "PR census could not refresh — the last good copy is shown" in SRC, (
        "the census banner does not say, in words, that it could not refresh"
    )
    assert re.search(
        r'<Technical label="Technical: why the census could not refresh">\{census\.warning\}</Technical>', SRC
    ), "the census shell error is not rendered under Technical"


def test_a_refused_action_leads_with_a_sentence():
    assert "That action did not go through. The service's exact message is under Technical." in SRC, (
        "a failed action does not lead with a plain sentence"
    )
    assert not re.search(r"refused: \$\{r\.error", SRC), (
        "the raw service error is still concatenated into the visible message"
    )
    assert "technical: raw || undefined" in SRC, "the raw service text is not carried in the technical field"
    assert "busy.technical ? <Technical" in SRC, "the technical text is not rendered as a disclosure"


def test_nothing_was_removed():
    assert len(re.findall(r"it\.where\.worktree", SRC)) >= 2, "the checkout path value was removed, not moved"
    assert len(re.findall(r"census\??\.warning", SRC)) >= 2, "the census warning value was removed, not moved"


def test_the_phone_layout_still_exists_and_hides_nothing_technical():
    for width in (390, 412):
        pattern = r"@media \(max-width: " + str(width) + r"px\) \{([\s\S]*?)\n      \}"
        match = re.search(pattern, SRC)
        if match:
            assert "technical" not in match.group(1).lower(), f"the {width}px block hides Technical"
    assert "@media (max-width: 760px)" in SRC, "the phone layout breakpoint disappeared"
