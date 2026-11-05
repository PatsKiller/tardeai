"""SPEC §6 deep-crawl step — the browser-independent decisions, driven against a fake page.

No browser, no network: the point is that the crawl's choices (what opens, what is refused, how far a link goes, how a
target is judged) are asserted behaviourally, not grepped.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from site_audit.deep_crawl import (  # noqa: E402
    BLANK, DEAD, ERROR, NOT_PERMITTED, OK, capture_page, classify_target, crawl_plan,
    is_in_page_link, link_is_crawlable,
)

PAGE_URL = "http://127.0.0.1:7777/v3/trading"

OPENERS = [
    {"label": "Open ADBE", "role": "button", "selector": "#open-adbe"},
    {"label": "Approve", "role": "button", "selector": "#approve"},
    {"label": "Open MSFT", "role": "button", "selector": "#open-msft"},
    {"label": "", "role": "button", "selector": "#unlabelled"},
]


class Node:
    def __init__(self, href, text, aria_label=None):
        self._href, self._text, self._aria = href, text, aria_label

    def get_attribute(self, name):
        if name == "href":
            return self._href
        if name == "aria-label":
            return self._aria
        return None

    def inner_text(self):
        return self._text


class FakePage:
    def __init__(self, anchors=None, targets=None, body="page body"):
        self.anchors, self.targets, self.body = anchors or [], targets or {}, body
        self.clicks, self.visited, self.escapes, self.gotos = [], [], 0, []

    def locator(self, selector):
        page = self

        class _L:
            @property
            def first(self):
                return self

            # The guard runs on the live element (codex R2): these fakes expose the same surface.
            def get_attribute(self, name):
                if name == "role":
                    return "button"
                if name == "aria-label":
                    return selector.lstrip("#").replace("-", " ").title() if selector != "#unlabelled" else None
                return None

            def inner_text(self):
                return "" if selector == "#unlabelled" else selector.lstrip("#").replace("-", " ").title()

            def evaluate(self, _js):
                return "button"

            def click(self, timeout=None):
                page.clicks.append(selector)

            def is_visible(self, timeout=None):
                # A safe click opens a dialog in this fake; a refused one never runs.
                return True

        return _L()

    def wait_for_timeout(self, _ms):
        return None

    class keyboard:
        @staticmethod
        def press(_key):
            return None

    def query_selector_all(self, selector):
        return list(self.anchors) if selector.startswith("a") else []

    def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append(url)
        status, text = self.targets.get(url, (200, "ok"))
        self.body = text

        class _Resp:
            def __init__(self, s):
                self.status = s

        return _Resp(status)

    def inner_text(self, _sel):
        return self.body


def test_only_sampled_openers_are_considered_and_actions_are_refused():
    allowed, refused = crawl_plan(OPENERS, [0, 1, 2, 3])
    assert [a["selector"] for a in allowed] == ["#open-adbe", "#open-msft"]
    assert {r["selector"] for r in refused} == {"#approve", "#unlabelled"}
    assert all("§6" in r["reason"] for r in refused)


def test_the_budget_limits_what_is_opened():
    allowed, _ = crawl_plan(OPENERS, [0])
    assert [a["selector"] for a in allowed] == ["#open-adbe"]


def test_links_are_followed_one_level_inside_the_app_only():
    assert is_in_page_link("/v3/watch?symbol=ADBE", PAGE_URL) is True
    assert is_in_page_link("http://127.0.0.1:7777/v3/watch", PAGE_URL) is True
    assert is_in_page_link("https://finviz.com/quote.ashx?t=ADBE", PAGE_URL) is False
    assert is_in_page_link("mailto:x@example.com", PAGE_URL) is False
    assert is_in_page_link("#section", PAGE_URL) is False
    assert link_is_crawlable("Open ADBE", "/v3/watch", PAGE_URL) is True
    assert link_is_crawlable("Approve", "/v3/approvals", PAGE_URL) is False


def test_targets_are_judged_by_what_came_back():
    assert classify_target(200, "ADBE detail") == OK
    assert classify_target(404, "not here") == DEAD
    assert classify_target(500, "boom") == DEAD
    assert classify_target(403, "forbidden — not permitted") == NOT_PERMITTED
    assert classify_target(200, "   ") == BLANK
    assert classify_target(None, "x") == ERROR


def test_capture_page_opens_only_allowed_details_and_records_the_rest():
    anchors = [Node("/v3/watch?symbol=ADBE", "Open ADBE"), Node("https://finviz.com/x", "Finviz"),
               Node("/v3/approvals", "Approve")]
    targets = {"/v3/watch?symbol=ADBE": (200, "ADBE detail"), "http://127.0.0.1:7777/v3/watch?symbol=ADBE": (200, "ADBE detail")}
    page = FakePage(anchors=anchors, targets=targets)
    out = capture_page(page, route="/trading", page_url=PAGE_URL, indices=[0, 1, 2, 3], out_dir=None, openers=OPENERS)

    assert page.clicks == ["#open-adbe", "#open-msft"], "an action or an unsampled opener was clicked"
    assert len(out["details"]) == 2 and all(d["opened"] for d in out["details"])
    assert {r["selector"] for r in out["refused"]} == {"#approve", "#unlabelled"}
    hrefs = [l["href"] for l in out["links"]]
    assert "/v3/watch?symbol=ADBE" in hrefs
    assert "https://finviz.com/x" not in hrefs, "an external link was followed"
    assert "/v3/approvals" not in hrefs, "an Approve link was followed"


def test_a_blank_or_forbidden_target_is_recorded_as_such():
    anchors = [Node("/v3/blank", "Open blank"), Node("/v3/forbidden", "View locked")]
    targets = {"http://127.0.0.1:7777/v3/blank": (200, "  "), "http://127.0.0.1:7777/v3/forbidden": (403, "not permitted")}
    page = FakePage(anchors=anchors, targets=targets)
    out = capture_page(page, route="/x", page_url=PAGE_URL, indices=[], out_dir=None, openers=[])
    outcomes = {l["href"]: l["outcome"] for l in out["links"]}
    assert outcomes["/v3/blank"] == BLANK
    assert outcomes["/v3/forbidden"] == NOT_PERMITTED


def test_an_action_in_the_accessible_name_or_past_the_truncation_is_not_followed():
    """cx-openai-4 R1 (residual) on #2648: the link phase judged the visible text only, truncated to 120 chars."""
    long_prefix = "Read the settlement note for the pending leg " * 4
    assert len(long_prefix) > 120 and "approve" not in long_prefix.lower()
    anchors = [
        Node("/v3/approve-icon", "", aria_label="Approve the request"),
        Node("/v3/long", long_prefix + "approve"),
        Node("/v3/watch?symbol=ADBE", "Open ADBE"),
    ]
    page = FakePage(anchors=anchors, targets={})
    out = capture_page(page, route="/x", page_url=PAGE_URL, indices=[], out_dir=None, openers=[])
    hrefs = [l["href"] for l in out["links"]]
    assert "/v3/approve-icon" not in hrefs, "an icon link whose accessible name was 'Approve' was followed"
    assert "/v3/long" not in hrefs, "an action word past the 120-character truncation was followed"
    assert "/v3/watch?symbol=ADBE" in hrefs, "a safe link stopped being followed"


