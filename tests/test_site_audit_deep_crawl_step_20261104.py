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
    def __init__(self, href, text):
        self._href, self._text = href, text

    def get_attribute(self, name):
        return self._href if name == "href" else None

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

            def click(self, timeout=None):
                page.clicks.append(selector)

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
