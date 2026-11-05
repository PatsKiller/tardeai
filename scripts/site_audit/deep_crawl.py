"""§6 deep crawl: open every sampled detail, follow in-page links one level, never press an action.

Operator (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104.md §6, 2026-11-04 ~12:45 ET): "Can it actually click every link
inside to see?" — yes for details and links; never for actions.

This module holds the browser-independent part: what counts as a detail opener, what is skipped, how far links are
followed, and how a target is judged. `capture_page(page, ...)` drives a Playwright page, but every decision it makes is
this module's, and those decisions are tested against a fake page rather than by hoping a live crawl is honest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

_log = logging.getLogger("site_audit.deep_crawl")
from urllib.parse import urljoin, urlparse

from site_audit.action_denylist import ACTION_WORDS, safe_to_activate, safe_to_open

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


#: The controls discovery treats as detail openers. One definition, used to find them and to click them.
OPENER_SELECTOR = "[data-testid$='-row'], [role='button'][aria-label^='Open ']"


DETAIL_SELECTORS = ("[role='dialog']", "[data-testid$='-sheet']", "[data-testid$='-detail']", "[data-testid$='-modal']")


def _live_label_role(target: Any) -> tuple[str, str] | None:
    """The label and role of the element that will ACTUALLY be clicked, or None when unreadable.

    codex R2 (2026-11-04): the plan-time guard checked metadata supplied by discovery. A selector can
    resolve to a different node — or the discovery itself can be wrong — and the synthetic Approve button
    was activated. The guard is therefore re-run on the live element immediately before the click, and an
    element whose label/role cannot be read is refused rather than clicked to find out.
    """
    try:
        role = str(target.get_attribute("role") or "").strip().lower()
        tag = str(target.evaluate("e => e.tagName.toLowerCase()") or "").strip().lower()
        if not role:
            if tag == "button":
                role = "button"
            elif tag == "a":
                role = "link"
            elif tag in ("input", "summary"):
                role = "button"
        label = target.get_attribute("aria-label") or target.inner_text() or ""
        return str(label).strip(), role
    except Exception as exc:  # noqa: BLE001 — unreadable target is refused, never clicked
        _log.debug("could not read the click target: %s", exc)
        return None


def _detail_is_open(page: Any) -> bool:
    for sel in DETAIL_SELECTORS:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return True
        except Exception as exc:  # noqa: BLE001 — an absent selector is a normal "not open"
            _log.debug("detail selector %s was not visible: %s", sel, exc)
            continue
    return False


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
            target = locator.first
            live = _live_label_role(target)
            if live is None:
                details.append(DetailRecord(**{**rec.__dict__, "skipped_reason": "unreadable click target — refused"}))
                refused.append({**item, "reason": "the target's label/role could not be read; not clicked"})
                continue
            live_label, live_role = live
            # The click boundary is fail-closed (whole-head F1): an action word refuses the node whatever its
            # role, and an absent/unknown role is never pressed to find out what it is. `<a>`, `<div>` and
            # role="none" labelled "Approve" are all refused here; only a readable, non-action clickable role
            # (a detail button, or a link) proceeds.
            if not safe_to_activate(live_label, live_role):
                details.append(DetailRecord(**{**rec.__dict__, "label": live_label,
                                               "skipped_reason": f"refused at click time: {live_role} {live_label!r}"}))
                refused.append({**item, "label": live_label, "role": live_role,
                                "reason": "the live element carries an action label or a role the crawler "
                                          "will not press — §6 never presses an action"})
                continue
            target.click(timeout=5000)
            page.wait_for_timeout(400)
            opened = _detail_is_open(page)
            details.append(DetailRecord(**{**rec.__dict__, "label": live_label or rec.label, "opened": opened,
                                           "skipped_reason": None if opened else "clicked but no detail appeared"}))
        except Exception as exc:  # noqa: BLE001 — an opener that does not open is a finding, not a crash
            details.append(DetailRecord(**{**rec.__dict__, "skipped_reason": f"{type(exc).__name__}"}))
        finally:
            try:
                page.keyboard.press("Escape")
            except Exception as exc:  # noqa: BLE001 — closing a detail is best-effort
                _log.debug("Escape did not close the detail: %s", exc)
    return {"route": route, "details": [d.__dict__ for d in details],
            "refused": refused,
            "links": [l.__dict__ for l in _follow_links(page, page_url=page_url, max_links=max_links)]}


def _discover_openers(page: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        nodes = page.query_selector_all(OPENER_SELECTOR)
    except Exception:  # noqa: BLE001
        nodes = []
    for i, node in enumerate(nodes):
        try:
            label = node.get_attribute("aria-label") or node.inner_text() or ""
        except Exception:  # noqa: BLE001
            label = ""
        # codex R3 (2026-11-04): the old selector was fabricated ([data-open=N]) and matched nothing, so
        # a real click could never land. This is the same selector discovery used, pinned to the node.
        out.append({"index": i, "label": label[:120], "role": "button",
                    "selector": f"{OPENER_SELECTOR} >> nth={i}"})
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
        except Exception as exc:  # noqa: BLE001 — an anchor we cannot read is skipped, and said so
            _log.debug("skipped an anchor without readable attributes: %s", exc)
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
            except Exception as exc:  # noqa: BLE001 — the next link navigates anyway
                _log.debug("could not return to %s before the next link: %s", page_url, exc)
    return records