class _Child:
    """A button inside a discovered container. role=None means the element carries no role attribute."""

    def __init__(self, label, role=None):
        self._label, self._role, self.clicks = label, role, 0

    def get_attribute(self, name):
        if name == "role":
            return self._role
        if name == "aria-label":
            return self._label
        return None

    def inner_text(self):
        return ""

    def evaluate(self, _js):
        return "button"

    def click(self, timeout=None):
        self.clicks += 1


class _Children:
    def __init__(self, kids):
        self.kids = kids

    def count(self):
        return len(self.kids)

    def nth(self, i):
        return self.kids[i]


class _Row:
    """The real Options desk shape: a div role=row carrying an onClick, with a labelled button inside."""

    def __init__(self, kids, role="row"):
        self._kids, self._role, self.clicks = kids, role, 0

    def get_attribute(self, name):
        return self._role if name == "role" else None

    def inner_text(self):
        return ""

    def evaluate(self, _js):
        return "div"

    def is_visible(self, timeout=None):
        return True

    def locator(self, _sel):
        return _Children(self._kids)

    def click(self, timeout=None):
        self.clicks += 1


class RowPage:
    def __init__(self, row):
        self.row = row

    def locator(self, _sel):
        row = self.row

        class _L:
            @property
            def first(self):
                return row

        return _L()

    def wait_for_timeout(self, _ms):
        return None

    class keyboard:
        @staticmethod
        def press(_key):
            return None

    def query_selector_all(self, _sel):
        return []


