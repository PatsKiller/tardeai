"""The lane's two safety guarantees, proven by EXECUTED probes (codex R1/R2, 2026-11-04).

The whole-head review found both guarantees false in the code while 25 tests passed: an action button could be
activated, and a capture could land inside the public repository. A test that greps for a denylist or a root check
does not prove either. These probes drive the real functions with objects that record what happened:

  R2 — the guard is re-run on the element that would actually be clicked; a "safe" discovery whose selector
       resolves to an Approve button is refused and `click` is never called.
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


class FakeTarget:
    def __init__(self, label, role=""):
        self.label, self.role, self.clicks = label, role, 0

    def get_attribute(self, name):
        return self.role if name == "role" else (self.label if name == "aria-label" else None)

    def inner_text(self):
        return self.label

    def evaluate(self, _js):
        return "button"

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
