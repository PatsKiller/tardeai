"""Plans page model/CSS guards (2026-11-03): 390 px wrapping, honest step counts, plans.css tokens.

The CC-v3 app has no tsx test harness, so this test reads the stylesheet, the token source and the
view-model/page source directly.

It guards four defects:

* A gap in the plan store must never render as an empty registry (the page gates the empty message
  on `!gap`, and the model turns `store.state != "ok"` into a gap with the server's reason).
* A registered plan must not read as approved, and provenance must be visible.
* An unreadable plan must not claim zero steps.
* `plans.css` light-theme tokens. The stylesheet used `color: inherit` and `opacity`, so contrast
  depended on an ancestor's colour and a blend; grepping for `rgba(255,255,255` could not catch
  that. This test computes WCAG 2.1 relative-luminance contrast for every text token a rule in
  `plans.css` names against the surface that rule sits on, in BOTH themes, and structurally forbids
  `color: inherit` and `opacity` on text.

SCOPE: this file proves the `plans.css` rules only. It cannot see the page chrome — DeskPage's
hardcoded inline colours, the active-nav accent, and the "showing last-good data" bar — which is
exactly why it once certified a page whose light-theme chrome failed. The rendered chrome is
proven in a real browser by `apps/command-center-v3/e2e/plans-theme.spec.ts`, which composites
computed colours and measures the ratios. Do not add a source-string assertion here that claims to
prove colour; add it to that spec.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "apps/command-center-v3/src/styles/plans.css"
TOKENS = ROOT / "apps/command-center-v3/src/styles/tokens.css"
MODEL = ROOT / "apps/command-center-v3/src/lib/plansModel.ts"
PAGE = ROOT / "apps/command-center-v3/src/pages/PlansPage.tsx"

WCAG_MIN = 4.5
TEXT_TOKEN = re.compile(r"var\(--text-[0-3]\)$")

# Every selector that renders text. Each must name an explicit text token: inherited text colour is
# exactly the defect that made the light theme unreadable.
TEXT_SELECTORS = (
    ".pl-card",
    ".pl-card-title",
    ".pl-card-line",
    ".pl-card-links",
    ".pl-empty",
    ".pl-detail",
    ".pl-status",
    ".pl-meta",
    ".pl-steps-summary",
    ".pl-provenance",
    ".pl-quote",
    ".pl-step",
    ".pl-step.done",
    ".pl-links",
    ".pl-links code",
    ".pl-body",
    ".pl-panel",
    ".pl-back",
)


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _rules(css: str) -> dict[str, list[dict[str, str]]]:
    """Map every selector to its declaration blocks. The @media wrapper's inner rule is found."""
    out: dict[str, list[dict[str, str]]] = {}
    for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css)):
        decls: dict[str, str] = {}
        for chunk in body.split(";"):
            if ":" not in chunk:
                continue
            prop, value = chunk.split(":", 1)
            decls[prop.strip().lower()] = " ".join(value.split())
        for selector in selector_group.split(","):
            out.setdefault(" ".join(selector.split()), []).append(decls)
    return out


def _decls(rules: dict[str, list[dict[str, str]]], selector: str) -> dict[str, str]:
    blocks = rules.get(selector)
    assert blocks, f"{selector} has no rule in plans.css"
    merged: dict[str, str] = {}
    for block in blocks:
        merged.update(block)
    return merged


def _token_block(css: str, selector_pattern: str) -> dict[str, str]:
    match = re.search(selector_pattern + r"\s*\{([^}]*)\}", css, flags=re.S)
    assert match, f"token block {selector_pattern!r} not found in tokens.css"
    return {
        prop: value.strip()
        for prop, value in re.findall(r"(--[A-Za-z0-9-]+)\s*:\s*([^;]+);", match.group(1))
    }


def _theme_tokens() -> dict[str, dict[str, str]]:
    """The two themes named by the review: the dark root block and the explicit light block."""
    raw = TOKENS.read_text(encoding="utf-8")
    dark = _token_block(raw, r':root,\s*\[data-theme="dark"\]')
    light = _token_block(raw, r'\[data-theme="light"\]')
    return {"dark": dark, "light": light}