def test_a_row_opens_its_own_detail_button_instead_of_being_refused():
    """cx-openai-4 R9 on #2648: the Options desk row is a container; its detail button is the safe target."""
    button = _Child("Show NVDA credit put details")
    row = _Row([_Child("Remove"), button])
    page = RowPage(row)
    openers = [{"label": "NVDA", "role": "row", "selector": "[data-testid$='-row'] >> nth=0"}]

    out = capture_page(page, route="/options", page_url=PAGE_URL, indices=[0], out_dir=None, openers=openers)

    assert row.clicks == 0, "the row container itself was pressed"
    assert button.clicks == 1, "the row's own detail button was not pressed"
    assert out["details"][0]["opened"] is True
    assert "Show NVDA credit put details" in (out["details"][0]["pressed"] or "")
    assert out["refused"] == []


def test_a_row_whose_children_are_not_openers_is_still_refused():
    row = _Row([_Child("Remove"), _Child("Pin this"), _Child("", role=None)])
    page = RowPage(row)
    openers = [{"label": "NVDA", "role": "row", "selector": "[data-testid$='-row'] >> nth=0"}]

    out = capture_page(page, route="/options", page_url=PAGE_URL, indices=[0], out_dir=None, openers=openers)

    assert row.clicks == 0 and all(k.clicks == 0 for k in row._kids), "a non-opener child was pressed"
    assert out["details"][0]["opened"] is False
    assert out["refused"] and "will not press" in out["refused"][0]["reason"]


class _Detail:
    """The opened detail: visible, and saying something unique that must survive the close."""

    def __init__(self, text, links=None):
        self.text = text
        self.links = links or []

    def is_visible(self, timeout=None):
        return True

    def inner_text(self):
        return self.text

    def query_selector_all(self, sel):
        return self.links if sel.startswith("a") else []


class _Opener:
    def __init__(self, label):
        self.label = label
        self.clicks = 0

    def get_attribute(self, name):
        return self.label if name == "aria-label" else None

    def inner_text(self):
        return ""

    def evaluate(self, _js):
        return "button"

    def click(self, timeout=None):
        self.clicks += 1


class DetailPage:
    """One safe opener; the detail selectors resolve to a visible node carrying a unique marker."""

    def __init__(self, opener_label, detail_text, detail_links=None):
        self.opener = _Opener(opener_label)
        self.detail = _Detail(detail_text, links=detail_links)
        self.screenshots, self.gotos = [], []

    def locator(self, sel):
        node = self.detail if (sel.startswith("[role='dialog']") or sel.startswith("[data-testid$=")) else self.opener

        class _L:
            @property
            def first(self):
                return node

        return _L()

    def wait_for_timeout(self, _ms):
        return None

    class keyboard:
        @staticmethod
        def press(_key):
            return None

    def query_selector_all(self, _sel):
        return []

    def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append(url)

        class _Resp:
            status = 200
        return _Resp()

    def inner_text(self, _sel):
        return "destination body"

    def screenshot(self, path=None, full_page=False):
        self.screenshots.append(path)


