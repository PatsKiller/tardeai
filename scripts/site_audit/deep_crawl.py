"""§6 deep crawl: open every sampled detail, follow in-page links one level, never press an action.

Operator (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104.md §6, 2026-11-04 ~12:45 ET): "Can it actually click every link
inside to see?" — yes for details and links; never for actions.

This module holds the browser-independent part: what counts as a detail opener, what is skipped, how far links are
followed, and how a target is judged. `capture_page(page, ...)` drives a Playwright page, but every decision it makes is
this module's, and those decisions are tested against a fake page rather than by hoping a live crawl is honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from site_audit.action_denylist import ACTION_WORDS, safe_to_open

#: A link label that opens something inside the app (one level only).
IN_PAGE_LINK_WORDS = ("→", "open ", "view ", "details", "review ", "see ")

#: Where a followed link ended.
OK, BLANK, NOT_PERMITTED, DEAD, ERROR = "ok", "blank", "not_permitted", "dead", "error"


@dataclass
class DetailRecord:
    opener: str
    label: str
    opened: bool
    skipped_reason: str | None = None
    fields: list[dict[str, str]] = field(default_factory=list)
    severity: str | None = None


@dataclass
class LinkRecord:
    href: str
    label: str
    outcome: str
    status: int | None = None


def is_in_page_link(href: str | None, page_url: str) -> bool:
    """Same-origin http(s) links only: following an external site is not "inside" the app."""
    h = str(href or "").strip()
    if not h or h.startswith(("#", "mailto:", "javascript:", "tel:")):
        return False
    base = urlparse(page_url)
    target = urlparse(h)
    if not target.scheme and not target.netloc:
        return True  # a relative path stays inside the app
    if target.scheme not in ("http", "https"):
        return False
    return target.netloc == base.netloc


def link_is_crawlable(label: str | None, href: str | None, page_url: str) -> bool:
    """In-page, same-origin, and not an action by label.

    Stricter than the button rule on purpose: a same-origin link whose text says "Approve" is not followed, because a GET
    that performs an action is exactly the trap a deep crawl must not walk into.
    """
    if not is_in_page_link(href, page_url):
        return False
    text = str(label or "").strip()
    if text and ACTION_WORDS.search(text):
        return False
    return safe_to_open(label, "link")


def classify_target(status: int | None, text: str | None) -> str:
    """Judge a followed link by what came back, not by the fact that it navigated."""
    if status is None:
        return ERROR
    if status >= 500 or status == 404:
        return DEAD
    if status in (401, 403):
        return NOT_PERMITTED
    body = " ".join(str(text or "").split())
    if not body:
        return BLANK
    low = body.lower()
    if "not permitted" in low or "forbidden" in low or "not authorised" in low or "not authorized" in low:
        return NOT_PERMITTED
    return OK


def sampled_openers(openers: Iterable[dict[str, Any]], indices: Iterable[int]) -> list[dict[str, Any]]:
    """The budget, applied to real openers: only the sampled ones are ever clicked."""
    rows = list(openers)
    return [rows[i] for i in sorted({int(i) for i in indices if 0 <= int(i) < len(rows)})]


def crawl_plan(openers: Iterable[dict[str, Any]], indices: Iterable[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split sampled openers into what may be opened and what is refused, with a reason. Never silent."""
    allowed: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for item in sampled_openers(openers, indices):
        label = str(item.get("label") or "")
        role = str(item.get("role") or "")
        if safe_to_open(label, role):
            allowed.append(item)
        else:
            refused.append({**item, "reason": "action label or unlabelled control — §6 never presses an action"})
    return allowed, refused


def capture_page(page: Any, *, route: str, page_url: str, indices: Iterable[int], out_dir: Any,
                 openers: Iterable[dict[str, Any]] | None = None, max_links: int = 40) -> dict[str, Any]:
    """Open the sampled details, then follow in-page links one level.

    `page` is a Playwright page. Opener discovery is passed in when the caller already has it (tests, or a component
    that knows its own rows); otherwise rows and cards carrying a button/role are collected from the document.
    """
    items = list(openers) if openers is not None else _discover_openers(page)
    allowed, refused = crawl_plan(items, indices)
    details: list[DetailRecord] = []
    for item in allowed:
        rec = DetailRecord(opener=str(item.get("selector") or item.get("label") or ""), label=str(item.get("label") or ""), opened=False)
        try:
            locator = page.locator(str(item.get("selector") or ""))
            locator.first.click(timeout=5000)
            page.wait_for_timeout(400)
            details.append(DetailRecord(**{**rec.__dict__, "opened": True}))
        except Exception as exc:  # noqa: BLE001 — an opener that does not open is a finding, not a crash
            details.append(DetailRecord(**{**rec.__dict__, "skipped_reason": f"{type(exc).__name__}"}))
        finally:
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
    return {"route": route, "details": [d.__dict__ for d in details],
            "refused": refused,
            "links": [l.__dict__ for l in _follow_links(page, page_url=page_url, max_links=max_links)]}


def _discover_openers(page: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        nodes = page.query_selector_all("[data-testid$='-row'], [role='button'][aria-label^='Open ']")
    except Exception:  # noqa: BLE001
        nodes = []
    for i, node in enumerate(nodes):
        try:
            label = node.get_attribute("aria-label") or node.inner_text() or ""
        except Exception:  # noqa: BLE001
            label = ""
        out.append({"index": i, "label": label[:120], "role": "button", "selector": f"[data-open={i}]"})
    return out


def _follow_links(page: Any, *, page_url: str, max_links: int) -> list[LinkRecord]:
    records: list[LinkRecord] = []
    try:
        anchors = page.query_selector_all("a[href]")
    except Exception:  # noqa: BLE001
        return records
    for node in anchors[:max_links]:
        try:
            href = node.get_attribute("href")
            label = (node.inner_text() or "").strip()[:120]
        except Exception:  # noqa: BLE001
            continue
        if not link_is_crawlable(label, href, page_url):
            continue
        try:
            resp = page.goto(urljoin(page_url, str(href)), wait_until="domcontentloaded", timeout=20000)
            status = getattr(resp, "status", None) if resp is not None else None
            text = page.inner_text("body")
            records.append(LinkRecord(href=str(href), label=label, outcome=classify_target(status, text), status=status))
        except Exception:  # noqa: BLE001
            records.append(LinkRecord(href=str(href), label=label, outcome=DEAD, status=None))
        finally:
            try:
                page.goto(page_url, wait_until="domcontentloaded", timeout=20000)
            except Exception:  # noqa: BLE001
                pass
    return records
