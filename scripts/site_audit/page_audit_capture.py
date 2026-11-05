#!/usr/bin/env python3
"""Page audit, pass 1 (capture, no AI) — operator directive 2026-11-03 19:10 ET.

Visits every Command Center v3 page found in the LIVE navigation (plus the known hub tabs from
scripts/cc_v3_playwright_audit.py), one at a time, read-only, and saves per page and viewport:
  screenshot (full page), visible text of the main area, console errors, failed requests,
  /api/ calls with status and duration, and load time.
Viewports: desktop 1440x900, phone 412x915, phone 390x844.
Never clicks anything except hub TAB buttons named in HUB_TABS (navigation only). Never submits.

Usage: page_audit_capture.py [--out DIR] [--base URL] [--pause SECONDS] [--limit N]
Writes DIR/index.json (one row per page/viewport) and DIR/<slug>/<viewport>.{png,txt,json}.
"""
from __future__ import annotations

import logging

_log = logging.getLogger("site_audit.capture")

# Dark-contract declaration (scripts/check_dark_contracts.py): CapturedPage/PcapSchema@v1 is written by this
# CLI and read by the audit checks, but no scheduled caller exists yet — the site-audit n8n lane is proposed,
# not installed (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104 §2.1). Wiring the workflow is what removes this
# declaration; it is not a substitute for the caller.
NO_CONSUMER_REASON = ("the site-audit n8n lane is not installed yet (SPEC §2.1); the CLI is the entrypoint "
                      "and tests/test_site_audit_lane_20261104.py pins it until the workflow exists")

import argparse
import os
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # repo-relative once this file lives in scripts/site_audit
sys.path.insert(0, str(REPO / "scripts"))
try:
    from cc_v3_playwright_audit import HUB_TABS, NAV_ROUTES  # known routes and tabs
except Exception:  # pragma: no cover
    HUB_TABS, NAV_ROUTES = {}, []

VIEWPORTS = {"desktop": (1440, 900), "phone412": (412, 915), "phone390": (390, 844)}
#: The browser binary is configuration too (SITE_AUDIT_CHROME), never a personal path in a public repo.
EXEC = os.getenv("SITE_AUDIT_CHROME", "")
ACTION_WORDS = re.compile(r"approve|decline|acknowledge|submit|delete|cancel|place|buy|sell|refresh|retry|apply|merge|install|arm|stop", re.I)


def slug(route: str) -> str:
    s = route.strip("/").replace("/", "_") or "home"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", s)[:80]