def test_the_opened_detail_is_persisted_before_it_is_closed(tmp_path):
    """cx-openai-4 R3 on #2648: `opened: true` was recorded, and the detail's own text was saved nowhere."""
    import hashlib

    marker = "NVDA credit put — theta 41.2 — unique marker 7f3c9e"
    page = DetailPage("Open NVDA", marker)
    openers = [{"label": "Open NVDA", "role": "button", "selector": "#open-nvda"}]

    out = capture_page(page, route="/options", page_url=PAGE_URL, indices=[0], out_dir=tmp_path,
                       openers=openers, prefix="desktop-")

    rec = out["details"][0]
    assert rec["opened"] is True
    assert page.opener.clicks == 1
    evidence = rec["fields"][0]
    assert evidence["sha256"] == hashlib.sha256(marker.encode("utf-8")).hexdigest()
    assert evidence["chars"] == len(marker)
    saved = tmp_path / "desktop-detail-0.txt"
    assert saved.read_text() == marker, "the opened detail's text was not written before Escape"
    assert page.screenshots == [str(tmp_path / "desktop-detail-0.png")]


# ── cx-cloud CX2 on #2648: the captured text is EVALUATED, not just saved ────────────────────────────────────────
def _card_text(*, cio=True):
    lines = ["NVDA", "Price 248.85", "RSI 54.2", "MACD 1.1", "SMA 20 240.0", "SMA 50 230.0", "SMA 200 210.0",
             "Support 1 240.0", "Support 2 230.0", "Resistance 1 252.0", "Resistance 2 260.0", "Trend up"]
    if cio:
        lines += ["CIO stance HOLD", "As of 2026-11-04"]
    return "\n".join(lines)


def test_a_detail_missing_its_cio_thesis_no_longer_produces_a_complete_record():
    """The finding's last clause: the same successful record used to be written with or without the evidence."""
    openers = [{"label": "Show analysis for NVDA", "role": "button", "selector": "#open-nvda"}]
    good = capture_page(DetailPage("Show analysis for NVDA", _card_text(cio=True)),
                        route="/trading", page_url=PAGE_URL, indices=[0], out_dir=None, openers=openers)
    bad = capture_page(DetailPage("Show analysis for NVDA", _card_text(cio=False)),
                       route="/trading", page_url=PAGE_URL, indices=[0], out_dir=None, openers=openers)

    good_rec, bad_rec = good["details"][0], bad["details"][0]
    assert good_rec["severity"] is None, good_rec
    assert bad_rec["severity"] == "P1", bad_rec
    assessment = bad_rec["fields"][0]["completeness"]
    assert assessment["evaluated"] is True
    assert any(g["field"] == "cio_stance_or_thesis" for g in assessment["gaps"]), assessment


def test_a_blank_detail_is_not_a_complete_record():
    page = DetailPage("Show details", "")
    out = capture_page(page, route="/x", page_url=PAGE_URL, indices=[0], out_dir=None,
                       openers=[{"label": "Show details", "role": "button", "selector": "#open"}])
    assert out["details"][0]["opened"] is True
    assert out["details"][0]["severity"] == "P1"


# ── cx-cloud CX7 on #2648: the inline analysis panel is evidence only for the selected row ──────────────────────
class _PanelPage:
    """The Trade AI panel: always mounted, visible, and showing whatever text it was given."""

    def __init__(self, text):
        self.panel = _Detail(text)

    def locator(self, sel):
        if sel in ("[data-testid='ta-analysis']", "[aria-label='Catalyst analysis']"):
            node = self.panel
        else:
            raise LookupError(sel)  # no dialog/sheet on this page

        class _L:
            @property
            def first(self):
                return node

        return _L()


