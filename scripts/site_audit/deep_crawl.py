"""§6 deep crawl: open every sampled detail, follow in-page links one level, never press an action.

Operator (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104.md §6, 2026-11-04 ~12:45 ET): "Can it actually click every link
inside to see?" — yes for details and links; never for actions.

This module holds the browser-independent part: what counts as a detail opener, what is skipped, how far links are
followed, and how a target is judged. `capture_page(page, ...)` drives a Playwright page, but every decision it makes is
this module's, and those decisions are tested against a fake page rather than by hoping a live crawl is honest.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

_log = logging.getLogger("site_audit.deep_crawl")
from urllib.parse import urljoin, urlparse

from site_audit.action_denylist import ACTION_WORDS, safe_to_activate, safe_to_open

#: A link label that opens something inside the app (one level only).
IN_PAGE_LINK_WORDS = ("→", "open ", "view ", "details", "review ", "see ")

#: Where a followed link ended.
OK, BLANK, NOT_PERMITTED, DEAD, ERROR = "ok", "blank", "not_permitted", "dead", "error"


def note_sweep_status(sweep: dict[str, Any] | None, *, status: Any, url: str = "") -> str | None:
    """Record a 5xx so the WHOLE sweep stops (AGENTS §28.8: "stop at the first 5xx").

    `sweep` is a small dict shared by every page of one invocation. The first 5xx wins, and callers must check it
    before the next navigation: a 503 means the server is struggling, so continuing to load it is exactly what the
    boundary forbids. Returns the abort reason (also stored on `sweep`), or None when this is not a 5xx.
    """
    if sweep is None or status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    if code < 500:
        return None
    sweep.setdefault("abort", f"HTTP {code} from {url or 'a navigation or API response'}")
    return sweep["abort"]


@dataclass
class DetailRecord:
    opener: str
    label: str
    opened: bool
    skipped_reason: str | None = None
    fields: list[dict[str, str]] = field(default_factory=list)
    severity: str | None = None
    #: The element actually pressed when it was not the discovered node itself (a row's own detail button).
    pressed: str | None = None
    #: A plain-words note for a detail that opened but could not be graded (e.g. its contents were unreadable).
    notes: str | None = None


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
#:
#: cx-cloud CX3 on #2648: the old selector found row CONTAINERS (``div[data-testid='ta-row']``) and only buttons that
#: carried an explicit ``role='button'`` AND a label beginning "Open ". The product's own detail controls are native
#: ``<button>`` elements without a role attribute ("Show analysis for NVDA", "Open AI analysis", "View record"), so
#: they matched nothing and the pages received no detail coverage. Native buttons are discovered here; a container is
#: still discovered, but it is never pressed directly — `_safe_detail_child()` presses the container's own named
#: opener through the same fail-closed click boundary, so widening discovery does not widen what may be clicked.
OPENER_SELECTOR = ", ".join((
    "button[aria-label^='Open ']",
    "button[aria-label^='Show ']",
    "button[aria-label^='View ']",
    "[role='button'][aria-label^='Open ']",
    "[role='button'][aria-label^='Show ']",
    "[role='button'][aria-label^='View ']",
    "button:text-matches('^\\s*(Open|View|Show|Details)\\b', 'i')",
    "[data-testid$='-row']",
))


#: Surfaces that are an inline detail rather than a dialog/sheet. The Trade AI analysis panel is ALWAYS mounted: it
#: shows "Click a symbol or catalyst…" as a placeholder. It is therefore evidence only when it names the symbol the
#: crawler actually selected — see `_visible_detail()`.
INLINE_DETAIL_SELECTORS = ("[data-testid='ta-analysis']", "[aria-label='Catalyst analysis']")

DETAIL_SELECTORS = INLINE_DETAIL_SELECTORS + (
    "[role='dialog']", "[data-testid$='-sheet']", "[data-testid$='-detail']", "[data-testid$='-modal']",
)


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
    except Exception as exc:  # noqa: BLE001 -- unreadable target is refused, never clicked
        _log.debug("could not read the click target: %s", exc)
        return None


#: The words in an opener label that are not the symbol. "Show analysis for NVDA" -> NVDA.
_LABEL_NOISE = {"OPEN", "SHOW", "VIEW", "DETAIL", "DETAILS", "ANALYSIS", "RECORD", "FOR", "THE", "AND", "AI", "CIO"}


def _expected_symbol(target: Any = None, label: str = "") -> str | None:
    """The symbol a pressed opener is about, when the DOM says so.

    Used to confirm that an inline panel (which is mounted even before a selection) actually switched to the row the
    crawler pressed. `data-symbol` on the row is authoritative; otherwise a ticker-shaped token in the accessible
    label is used. No guess is better than a wrong one: an unknown symbol means the inline panel is not counted.
    """
    if target is not None:
        try:
            symbol = str(target.get_attribute("data-symbol") or "").strip()
        except Exception as exc:  # noqa: BLE001 -- an unreadable attribute is simply no hint
            _log.debug("could not read data-symbol from the opener: %s", exc)
            symbol = ""
        if symbol:
            return symbol.upper()
    for token in re.findall(r"\b[A-Z]{1,6}\b", str(label or "")):
        if token not in _LABEL_NOISE:
            return token
    return None


def _visible_detail(page: Any, expected_symbol: str | None = None) -> tuple[str, Any] | None:
    """(selector, locator) for the visible detail that is evidence for THIS click.

    A dialog/sheet/detail/modal is evidence as soon as it is visible. An inline panel is only evidence when it names
    the selected symbol: the Trade AI panel is always in the DOM with a "Click a symbol…" placeholder, so counting its
    mere visibility would report `opened: true` for a click that did nothing (cx-cloud CX7 on #2648).
    """
    for sel in DETAIL_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=500):
                continue
            if sel in INLINE_DETAIL_SELECTORS:
                if not expected_symbol:
                    continue
                text = loc.inner_text() or ""
                if expected_symbol.lower() not in text.lower():
                    continue
            return sel, loc
        except Exception as exc:  # noqa: BLE001 -- an absent selector is a normal "not open"
            _log.debug("detail selector %s was not visible: %s", sel, exc)
            continue
    return None


def _detail_is_open(page: Any, expected_symbol: str | None = None) -> bool:
    return _visible_detail(page, expected_symbol) is not None


#: Accessible names that read as "this opens something": the only children of a container the crawler will press.
#: Deliberately narrower than "any non-action button" — a row can hold a toggle or a preference control, and §6 says
#: the crawl opens details, not whatever happens to be clickable.
OPENER_NAME = re.compile(r"^\s*(open|show|view|expand|see|review)\b|\bdetails?\b", re.I)


def _detail_links(locator: Any) -> list[tuple[str, str]]:
    """Anchors inside an open detail, snapshotted while it is still open.

    cx-cloud CX2 on #2648: `_follow_links()` ran after every detail had been closed, so a link rendered only inside a
    detail (a "View the filing", "Open the record" row) was never seen. The href and accessible name are read here,
    before Escape, and followed afterwards by URL.
    """
    out: list[tuple[str, str]] = []
    try:
        nodes = locator.query_selector_all("a[href]")
    except Exception as exc:  # noqa: BLE001 -- no anchors is normal
        _log.debug("could not enumerate links inside the detail: %s", exc)
        return out
    for node in nodes[:40]:
        try:
            href = node.get_attribute("href")
            label = " ".join(part for part in ((node.get_attribute("aria-label") or "").strip(),
                                               (node.inner_text() or "").strip()) if part)
            if href:
                out.append((str(href), label))
        except Exception as exc:  # noqa: BLE001 -- an unreadable anchor is skipped
            _log.debug("skipped an anchor inside the detail: %s", exc)
    return out


def _capture_detail(page: Any, *, out_dir: Any = None, prefix: str = "", ordinal: int = 0,
                    expected_symbol: str | None = None) -> dict[str, Any] | None:
    """Persist and GRADE what the opened detail actually says, BEFORE it is closed.

    cx-openai-4 R3 on #2648. The crawl clicked an opener, saw that a detail had appeared, pressed Escape and recorded
    only `opened: true`. The detail's text — the whole reason for opening it, and the input to the pass-2 checks —
    existed in the DOM for 400 ms and nowhere else; the reviewer drove a detail whose text was a unique marker and
    found that marker in no saved artifact. The text (and a screenshot, when there is somewhere to put it) is written
    now while the detail is open, and its sha256 goes into the record, so a later pass can prove which text it graded
    without trusting the crawl's own account of itself.

    cx-cloud CX2 on #2648, the half that was still open: capturing was not enough. `severity` stayed null and `fields`
    held only file metadata, so a detail missing its technical evidence or CIO thesis produced exactly the same
    successful record as a complete one. The captured text is now run through the SAME completeness rule the
    cross-checks use (`completeness.assess_detail_text`), and the severity/gaps travel with the record. Links inside
    the open detail are snapshotted too (cx-cloud CX2's link clause).
    """
    import hashlib

    from site_audit.completeness import assess_detail_text

    found = _visible_detail(page, expected_symbol)
    if found is None:
        return None
    sel, loc = found
    try:
        text = loc.inner_text() or ""
    except Exception as exc:  # noqa: BLE001 -- an unreadable detail is reported, not silently "opened"
        _log.debug("could not read the opened detail (%s): %s", sel, exc)
        return None
    assessment = assess_detail_text(text)
    record: dict[str, Any] = {"detail_selector": sel, "chars": len(text),
                              "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "text": text,
                              "evidence_kind": "inline" if sel in INLINE_DETAIL_SELECTORS else "surface",
                              "completeness": assessment}
    if sel in INLINE_DETAIL_SELECTORS:
        # It qualified by naming `expected_symbol` in `_visible_detail()`, so this is a checked fact, not a hope.
        record["represents_selected"] = expected_symbol
    links = _detail_links(loc)
    if links:
        record["links"] = [{"href": href, "label": label[:120]} for href, label in links]
    if out_dir is not None:
        from pathlib import Path as _Path

        from site_audit.capture_root import assert_leaf_inside_root
        stem = f"{prefix}detail-{ordinal}"
        leaf = assert_leaf_inside_root(_Path(out_dir) / f"{stem}.txt", out_dir)
        leaf.write_text(text)
        record["file"] = leaf.name
        record.pop("text")  # the file is the evidence; the record names it and its digest
        try:
            shot = assert_leaf_inside_root(_Path(out_dir) / f"{stem}.png", out_dir)
            page.screenshot(path=str(shot), full_page=True)
            record["screenshot"] = shot.name
        except Exception as exc:  # noqa: BLE001 -- a screenshot is extra evidence, not the contract
            _log.debug("could not screenshot the opened detail: %s", exc)
    return record


def _safe_detail_child(target: Any) -> tuple[Any, str, str] | None:
    """The container's own detail button, when the container itself is not something the crawler may press.

    cx-openai-4 R9 on #2648. A table row is a container, not a control: the Options desk renders
    ``<div role="row" data-testid="options-desk-row" onClick=…>`` holding
    ``<button aria-label="Show NVDA credit put details">``. Refusing the row is right — its role is one the crawler
    will not press — but stopping there opened nothing at all on that page. The row's DETAIL button is the deliberate,
    read-only target, and it is chosen only when it names itself as an opener and passes the same click boundary.
    Anything else in the row (a toggle, an unlabelled button, an action) is left alone.
    """
    try:
        children = target.locator("button, [role='button']")
        count = int(children.count())
    except Exception as exc:  # noqa: BLE001 -- no reachable children is a refusal, not a crash
        _log.debug("could not enumerate a container's children: %s", exc)
        return None
    for i in range(min(count, 8)):
        try:
            child = children.nth(i)
        except Exception as exc:  # noqa: BLE001 -- one unreadable child is skipped and logged; the others are still examined
            _log.debug("could not read child %d: %s", i, exc)
            continue
        live = _live_label_role(child)
        if live is None:
            continue
        label, role = live
        if OPENER_NAME.search(label) and safe_to_activate(label, role):
            return child, label, role
    return None


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
                 openers: Iterable[dict[str, Any]] | None = None, max_links: int = 40,
                 prefix: str = "", sweep: dict[str, Any] | None = None) -> dict[str, Any]:
    """Open the sampled details, then follow in-page links one level.

    `page` is a Playwright page. Opener discovery is passed in when the caller already has it (tests, or a component
    that knows its own rows); otherwise rows and cards carrying a button/role are collected from the document.
    `prefix` names this viewport's evidence files (several viewports share one page directory).

    `sweep` is the invocation-wide abort state (see `note_sweep_status`). A 5xx observed by a link navigation, or by
    the caller's API response handler, stops the remaining openers here and the remaining links in `_follow_links`.
    """
    items = list(openers) if openers is not None else _discover_openers(page)
    allowed, refused = crawl_plan(items, indices)
    details: list[DetailRecord] = []
    #: Links snapshotted inside a detail while it was open, followed after it closes (cx-cloud CX2 on #2648).
    detail_links: list[tuple[str, str]] = []
    for ordinal, item in enumerate(allowed):
        if sweep is not None and sweep.get("abort"):
            break  # cx-cloud CX5 on #2648: do not keep opening details on a server that already returned 5xx
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
            pressed, pressed_label, via = target, live_label, None
            if not safe_to_activate(live_label, live_role):
                # cx-openai-4 R9 on #2648: a row is a container, not a control. Its own detail button is the
                # target the §6 contract means ("every selected row/card opens its read-only detail"); it is
                # pressed only when it names itself as an opener and passes the same fail-closed boundary.
                child = _safe_detail_child(target)
                if child is None:
                    details.append(DetailRecord(**{**rec.__dict__, "label": live_label,
                                                   "skipped_reason": f"refused at click time: {live_role} {live_label!r}"}))
                    refused.append({**item, "label": live_label, "role": live_role,
                                    "reason": "the live element carries an action label or a role the crawler "
                                              "will not press — §6 never presses an action"})
                    continue
                pressed, pressed_label, _child_role = child
                via = f"row container {live_role!r}; pressed its own detail button {pressed_label!r}"
            expected = _expected_symbol(pressed, pressed_label or rec.label)
            pressed.click(timeout=5000)
            page.wait_for_timeout(400)
            opened = _detail_is_open(page, expected)
            # cx-openai-4 R3 on #2648: the evidence is taken while the detail is open — after Escape it is gone.
            # cx-cloud CX2 on #2648: it is also GRADED while it is open, so "opened" and "complete" are different facts.
            evidence = (_capture_detail(page, out_dir=out_dir, prefix=prefix, ordinal=ordinal,
                                        expected_symbol=expected) if opened else None)
            severity, notes = None, None
            if evidence:
                completeness = evidence.get("completeness") or {}
                severity = completeness.get("severity")
                if completeness.get("evaluated") is False:
                    notes = "captured, but the text did not read as a symbol card, so it was not graded"
            elif opened:
                severity = "P1"
                notes = "a detail was visible but its contents could not be read"
            details.append(DetailRecord(**{**rec.__dict__, "label": pressed_label or rec.label, "opened": opened,
                                           "pressed": via, "fields": [evidence] if evidence else [],
                                           "severity": severity, "notes": notes,
                                           "skipped_reason": None if opened else "clicked but no detail appeared"}))
            for link in (evidence or {}).get("links") or []:
                href = link.get("href")
                if href:
                    detail_links.append((str(href), str(link.get("label") or "")))
        except Exception as exc:  # noqa: BLE001 -- an opener that does not open is a finding, not a crash
            details.append(DetailRecord(**{**rec.__dict__, "skipped_reason": f"{type(exc).__name__}"}))
        finally:
            try:
                page.keyboard.press("Escape")
            except Exception as exc:  # noqa: BLE001 -- closing a detail is best-effort
                _log.debug("Escape did not close the detail: %s", exc)
    return {"route": route, "details": [d.__dict__ for d in details],
            "refused": refused, "aborted": (sweep or {}).get("abort"),
            "links": [l.__dict__ for l in _follow_links(page, page_url=page_url, max_links=max_links,
                                                        extra_links=detail_links, sweep=sweep)]}


def _discover_openers(page: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        nodes = page.query_selector_all(OPENER_SELECTOR)
    except Exception as exc:  # noqa: BLE001 -- the failed read is logged; no openers found is the honest result, never a click target
        _log.warning("could not enumerate openers: %s: %s", type(exc).__name__, exc)
        nodes = []
    for i, node in enumerate(nodes):
        try:
            label = node.get_attribute("aria-label") or node.inner_text() or ""
            # cx-openai-4 R9 on #2648: the plan used to claim every discovered node was a button. A table row is
            # discovered here and its live role is `row`, so the plan described a control that does not exist —
            # and the click boundary, reading the truth, refused it while the plan said it was fine.
            #
            # cx-cloud CX3 on #2648: the plan must also be truthful for NATIVE buttons, which carry no role
            # attribute at all. Their tag says what they are; a container says `div`/`article`/`row` and stays a
            # container, handled by `_safe_detail_child()` rather than pressed directly.
            role = (node.get_attribute("role") or "").strip().lower()
            if not role:
                try:
                    tag = str(node.evaluate("e => e.tagName.toLowerCase()") or "").strip().lower()
                except Exception:  # noqa: BLE001 -- an unreadable tag is an unknown role, which is refused
                    tag = ""
                role = {"button": "button", "a": "link", "summary": "button", "input": "button"}.get(tag, "")
        except Exception as exc:  # noqa: BLE001 -- an unreadable node gets an empty label and role, which discovery refuses to click
            _log.debug("could not read opener %d: %s", i, exc)
            label, role = "", ""
        # codex R3 (2026-11-04): the old selector was fabricated ([data-open=N]) and matched nothing, so
        # a real click could never land. This is the same selector discovery used, pinned to the node.
        out.append({"index": i, "label": label[:120], "role": role or "none",
                    "selector": f"{OPENER_SELECTOR} >> nth={i}"})
    return out


#: How long a followed link's destination gets to render content before it is judged. Bounded on purpose: the crawl
#: must not hang on a page whose API never answers, and a shell read too early is exactly the false "ok" CX8 named.
LINK_SETTLE_MS = 6000


def _bounded_body_text(page: Any, *, settle_ms: int = LINK_SETTLE_MS) -> str:
    """The destination's rendered text, read after a bounded readiness wait.

    cx-cloud CX8 on #2648: `goto(wait_until="domcontentloaded")` then an immediate `inner_text("body")` read the
    React shell — or a "Loading…" line — before the page's `useApi` data arrived, so an API error or a permission
    failure on the destination was classified `ok`. The wait is bounded (a fixed budget, never "until network idle
    forever"), it stops at the first non-empty body, and it degrades to a plain read on a test double that has no
    waiting surface.
    """
    deadline = time.monotonic() + max(0, settle_ms) / 1000.0
    wait = getattr(page, "wait_for_timeout", None)
    text = ""
    while True:
        try:
            text = page.inner_text("body") or ""
        except Exception as exc:  # noqa: BLE001 -- an unreadable body is judged by the caller as ERROR
            _log.debug("could not read the destination body: %s", exc)
            text = ""
        if text.strip() or wait is None or time.monotonic() >= deadline:
            return text
        try:
            wait(250)
        except Exception as exc:  # noqa: BLE001 -- a fake/closed page cannot wait; return what we have
            _log.debug("destination readiness wait unavailable: %s", exc)
            return text


def _follow_links(page: Any, *, page_url: str, max_links: int,
                  extra_links: Iterable[tuple[str, str]] = (),
                  sweep: dict[str, Any] | None = None) -> list[LinkRecord]:
    records: list[LinkRecord] = []
    try:
        anchors = page.query_selector_all("a[href]")
    except Exception as exc:  # noqa: BLE001 -- the failed read is logged; no anchors means no links recorded, never a pass
        _log.warning("could not enumerate anchors: %s: %s", type(exc).__name__, exc)
        anchors = []
    # cx-openai-4 R5 on #2648: the handles were retained ACROSS navigations. The first goto detaches every
    # remaining anchor, so reading the second one raised and the loop skipped it — two allowed links produced one
    # record, silently. Snapshot what is needed (href, label) BEFORE leaving the page; a handle is then never used
    # after a navigation, and every allowed link gets a result.
    #
    # cx-openai-4 R1 (residual) on #2648: the snapshot read ONLY the visible text, truncated to 120 characters, so
    # an icon link whose accessible name was "Approve" had an empty label and was followed, and an action word past
    # character 120 was never seen. The label judged here is the link's FULL accessible name — aria-label plus the
    # whole text — and the truncation is applied only to what is recorded.
    snapshot: list[tuple[str | None, str, str]] = []
    seen: set[str] = set()

    def _add(href: Any, full: str) -> None:
        key = str(href or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        snapshot.append((key, full, full[:120]))

    for node in anchors[:max_links]:
        try:
            full = " ".join(part for part in ((node.get_attribute("aria-label") or "").strip(),
                                              (node.inner_text() or "").strip()) if part)
            _add(node.get_attribute("href"), full)
        except Exception as exc:  # noqa: BLE001 -- an anchor we cannot read is skipped, and said so
            _log.debug("skipped an anchor without readable attributes: %s", exc)
    # cx-cloud CX2 on #2648: links that existed only inside an open detail are followed by their snapshotted href.
    for href, label in list(extra_links)[:40]:
        _add(href, str(label or ""))
    for href, full_label, label in snapshot:
        if sweep is not None and sweep.get("abort"):
            break  # cx-cloud CX5 on #2648: a previous destination already 5xx'd — stop loading the server
        if not link_is_crawlable(full_label, href, page_url):
            continue
        try:
            resp = page.goto(urljoin(page_url, str(href)), wait_until="domcontentloaded", timeout=20000)
            status = getattr(resp, "status", None) if resp is not None else None
            text = _bounded_body_text(page)
            records.append(LinkRecord(href=str(href), label=label, outcome=classify_target(status, text), status=status))
            # cx-cloud CX5 on #2648: a 5xx is not merely a dead link — AGENTS §28.8 says stop at the FIRST one.
            note_sweep_status(sweep, status=status, url=str(href))
        except Exception as exc:  # noqa: BLE001 -- a link that cannot be followed is recorded as DEAD with no status, and logged
            _log.debug("could not follow %s: %s: %s", href, type(exc).__name__, exc)
            records.append(LinkRecord(href=str(href), label=label, outcome=DEAD, status=None))
        finally:
            # The return navigation is suppressed once the sweep has aborted: navigating back would be one more
            # request to the server the boundary says to leave alone.
            if sweep is None or not sweep.get("abort"):
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=20000)
                except Exception as exc:  # noqa: BLE001 -- the next link navigates anyway
                    _log.debug("could not return to %s before the next link: %s", page_url, exc)
    return records
