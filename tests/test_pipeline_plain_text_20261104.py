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


def test_the_census_banner_state_decides_the_sentence():
    """cc-deepseek-8 R1 at 75251580: the old sentence said "could not refresh — the last good copy is shown" for ANY
    truthy warning, including the producer's "first refresh pending" (there is no copy at all) and partial warnings
    after a SUCCEEDING refresh. A presence assertion could not see that, so the sentence is a tested function now."""
    assert "could not refresh — the last good copy is shown" not in SRC, (
        "the panel still asserts a failed refresh for any warning, including before the first one"
    )
    assert "censusView.text" in SRC, "the panel does not render the state-chosen census sentence"
    assert re.search(
        r'<Technical label="Technical: the census report">\{census\.warning\}</Technical>', SRC
    ), "the census report is not rendered under Technical"


def test_a_refused_action_leads_with_a_sentence():
    assert "That action did not go through. The service's exact message is under Technical." in SRC, (
        "a failed action does not lead with a plain sentence"
    )
    assert not re.search(r"refused: \$\{r\.error", SRC), (
        "the raw service error is still concatenated into the visible message"
    )
    assert "technical: raw || undefined" in SRC, "the raw service text is not carried in the technical field"
    assert "busy.technical ? <Technical" in SRC, "the technical text is not rendered as a disclosure"


def test_identifiers_are_not_the_first_thing_read():
    assert re.search(
        r'<Technical label="Technical: item id, design id and batch">[\s\S]{0,400}<span>\{it\.id\}</span>', SRC
    ), "the item id / design id / batch are not under Technical"
    assert re.search(r'<Technical label="Technical: agent session">\{it\.who\.session\}</Technical>', SRC), (
        "the raw agent session id is still inline"
    )


def test_nothing_was_removed():
    assert len(re.findall(r"it\.where\.worktree", SRC)) >= 2, "the checkout path value was removed, not moved"
    assert len(re.findall(r"census\??\.warning", SRC)) >= 2, "the census warning value was removed, not moved"
    assert "{it.id}" in SRC, "the item id was removed, not moved"
    assert "it.who.session" in SRC, "the agent session was removed, not moved"


def test_the_phone_layout_still_exists_and_hides_nothing_technical():
    for width in (390, 412):
        pattern = r"@media \(max-width: " + str(width) + r"px\) \{([\s\S]*?)\n      \}"
        match = re.search(pattern, SRC)
        if match:
            assert "technical" not in match.group(1).lower(), f"the {width}px block hides Technical"
    assert "@media (max-width: 760px)" in SRC, "the phone layout breakpoint disappeared"