def test_the_inline_panel_is_evidence_only_when_it_names_the_selected_row():
    import site_audit.deep_crawl as dc

    placeholder = _PanelPage("Click a symbol or catalyst to see the AI analysis.")
    assert dc._detail_is_open(placeholder, "NVDA") is False, "the always-mounted placeholder read as an opened detail"
    assert dc._detail_is_open(placeholder, None) is False

    selected = _PanelPage("NVDA\nHOLD\ncatalyst verified")
    assert dc._detail_is_open(selected, "NVDA") is True
    assert dc._detail_is_open(selected, "MSFT") is False, "a stale panel for another row read as this click's evidence"
    assert dc._detail_is_open(selected, None) is False


def test_the_inline_panel_is_recorded_with_the_symbol_it_represents():
    import site_audit.deep_crawl as dc

    page = _PanelPage("NVDA\nHOLD\ncatalyst verified")
    record = dc._capture_detail(page, out_dir=None, expected_symbol="NVDA")
    assert record is not None
    assert record["evidence_kind"] == "inline"
    assert record["represents_selected"] == "NVDA"


# ── cx-cloud CX2 (links clause) + CX8 (readiness) ───────────────────────────────────────────────────────────────
class _AnchorNode:
    def __init__(self, href, label):
        self._href, self._label = href, label

    def get_attribute(self, name):
        if name == "href":
            return self._href
        if name == "aria-label":
            return self._label
        return None

    def inner_text(self):
        return ""


def test_a_link_exposed_only_inside_a_detail_is_still_followed():
    page = DetailPage("Show details for NVDA", "NVDA detail",
                      detail_links=[_AnchorNode("/v3/filings/NVDA", "Open the filing")])
    out = capture_page(page, route="/x", page_url=PAGE_URL, indices=[0], out_dir=None,
                       openers=[{"label": "Show details for NVDA", "role": "button", "selector": "#open"}])
    assert any(l["href"] == "/v3/filings/NVDA" for l in out["links"]), out["links"]


class _SlowLinkPage:
    """A destination whose body is empty for the first two reads; the readiness wait must not judge it early."""

    def __init__(self):
        self.reads = self.waits = 0

    def query_selector_all(self, sel):
        return [_AnchorNode("/v3/slow", "Show details")] if sel.startswith("a") else []

    def goto(self, url, wait_until=None, timeout=None):
        class _Resp:
            status = 200
        return _Resp()

    def inner_text(self, _sel):
        self.reads += 1
        return "" if self.reads < 3 else "destination content"

    def wait_for_timeout(self, _ms):
        self.waits += 1


def test_a_slow_destination_is_waited_for_before_being_classified():
    page = _SlowLinkPage()
    records = __import__("site_audit.deep_crawl", fromlist=["_follow_links"])._follow_links(
        page, page_url=PAGE_URL, max_links=5)
    assert records and records[0].outcome == OK, records
    assert page.waits >= 1, "the destination was judged before it rendered anything"


# ── cx-cloud CX3 on #2648: native detail buttons are discovered, and still guarded at click time ────────────────
class _NativeButton:
    def __init__(self, label):
        self._label = label

    def get_attribute(self, name):
        if name == "role":
            return None                 # a native <button> carries no role attribute
        if name == "aria-label":
            return self._label
        return None

    def inner_text(self):
        return ""

    def evaluate(self, _js):
        return "button"


class _DiscoveryPage:
    def __init__(self, nodes):
        self.nodes = nodes

    def query_selector_all(self, _sel):
        return self.nodes


def test_native_detail_buttons_are_discovered_by_their_tag():
    import site_audit.deep_crawl as dc

    assert "button[aria-label^='Show ']" in dc.OPENER_SELECTOR
    assert "button[aria-label^='Open ']" in dc.OPENER_SELECTOR
    assert "text-matches" in dc.OPENER_SELECTOR, "a native button with visible text and no aria-label was not discoverable"

    got = dc._discover_openers(_DiscoveryPage([_NativeButton("Show analysis for NVDA"),
                                               _NativeButton("Open AI analysis")]))
    assert [g["role"] for g in got] == ["button", "button"], got
    assert [g["label"] for g in got] == ["Show analysis for NVDA", "Open AI analysis"]
