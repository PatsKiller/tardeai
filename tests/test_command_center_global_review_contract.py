from pathlib import Path


APP = Path("apps/command-center-v3/src/App.tsx").read_text()
CSS = Path("apps/command-center-v3/src/interaction.css").read_text()
MAIN = Path("apps/command-center-v3/src/main.tsx").read_text()
E2E = Path("apps/command-center-v3/e2e/global-review-modal.spec.ts").read_text()


def test_app_consumes_url_addressable_review_contract():
    for token in (
        "command-center-global-review-v1",
        "searchParams.get('review') === '1'",
        "searchParams.get('modal') === 'review'",
        "set('symbol', symbol)",
        "set('review', '1')",
        "set('modal', 'review')",
        "data-command-center-modal=\"review\"",
        "aria-modal=\"true\"",
        "URL-addressable decision, provenance and evidence review",
    ):
        assert token in APP


def test_watch_cards_are_keyboard_accessible_review_surfaces():
    for token in (
        "data.reviewSurface = 'watchlist-card'",
        "card.tabIndex = 0",
        "card.setAttribute('role', 'button')",
        "Open ${symbol} operator review",
        "event.key !== 'Enter' && event.key !== ' '",
        "onClickCapture={handleClickCapture}",
        "onKeyDownCapture={handleKeyCapture}",
    ):
        assert token in APP


def test_modal_layer_is_loaded_and_visually_distinct():
    assert "import './interaction.css'" in MAIN
    for token in (
        "[data-review-surface='watchlist-card']",
        "OPEN REVIEW",
        "div:has(> .cc-drawer)",
        "backdrop-filter: blur(5px)",
        "height: min(92vh, 1040px)",
        ":focus-visible",
    ):
        assert token in CSS


def test_browser_contract_covers_deep_links_clicks_and_escape():
    for token in (
        "/v3/watch?symbol=FATN&review=1&tab=watchlist",
        "/v3/watch?symbol=SWBI&review=1&tab=sectors",
        "FATN operator review",
        "SWBI operator review",
        "page.keyboard.press('Escape')",
        "modal=review",
    ):
        assert token in E2E
