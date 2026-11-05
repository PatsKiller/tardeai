"""The lane's two safety guarantees, proven by EXECUTED probes (codex R1/R2, 2026-11-04).

The whole-head review found both guarantees false in the code while 25 tests passed: an action button could be
activated, and a capture could land inside the public repository. A test that greps for a denylist or a root check
does not prove either. These probes drive the real functions with objects that record what happened:

  R2 — the guard is re-run on the element that would actually be clicked; a "safe" discovery whose selector
       resolves to an Approve button is refused and `click` is never called.
  F1 — that same click guard is fail-closed: an action name is refused whatever the live role resolves to
       (`<a>`, `<div>`, `role="none"`), and an absent/unknown role is never pressed even with a safe name.
       A genuinely safe link is still clicked and a safe detail button still opens.
  R1 — a per-page directory that already exists as a symlink into the checkout is refused before a byte is written;
       `--out` pointing into the checkout is refused by the same root check.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from site_audit import capture_root as cr  # noqa: E402
from site_audit import deep_crawl as dc  # noqa: E402
from site_audit.action_denylist import is_forbidden_click, safe_to_activate  # noqa: E402


class FakeTarget:
    def __init__(self, label, role="", tag="button"):
        self.label, self.role, self.tag, self.clicks = label, role, tag, 0

    def get_attribute(self, name):
        return self.role if name == "role" else (self.label if name == "aria-label" else None)

    def inner_text(self):
        return self.label

    def evaluate(self, _js):
        return self.tag

    def click(self, **kw):
        self.clicks += 1


class FakeLocator:
    def __init__(self, target):
        self.first = target


class FakePage:
    def __init__(self, target):
        self.target = target
        self.keyboard = self

    def locator(self, sel):
        return FakeLocator(self.target)

    def wait_for_timeout(self, ms):
        pass

    def press(self, key):
        pass

    def query_selector_all(self, sel):
        return []


def test_R2_the_live_target_is_guarded_not_the_discovery_metadata():
    target = FakeTarget("Approve")
    page = FakePage(target)
    # Discovery claims a harmless label; the selector actually resolves to the Approve button.
    plan = [{"label": "Quarterly revenue", "role": "button", "selector": "[data-open=0]"}]
    out = dc.capture_page(page, route="/reports", page_url="http://x/v3/reports", indices=[0],
                          out_dir=None, openers=plan, max_links=0)

    assert target.clicks == 0, "an action button was clicked because the plan-time label was trusted"
    assert out["details"][0]["opened"] is False
    assert "refused at click time" in (out["details"][0]["skipped_reason"] or "")
    assert any("action label" in r["reason"] for r in out["refused"])


def test_R2_a_safe_detail_button_is_still_opened_when_no_detail_appears_it_says_so():
    target = FakeTarget("Show details", role="button")
    page = FakePage(target)
    plan = [{"label": "Show details", "role": "button", "selector": "[data-open=0]"}]
    out = dc.capture_page(page, route="/reports", page_url="http://x/v3/reports", indices=[0],
                          out_dir=None, openers=plan, max_links=0)
    assert target.clicks == 1
    # The fake page opens no dialog: the record must not claim the detail opened.
    assert out["details"][0]["opened"] is False
    assert "no detail appeared" in (out["details"][0]["skipped_reason"] or "")


@pytest.mark.parametrize("tag,role", [
    ("a", ""),            # resolves as a link
    ("div", ""),          # no role at all
    ("div", "none"),      # declared non-actionable role
    ("button", ""),       # the semantic button
])
def test_F1_an_action_name_is_refused_whatever_the_live_role(tag, role):
    """Whole-head F1: only a semantic button used to be refused; `<a>`/`<div>`/role=none were clicked."""
    target = FakeTarget("Approve", role=role, tag=tag)
    page = FakePage(target)
    plan = [{"label": "Open revenue", "role": "button", "selector": "[data-open=0]"}]
    out = dc.capture_page(page, route="/approvals", page_url="http://x/v3/approvals", indices=[0],
                          out_dir=None, openers=plan, max_links=0)

    assert target.clicks == 0, f"an action was clicked on a <{tag} role={role!r}> target"
    assert out["details"][0]["opened"] is False
    assert "refused at click time" in (out["details"][0]["skipped_reason"] or "")
    assert any("action label" in r["reason"] for r in out["refused"])


@pytest.mark.parametrize("tag,role", [("div", ""), ("div", "none"), ("span", "presentation")])
def test_F1_an_unknown_or_absent_role_is_never_pressed_even_with_a_safe_name(tag, role):
    """The fail-closed default: if the crawler cannot tell what the node is, it does not press it."""
    target = FakeTarget("Open revenue", role=role, tag=tag)
    page = FakePage(target)
    plan = [{"label": "Open revenue", "role": "button", "selector": "[data-open=0]"}]
    out = dc.capture_page(page, route="/reports", page_url="http://x/v3/reports", indices=[0],
                          out_dir=None, openers=plan, max_links=0)

    assert target.clicks == 0, f"an unknown role ({tag} role={role!r}) was pressed"
    assert "refused at click time" in (out["details"][0]["skipped_reason"] or "")


def test_F1_a_safe_link_is_still_clicked_and_a_safe_button_still_opens():
    """The fix must not turn the crawl off: a safe link (role=link) and a safe detail button still run."""
    link = FakeTarget("Open ADBE", role="", tag="a")
    out = dc.capture_page(FakePage(link), route="/reports", page_url="http://x/v3/reports", indices=[0],
                          out_dir=None,
                          openers=[{"label": "Open ADBE", "role": "button", "selector": "a[href]"}],
                          max_links=0)
    assert link.clicks == 1, "a genuinely safe link is no longer followed/clicked"
    assert out["details"][0]["opened"] is False and "no detail appeared" in out["details"][0]["skipped_reason"]

    button = FakeTarget("Show details", role="button", tag="button")
    dc.capture_page(FakePage(button), route="/reports", page_url="http://x/v3/reports", indices=[0],
                    out_dir=None,
                    openers=[{"label": "Show details", "role": "button", "selector": "#open"}],
                    max_links=0)
    assert button.clicks == 1, "a safe detail button is no longer opened"


def test_F1_the_click_predicate_fails_closed():
    for role in ("", None, "none", "presentation", "heading", "tab", "link-ish"):
        assert is_forbidden_click("Open revenue", role) is True, role
        assert safe_to_activate("Open revenue", role) is False, role
    for role in ("", None, "link", "none"):
        assert is_forbidden_click("Approve", role) is True, role
    assert is_forbidden_click("Open revenue", "link") is False
    assert is_forbidden_click("Open revenue", "button") is False
    assert is_forbidden_click("", "button") is True   # unlabelled: nothing to judge it by
    assert is_forbidden_click(None, "link") is True


def test_R1_a_symlinked_page_directory_into_the_repo_is_refused(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "captures"
    root.mkdir()
    (root / "reports").symlink_to(repo / "leaked", target_is_directory=True)
    with pytest.raises(cr.CaptureRootRefused):
        cr.assert_inside_root(root / "reports", root)


def test_R1_the_out_argument_cannot_name_a_repository_path(tmp_path):
    """The real resolver the CLI calls, not just the checker it used to bypass."""
    from site_audit import page_audit_capture as pac
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    with pytest.raises(cr.CaptureRootRefused):
        pac.resolve_output_dir(str(repo / "data" / "page-audit-x"), "20261104T0000Z", repo_root=repo)
    # and a path that is merely NEAR the repo is fine once it resolves outside it
    outside = tmp_path / "captures"
    outside.mkdir()
    assert cr.assert_capture_root(outside, repo_root=repo) == outside.resolve()


# ── R2 (cx-openai-4): a LEAF symlink is the same escape as a directory symlink ────────────────────────────────
def test_a_leaf_symlink_cannot_smuggle_a_capture_into_the_repo(tmp_path):
    """A pre-existing `<vp>.txt -> ../../repo/...` used to be followed by write_text; the repo got written."""
    from site_audit.capture_root import CaptureRootRefused, assert_leaf_inside_root

    root = tmp_path / "captures"
    page_dir = root / "route"
    page_dir.mkdir(parents=True)
    repo_file = tmp_path / "repo" / "secret.txt"
    repo_file.parent.mkdir()
    repo_file.write_text("original\n")
    (page_dir / "phone.txt").symlink_to(repo_file)

    with pytest.raises(CaptureRootRefused) as exc:
        assert_leaf_inside_root(page_dir / "phone.txt", root)
    assert "symlink" in str(exc.value)
    assert repo_file.read_text() == "original\n", "the refused write must not have touched the target"


def test_a_normal_leaf_is_returned_and_written_inside_the_root(tmp_path):
    from site_audit.capture_root import assert_leaf_inside_root

    root = tmp_path / "captures"
    page_dir = root / "route"
    page_dir.mkdir(parents=True)
    leaf = assert_leaf_inside_root(page_dir / "phone.txt", root)
    leaf.write_text("body\n")
    assert leaf.read_text() == "body\n" and page_dir.resolve().is_relative_to(root.resolve())


def test_every_leaf_write_in_the_capture_module_goes_through_the_guard():
    """A future write added beside the others must not skip the guard."""
    src = (ROOT / "scripts/site_audit/page_audit_capture.py").read_text()
    writes = [ln for ln in src.splitlines() if ".write_text(" in ln or "screenshot(" in ln]
    assert writes, "no writes found — did the module move?"
    unguarded = [ln.strip() for ln in writes if "assert_leaf_inside_root" not in ln]
    assert not unguarded, unguarded


# ── R5 (cx-openai-4): a handle retained across a navigation is a link that never gets a result ────────────────
class _DetachingAnchor:
    """A real Playwright ElementHandle after a navigation: every read raises."""

    def __init__(self, href, label, page):
        self._href, self._label, self._page = href, label, page

    def _check(self):
        if self._page.navigations:
            raise RuntimeError("Element is not attached to the Document")

    def get_attribute(self, name):
        self._check()
        return self._href if name == "href" else None

    def inner_text(self):
        self._check()
        return self._label


class _LinkPage:
    def __init__(self, anchors):
        self.navigations = 0
        self._anchors = anchors

    def query_selector_all(self, _sel):
        return [_DetachingAnchor(h, l, self) for h, l in self._anchors]

    def goto(self, url, **_kw):
        self.navigations += 1

        class R:
            status = 200
        return R()

    def inner_text(self, _sel):
        return "a body"


def test_R5_every_allowed_link_gets_a_result_even_after_a_navigation(monkeypatch):
    from site_audit import deep_crawl

    page = _LinkPage([("/v3/a", "Show details"), ("/v3/b", "Open chart")])
    records = deep_crawl._follow_links(page, page_url="http://host/v3", max_links=5)
    assert [r.href for r in records] == ["/v3/a", "/v3/b"], [r.href for r in records]
    assert all(r.outcome for r in records)


# ── R7 (cx-openai-4): the live-crawl safeguards must not be bypassable ───────────────────────────────────────
def test_R7_the_health_gate_probes_the_declared_api_contract():
    from site_audit.page_audit_capture import HEALTH_PATH, HEALTH_PATH_FOR

    assert HEALTH_PATH == "/api/v2/health"
    assert HEALTH_PATH_FOR("http://host:7777") == "http://host:7777/api/v2/health"
    assert HEALTH_PATH_FOR("http://host:7777/") == "http://host:7777/api/v2/health"
    # cx-cloud CX1 on #2648: the CLI's default base is the /v3 FRONTEND mount; the health route lives on the origin.
    assert HEALTH_PATH_FOR("http://127.0.0.1:7777/v3") == "http://127.0.0.1:7777/api/v2/health"
    assert HEALTH_PATH_FOR("http://127.0.0.1:7777/v3/") == "http://127.0.0.1:7777/api/v2/health"
    assert "/v3/" not in HEALTH_PATH_FOR("http://127.0.0.1:7777/v3")


def test_CX4_the_live_gate_runs_before_route_discovery():
    """cx-cloud CX4 on #2648: the old entry point navigated the app before any §28.8 check."""
    from site_audit.page_audit_capture import live_access_refusal

    assert live_access_refusal("http://127.0.0.1:8123/v3") is None, "a fixture/replay backend was refused"

    src = (ROOT / "scripts/site_audit/page_audit_capture.py").read_text()
    gate = src.index("refusal = live_access_refusal(a.base)")
    discovery = src.index("discover_routes(page, a.base)")
    assert gate < discovery, "the live-access gate runs after route discovery"