def discover_routes(page, base: str) -> list[tuple[str, str]]:
    page.goto(base + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(1500)
    found = {}
    for a in page.locator("a[href]").all():
        try:
            href = a.get_attribute("href") or ""
            label = (a.inner_text() or "").strip().split("\n")[0][:60]
        except Exception as exc:  # noqa: BLE001 — an unreadable anchor is skipped, and said so
            _log.debug("skipped an anchor in route discovery: %s", exc)
            continue
        if href.startswith("/v3"):
            href = href[3:] or "/"
        if not href.startswith("/") or href.startswith("//") or "#" in href or "?" in href:
            continue
        if href.startswith("/api"):
            continue
        found.setdefault(href, label or href)
    for r, label in NAV_ROUTES:
        found.setdefault(r, label)
    return sorted(found.items())


def server_healthy(base: str, wait_s: int = 300) -> bool:
    """Gate before every page: the live server must answer quickly. If it does not, wait up to wait_s
    (it restarts itself), and abort the sweep rather than keep loading a struggling server.
    Added 2026-11-03 after the server was SIGKILLed mid-sweep (cause unverified)."""
    import urllib.parse
    import urllib.request
    scheme = urllib.parse.urlparse(base).scheme
    if scheme not in ("http", "https"):
        raise SystemExit(f"SITE_AUDIT base must be http(s): {scheme!r}")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            t0 = time.time()
            with urllib.request.urlopen(base + "/", timeout=10) as r:  # noqa: S310 — http(s) enforced above
                if r.status < 500 and time.time() - t0 < 8:
                    return True
        except Exception as exc:  # noqa: BLE001 — a failed probe is retried until the deadline
            _log.debug("health probe failed: %s", exc)
        time.sleep(15)
    return False


def capture(page, base: str, route: str, label: str, vp: str, out: Path, tabs: list[str], *, deep: bool = True) -> dict:
    api, failed, console = [], [], []
    starts = {}
    page.on("request", lambda r: starts.__setitem__(r, time.time()) if "/api/" in r.url else None)
    def on_resp(resp):
        if "/api/" in resp.url:
            t0 = starts.get(resp.request)
            api.append({"url": resp.url.split("7777")[-1][:160], "status": resp.status,
                        "ms": round((time.time() - t0) * 1000) if t0 else None})
        if resp.status >= 400:
            failed.append({"url": resp.url.split("7777")[-1][:160], "status": resp.status})
    page.on("response", on_resp)
    page.on("requestfailed", lambda r: failed.append({"url": r.url.split("7777")[-1][:160], "status": "failed", "error": (r.failure or "")[:80]}))
    page.on("console", lambda m: console.append(m.text[:200]) if m.type == "error" else None)
    page.on("pageerror", lambda e: console.append(f"PAGEERROR: {str(e)[:200]}"))

    from site_audit.capture_root import assert_inside_root, assert_leaf_inside_root
    d = out / slug(route)
    d.mkdir(parents=True, exist_ok=True)
    # codex R1 (2026-11-04): a pre-existing symlink here can point inside the checkout. Resolve the
    # directory and refuse before the first byte is written, so a capture can never enter the repo.
    d = assert_inside_root(d, out)
    row = {"route": route, "label": label, "viewport": vp, "url": base + route}
    t0 = time.time()
    try:
        resp = page.goto(base + route, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            row["networkidle_timeout"] = True
        page.wait_for_timeout(1500)
        row["status"] = resp.status if resp else None
        row["final_url"] = page.url
        row["load_ms"] = round((time.time() - t0) * 1000)
        main = page.locator("main").first
        text = main.inner_text() if main.count() else page.inner_text("body")
        assert_leaf_inside_root(d / f"{vp}.txt", out).write_text(text)
        row["text_chars"] = len(text)
        row["blank_suspect"] = len(text.strip()) < 80
        low = text.lower()
        row["flags"] = sorted({w for w in ("loading", "unavailable", "stale", "unknown", "error", "failed", "withheld", "not found", "—")
                               if w in low})
        row["h_scroll"] = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        page.screenshot(path=str(assert_leaf_inside_root(d / f"{vp}.png", out)), full_page=True)
        if vp == "desktop":
            for tab in tabs:
                if ACTION_WORDS.search(tab):
                    continue
                trow = {"tab": tab}
                try:
                    btn = page.get_by_role("button", name=tab, exact=True)
                    if btn.count() == 0:
                        trow["missing"] = True
                    else:
                        btn.first.click(timeout=5000)
                        page.wait_for_timeout(1500)
                        tt = main.inner_text() if main.count() else page.inner_text("body")
                        tslug = re.sub(r"[^A-Za-z0-9]+", "-", tab)
                        assert_leaf_inside_root(d / f"tab-{tslug}.txt", out).write_text(tt)
                        page.screenshot(path=str(assert_leaf_inside_root(d / f"tab-{tslug}.png", out)), full_page=True)
                        trow["text_chars"] = len(tt)
                        trow["blank_suspect"] = len(tt.strip()) < 60
                except Exception as e:
                    trow["error"] = str(e)[:150]
                row.setdefault("tabs", []).append(trow)
    except Exception as e:
        row["error"] = str(e)[:300]
    row["console_errors"] = console[:20]
    row["failed_requests"] = failed[:30]
    row["api_calls"] = api[:80]
    row["slow_api"] = [a for a in api if (a.get("ms") or 0) > 3000]
    assert_leaf_inside_root(d / f"{vp}.json", out).write_text(json.dumps(row, indent=1))
    # codex R3 (2026-11-04): the CLI captured screenshots and never invoked the deep crawl, so no detail
    # was ever opened and no completeness check ever ran. The crawl and its evidence are now part of the
    # capture, on the same page and viewport, under the pinned detail budget.
    if deep:
        from site_audit import deep_crawl, detail_budget
        openers = deep_crawl._discover_openers(page)
        week = int(time.strftime("%V"))
        indices = detail_budget.selected_indices(len(openers), page=route, week_index=week)
        detail = deep_crawl.capture_page(page, route=route, page_url=base + route, indices=indices,
                                         out_dir=d, openers=openers)
        assert_leaf_inside_root(d / f"{vp}-details.json", out).write_text(json.dumps(detail, indent=1))
        row["details_sampled"] = len(indices)
        row["details_opened"] = sum(1 for x in detail["details"] if x.get("opened"))
        row["details_refused"] = [x.get("selector") or x.get("label") for x in detail["refused"]]
        row["links_followed"] = len(detail["links"])
        row["links_dead"] = sum(1 for x in detail["links"] if x.get("outcome") not in (None, "OK"))
    return row


def resolve_output_dir(out_arg: str | None, stamp: str, *, repo_root: Path | str | None = None) -> Path:
    """The capture directory, refused unless it resolves outside the checkout.

    codex R1 (2026-11-04): `--out` used to skip the boundary entirely, so an argument could place a
    capture inside the public repository. Both branches now go through the same resolved-path check,
    and this function exists so the guarantee can be probed without launching a browser.
    """
    from site_audit.capture_root import assert_capture_root, configured_capture_root
    root = repo_root if repo_root is not None else REPO
    out = (assert_capture_root(out_arg, repo_root=root) if out_arg
           else configured_capture_root(repo_root=root) / f"page-audit-{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    return assert_capture_root(out, repo_root=root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:7777/v3")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pause", type=float, default=4.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only-failed-from", default=None, help="index.json of an earlier run: recapture only its error rows")
    ap.add_argument("--no-deep", action="store_true", help="screenshots only; skip opening sampled details and following links")
    a = ap.parse_args()
    a.only = None
    if a.only_failed_from:
        prev = json.load(open(a.only_failed_from))
        a.only = {(r["viewport"], r["route"]) for r in prev["index"] if r.get("error")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    out = resolve_output_dir(a.out, stamp)
    from playwright.sync_api import sync_playwright
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EXEC)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        routes = discover_routes(page, a.base)
        ctx.close()
        if a.limit:
            routes = routes[: a.limit]
        print(f"{len(routes)} routes discovered", flush=True)
        for vp, (w, h) in VIEWPORTS.items():
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      is_mobile=vp != "desktop", has_touch=vp != "desktop")
            for route, label in routes:
                if a.only and (vp, route) not in a.only:
                    continue
                if not server_healthy(a.base):
                    print("ABORT: server not healthy for 5 minutes; stopping the sweep", flush=True)
                    rows.append({"route": route, "viewport": vp, "error": "aborted: server unhealthy"})
                    break
                page = ctx.new_page()
                r = capture(page, a.base, route, label, vp, out, HUB_TABS.get(route, []), deep=not a.no_deep)
                page.close()
                rows.append(r)
                print(f"{vp:8} {route:40} {'ERR ' + r['error'][:60] if r.get('error') else ('BLANK? ' if r.get('blank_suspect') else 'ok')}"
                      f" fail={len(r.get('failed_requests', []))} console={len(r.get('console_errors', []))}", flush=True)
                time.sleep(a.pause)
            ctx.close()
        browser.close()
    summary = {"schema": "PageAuditCapture@v1", "captured_at": stamp, "base": a.base, "routes": len(routes),
               "rows": len(rows), "errors": sum(1 for r in rows if r.get("error")),
               "blank_suspects": sum(1 for r in rows if r.get("blank_suspect")),
               "with_failed_requests": sum(1 for r in rows if r.get("failed_requests")),
               "with_console_errors": sum(1 for r in rows if r.get("console_errors")),
               "h_scroll_phone": [r["route"] for r in rows if r.get("h_scroll") and r["viewport"] != "desktop"],
               "index": [{k: r.get(k) for k in ("route", "label", "viewport", "status", "load_ms", "text_chars",
                                                "blank_suspect", "flags", "h_scroll", "error")}
                         | {"failed": len(r.get("failed_requests", [])), "console": len(r.get("console_errors", [])),
                            "slow_api": len(r.get("slow_api", []))} for r in rows]}
    assert_leaf_inside_root(out / "index.json", out).write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "index"}, indent=1))
    print(f"OUT {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
