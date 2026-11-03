"""Plans page UI repairs (2026-11-03): light-theme tokens, 390 px wrapping, honest step counts.

The CC-v3 app has no tsx test harness, so this test reads the stylesheet and the view-model source
directly. It guards two defects: white-only borders/fills that vanish in the light theme, and long
titles or `wt/...` branches that push the card past a 390 px phone. It also pins the model's refusal
to derive progress from a lone or invalid step count.
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


def test_stylesheet_has_no_white_only_rgba_literals():
    css = CSS.read_text(encoding="utf-8")
    assert not re.search(r"rgba\(\s*255\s*,\s*255\s*,\s*255", css, re.I), (
        "plans.css still hard-codes white; borders and fills vanish in the light theme"
    )


def test_light_theme_rules_use_design_tokens():
    rules = _rules(CSS.read_text(encoding="utf-8"))
    assert "var(--border-color)" in _decls(rules, ".pl-card")["border"]
    assert _decls(rules, ".pl-card")["background"].startswith("var(--")
    assert "var(--border-color)" in _decls(rules, ".pl-quote")["border-left"]
    assert "var(--border-color)" in _decls(rules, ".pl-panel")["border-left"]
    for selector in (".pl-card:active", ".pl-card:hover"):
        assert _decls(rules, selector)["background"].startswith("var(--")


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
    # A listing that cannot be parsed and a detail {ok:false} both feed the page's gap.
    assert "plansGap(index.data)" in page
    assert "detailGap(one.data, selectedId)" in page


def test_model_defines_the_gap_and_waiting_helpers():
    src = MODEL.read_text(encoding="utf-8")
    for name in ("plansGap", "detailGap", "waitingDecision"):
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