def test_R7_the_pause_cannot_be_configured_below_the_floor():
    from site_audit.page_audit_capture import MIN_PAUSE_S, effective_pause

    assert MIN_PAUSE_S >= 4.0
    for requested in (0, 0.0, -3, None):
        assert effective_pause(requested) >= MIN_PAUSE_S, requested
    assert effective_pause(9) == 9


def test_R7_an_abort_stops_the_whole_sweep_not_just_one_route():
    """The loop must leave the viewport loop too; a `break` in the route loop alone kept capturing."""
    src = (ROOT / "scripts/site_audit/page_audit_capture.py").read_text()
    start = src.index("for vp, (w, h) in VIEWPORTS.items():")
    body = src[start:]
    end = body.index("browser.close()")
    loop = body[:end]
    assert "aborted = True" in loop, "an unhealthy server must set the abort flag"
    assert "if aborted:" in loop and loop.count("break") >= 2, loop


# ── R3 (cx-openai-4): completeness must include the CIO clock, in the function that decides completeness ──────
def _complete_card(**extra):
    """A card that satisfies every required symbol field, so only the CIO clock can make it incomplete."""
    from site_audit.completeness import REQUIRED_SYMBOL_FIELDS

    card = {name: 1.0 for name in REQUIRED_SYMBOL_FIELDS}
    card.update({"symbol": "AAA", "trend": "up", "cio_stance": "ADD"})
    card.update(extra)
    return card