def _rgb(value: str) -> tuple[float, float, float]:
    match = re.fullmatch(r"#([0-9a-fA-F]{6})", value.strip())
    assert match, f"cannot parse colour {value!r} as a 6-digit hex token"
    digits = match.group(1)
    return tuple(int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value] -- tuple of three floats from a generator; the width is fixed by the 3-step range


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_linear(channel) for channel in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    """WCAG 2.1 relative-luminance contrast ratio."""
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _backgrounds(selector: str) -> tuple[str, ...]:
    """The surfaces a rule's text can sit on in plans.css.

    Card text sits on the card fill (`--bg-2`) and its active/hover fill (`--bg-3`). Everything else
    sits on the page surface (`--bg-0`) or the detail panel fill (`--bg-1`; on a phone the detail
    sheet body is `--bg-0`). Checking both is stricter than picking one.
    """
    if selector == ".pl-card" or selector.startswith(".pl-card-"):
        return ("bg-2", "bg-3")
    return ("bg-0", "bg-1")


def test_stylesheet_uses_no_colour_literals():
    css = _strip_comments(CSS.read_text(encoding="utf-8"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "plans.css hard-codes a hex colour; use a token"
    assert not re.search(r"\brgba?\(", css), "plans.css hard-codes an rgb colour; use a token"


def test_stylesheet_has_no_inherited_text_colour():
    css = _strip_comments(CSS.read_text(encoding="utf-8"))
    assert not re.search(r"color\s*:\s*inherit", css, re.I), (
        "plans.css uses `color: inherit`: contrast then depends on an ancestor colour and can fail "
        "in the light theme"
    )


def test_stylesheet_has_no_opacity_on_text():
    css = _strip_comments(CSS.read_text(encoding="utf-8"))
    assert not re.search(r"opacity\s*:", css, re.I), (
        "plans.css uses `opacity` for de-emphasis: the blended text contrast is not a token and can "
        "fail in the light theme; name a darker/lighter text token instead"
    )


def test_every_text_rule_names_an_explicit_token_colour():
    rules = _rules(CSS.read_text(encoding="utf-8"))
    for selector in TEXT_SELECTORS:
        colour = _decls(rules, selector).get("color", "")
        assert TEXT_TOKEN.match(colour), (
            f"{selector} must name an explicit text token (got {colour!r}); inherited or blended "
            f"text is the light-theme defect"
        )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_text_rules_meet_wcag_aa_on_their_surfaces(theme: str):
    tokens = _theme_tokens()[theme]
    rules = _rules(CSS.read_text(encoding="utf-8"))
    checked = 0
    for selector, blocks in rules.items():
        for decls in blocks:
            declared = decls.get("color")
            if not declared:
                continue
            match = TEXT_TOKEN.match(declared)
            assert match, f"{selector} color {declared!r} is not an explicit text token"
            token_name = re.search(r"--text-[0-3]", declared)
            assert token_name, f"{selector} color {declared!r} names no text token"
            fg = _rgb(tokens[token_name.group(0)])
            for bg_name in _backgrounds(selector):
                bg = _rgb(tokens[f"--{bg_name}"])
                ratio = _contrast(fg, bg)
                assert ratio >= WCAG_MIN, (
                    f"{theme}: {selector} {declared} on --{bg_name} is {ratio:.2f}:1 "
                    f"(min {WCAG_MIN}:1)"
                )
                checked += 1
    assert checked > 0, "no text-bearing rule was checked"


def test_light_theme_rules_use_design_tokens():
    rules = _rules(CSS.read_text(encoding="utf-8"))
    assert "var(--border-color)" in _decls(rules, ".pl-card")["border"]
    assert _decls(rules, ".pl-card")["background"].startswith("var(--")
    assert "var(--border-color)" in _decls(rules, ".pl-quote")["border-left"]
    assert "var(--border-color)" in _decls(rules, ".pl-panel")["border-left"]
    for selector in (".pl-card:active", ".pl-card:hover"):
        assert _decls(rules, selector)["background"].startswith("var(--")


def test_cards_have_no_fixed_width():
    card = _decls(_rules(CSS.read_text(encoding="utf-8")), ".pl-card")
    assert card.get("width") == "100%", "the card must fill its column, not carry a fixed width"


@pytest.mark.parametrize("selector", [".pl-card-title", ".pl-card-line", ".pl-links code"])
def test_long_titles_and_branches_cannot_overflow_390px(selector: str):
    rules = _rules(CSS.read_text(encoding="utf-8"))
    decls = _decls(rules, selector)
    wraps = decls.get("overflow-wrap") in {"anywhere", "break-word"} or decls.get("word-break") == "break-word"
    assert wraps, f"{selector} does not wrap long unbroken text"
    assert decls.get("min-width") == "0", f"{selector} cannot shrink inside its flex row"


def test_every_css_variable_is_defined_in_the_token_source():
    used = set(re.findall(r"var\(\s*(--[A-Za-z0-9-]+)", CSS.read_text(encoding="utf-8")))
    defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", TOKENS.read_text(encoding="utf-8")))
    assert used <= defined, f"plans.css uses undefined tokens: {sorted(used - defined)}"


def test_plans_page_wires_the_unknown_and_detail_gap_states():
    page = PAGE.read_text(encoding="utf-8")
    # The Decisions line comes from the model, never an unconditional empty-success sentence.
    assert "waitingDecision(" in page
    assert "decisionGap={decisionGap}" in page
    assert "Nothing approved and unclaimed right now." not in page
    # A listing that cannot be parsed, a store it could not read, and a detail {ok:false} all feed
    # the page's gap — and the gap suppresses the empty-registry sentence.
    assert "plansGap(index.data)" in page
    assert "detailGap(one.data, selectedId)" in page
    assert re.search(r"rows\.length === 0\s*&&\s*!gap", page), (
        "the empty-registry message is not gated on !gap, so a store gap could paint "
        "\"No plans registered yet.\""
    )


def test_plans_page_wires_provenance_stalled_and_freshness():
    page = PAGE.read_text(encoding="utf-8")
    assert "provenanceLabel(plan)" in page, "the detail does not render the provenance line"
    assert "stalledLine(plan)" in page, "the detail does not render the stalled clock"
    # A known empty read uses the server receipt instead of falling into a freshness gap.
    assert "index.data?.as_of" in page, "the page does not use the listing as_of"
    assert re.search(r"listKnown\s*&&\s*rows\.length === 0", page), (
        "as_of must only stand in for a known empty listing; a failed read keeps asOf undefined"
    )
    # An approval date is printed only for a plan the registry actually approved: a registration
    # carries no approved_at, and even an explicit one must not be shown as an approval.
    assert "plan.status === 'approved' && plan.approved_at" in page, (
        "the detail prints an approval date for a plan whose status is not approved"
    )


def test_plans_page_purpose_describes_registration_not_approval():
    page = PAGE.read_text(encoding="utf-8")
    assert "Every registered plan" in page
    assert "Every approved plan" not in page
    assert "who registered it, who picked it up, what is left" in page
    assert "who approved it" not in page


def test_model_defines_the_gap_and_waiting_helpers():
    src = MODEL.read_text(encoding="utf-8")
    for name in ("plansGap", "detailGap", "waitingDecision", "provenanceLabel", "stalledLine"):
        assert re.search(rf"export function {name}\(", src), f"{name} is not exported"


def test_step_summary_validates_before_showing_progress():
    src = MODEL.read_text(encoding="utf-8")
    match = re.search(r"export function stepSummary\(.*?\n\}", src, re.S)
    assert match, "stepSummary not found in plansModel.ts"
    body = match.group(0)
    assert "Number.isInteger" in src, "step counts are not validated as integers"
    assert "stepCount(" in body, "stepSummary does not validate its counts"
    assert "steps unknown" in body, "an invalid count is not reported as unknown"
    assert not re.search(r"Number\(plan\.steps_(done|left)\s*\|\|\s*0\)", body), (
        "a missing count is defaulted to zero and added into a fabricated total"
    )