def test_R3_an_undated_cio_stance_is_not_a_complete_card():
    from site_audit.completeness import card_severity, thesis_as_of_missing

    card = _complete_card()
    assert thesis_as_of_missing(card) is True
    severity, gaps = card_severity(card, top_list=False)
    assert severity is not None, "an undated stance read as a complete card"
    assert [g["field"] for g in gaps] == ["cio_as_of"], gaps


def test_R3_a_dated_cio_stance_is_still_complete():
    from site_audit.completeness import card_severity

    severity, gaps = card_severity(_complete_card(cio_as_of="2026-11-05T14:00:00Z"), top_list=False)
    assert severity is None and gaps == [], (severity, gaps)


# ── R6 (cx-openai-4): a successful link is not dead, and the receipt carries the deep facts ───────────────────
def test_R6_a_successful_link_is_not_counted_dead():
    from site_audit.page_audit_capture import deep_counters

    detail = {"details": [{"opened": True}], "refused": [], "links": [{"outcome": "ok"}, {"outcome": "dead"}]}
    c = deep_counters(detail, [0])
    assert c["links_followed"] == 2
    assert c["links_dead"] == 1, c          # the one 'ok' must NOT be dead
    assert c["details_opened"] == 1 and c["details_sampled"] == 1


def test_R6_the_viewport_receipt_is_written_after_the_deep_facts():
    src = (ROOT / "scripts/site_audit/page_audit_capture.py").read_text()
    deep_at = src.index("if deep:")
    receipt_at = src.index('f"{vp}.json"')
    assert receipt_at > deep_at, "the viewport receipt is written before the deep crawl runs"


# ── CX6 (cx-cloud): each hub tab is crawled while it is mounted ─────────────────────────────────────────────────
def test_CX6_a_hub_tab_is_deep_crawled_before_the_next_one_is_selected():
    """`TradingHub` mounts `OptionsHub` only while Options is selected; a crawl after the loop missed it entirely."""
    src = (ROOT / "scripts/site_audit/page_audit_capture.py").read_text()
    loop = src[src.index("for tab in tabs:"):src.index("row[\"console_errors\"]")]
    assert "_deep_into(trow" in loop, "the deep crawl is not run inside the hub-tab loop"
    assert 'f"{vp}-tab-{tslug}-"' in loop, "a tab crawl does not use tab-specific evidence filenames"
    # ...and a viewport that ran no tab crawl still crawls its route once.
    assert "_deep_into(row" in src
