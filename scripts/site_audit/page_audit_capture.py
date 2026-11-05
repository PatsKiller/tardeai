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


#: The health contract page_audit_capture obeys (SPEC §2.1). A capture reads the v3 APIs, so the
#: gate probes the API health contract rather than the frontend root.
HEALTH_PATH = "/api/v2/health"
#: The pacing floor. `--pause 0` used to be accepted, which removed the "at least 4 s between pages"
#: safeguard entirely (cx-openai-4 R7).
MIN_PAUSE_S = 4.0


def HEALTH_PATH_FOR(base: str) -> str:
    """The health URL for one base, resolved against the SERVER ORIGIN.

    cx-cloud CX1 on #2648: the CLI's default base is ``http://127.0.0.1:7777/v3`` — the frontend's mount point.
    Appending the API path to it produced ``/v3/api/v2/health``, which `scripts/portfolio_server.py` answers with the
    SPA fallback (HTML, status 200), so the gate could report a healthy server while the API was down and every page
    capture would then fail or read stale data. The health route lives at the origin, not under the frontend base.
    """
    import urllib.parse
    parsed = urllib.parse.urlparse(str(base or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"SITE_AUDIT base must be an http(s) URL with a host: {base!r}")
    return f"{parsed.scheme}://{parsed.netloc}{HEALTH_PATH}"


def effective_pause(requested: float | None) -> float:
    """The pause actually slept between pages: never below the contract's floor, never negative."""
    try:
        value = float(requested if requested is not None else MIN_PAUSE_S)
    except (TypeError, ValueError):
        value = MIN_PAUSE_S
    return max(MIN_PAUSE_S, value)


def live_access_refusal(base: str) -> str | None:
    """The §28.8 reason this base must not be crawled now, or None.

    cx-cloud CX4 on #2648: with the default live base, invoking the CLI during 04:00–16:15 ET on a market day sent
    browser traffic through `discover_routes` before any check. `lane.live_access_violation()` is the one rule (market
    calendar + wall clock + the after-close acknowledgement); a fixture/replay backend on another loopback port is
    permitted, which is how the in-session and test runs work. This wrapper exists so the CLI's gate can be probed
    without a browser.
    """
    from site_audit import lane
    return lane.live_access_violation(base)


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
            # cx-openai-4 R7 on #2648: the contract names /api/v2/health, not the v3 frontend root —
            # probing "/" only proves the page server is up, not that the API a capture reads is healthy.
            # cx-cloud CX1 on #2648: the URL is resolved on the ORIGIN (`HEALTH_PATH_FOR`), and the answer must be
            # JSON. An HTML body here is the SPA fallback answering for a route the API did not handle, which is
            # exactly the "healthy frontend, dead API" state this gate exists to refuse.
            with urllib.request.urlopen(HEALTH_PATH_FOR(base), timeout=10) as r:  # noqa: S310 — http(s) enforced
                body = r.read(4096)
                if r.status >= 500 or time.time() - t0 >= 8:
                    continue
                if "html" in str(r.headers.get("content-type") or "").lower():
                    _log.warning("health probe answered HTML (SPA fallback?) — not healthy: %s", r.url)
                    continue
                try:
                    json.loads(body.decode("utf-8", "replace") or "null")
                except (ValueError, TypeError):
                    _log.warning("health probe answered non-JSON — not healthy: %s", r.url)
                    continue
                return True
        except Exception as exc:  # noqa: BLE001 — a failed probe is retried until the deadline
            _log.debug("health probe failed: %s", exc)
        time.sleep(15)
    return False


def note_http_status(sweep: dict | None, *, status, url: str = "") -> str | None:
    """The one 5xx rule for navigation and API responses (AGENTS §28.8: stop at the first 5xx).

    Both the response handler and the page's own navigation feed this, so a 503 is an abort wherever it is seen —
    not just in the link follower. The first reason wins and `main()` checks it after every page.
    """
    from site_audit.deep_crawl import note_sweep_status
    return note_sweep_status(sweep, status=status, url=url)


def deep_counters(detail: dict, indices: list[int]) -> dict:
    """The row's deep-crawl facts, counted against the SHARED outcome constant.

    cx-openai-4 R6 on #2648: this compared each link's outcome to the string "OK" while deep_crawl's outcomes are
    lowercase, so every successful link was counted dead (links_followed=1, links_dead=1 for one good 200).
    """
    from site_audit.deep_crawl import OK

    links = detail.get("links") or []
    return {
        "details_sampled": len(indices),
        "details_opened": sum(1 for x in detail.get("details") or [] if x.get("opened")),
        "details_refused": [x.get("selector") or x.get("label") for x in detail.get("refused") or []],
        "links_followed": len(links),
        "links_dead": sum(1 for x in links if x.get("outcome") not in (None, OK)),
    }


def capture(page, base: str, route: str, label: str, vp: str, out: Path, tabs: list[str], *,
            deep: bool = True, sweep: dict | None = None) -> dict:
    api, failed, console = [], [], []
    sweep = sweep if sweep is not None else {}
    starts = {}
    page.on("request", lambda r: starts.__setitem__(r, time.time()) if "/api/" in r.url else None)
    def on_resp(resp):
        if "/api/" in resp.url:
            t0 = starts.get(resp.request)
            api.append({"url": resp.url.split("7777")[-1][:160], "status": resp.status,
                        "ms": round((time.time() - t0) * 1000) if t0 else None})
        if resp.status >= 400:
            failed.append({"url": resp.url.split("7777")[-1][:160], "status": resp.status})
        # cx-cloud CX5 on #2648: an API 5xx is the §28.8 stop condition too, not just a failed-request row.
        note_http_status(sweep, status=resp.status, url=resp.url)
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

    #: One entry per deep crawl actually run on this viewport (one per hub tab on desktop, else one for the route).
    deep_runs: list[tuple[dict, list[int]]] = []

    def _deep_into(holder: dict, prefix: str) -> None:
        """Deep-crawl the page AS IT IS NOW and record tab-specific evidence filenames.

        cx-cloud CX6 on #2648: the crawl ran once, after the hub-tab loop, so it examined whichever tab was selected
        last. `TradingHub` mounts `OptionsHub` only while Options is selected, so Options details and links received no
        deep coverage at all. Running it inside each successful tab visit (with `desktop-tab-<tab>-` prefixes) covers
        every tab that was screenshotted; a phone capture, which never switches tabs, still crawls its route once.
        """
        from site_audit import deep_crawl, detail_budget, lane
        if sweep.get("abort"):
            return  # cx-cloud CX5 on #2648: a 5xx already stopped this sweep; open nothing else
        openers = deep_crawl._discover_openers(page)
        # cx-openai-4 R4 on #2648: the ISO week was the sampling step, so all five runs of a week re-opened the same
        # twenty rows and a long table's remaining rows were never reached. The step is the scheduled RUN.
        run_index = lane.run_slot(datetime.now(timezone.utc))
        indices = detail_budget.selected_indices(len(openers), page=route, run_index=run_index)
        detail = deep_crawl.capture_page(page, route=route, page_url=base + route, indices=indices,
                                         out_dir=d, openers=openers, prefix=prefix, sweep=sweep)
        assert_leaf_inside_root(d / f"{prefix}details.json", out).write_text(json.dumps(detail, indent=1))
        holder.update(deep_counters(detail, indices))
        deep_runs.append((detail, indices))

    row = {"route": route, "label": label, "viewport": vp, "url": base + route}
    t0 = time.time()
    try:
        resp = page.goto(base + route, wait_until="domcontentloaded", timeout=45000)
        note_http_status(sweep, status=getattr(resp, "status", None), url=base + route)
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
        if vp == "desktop" and not sweep.get("abort"):
            # cx-cloud CX5 on #2648: a 5xx already stopped the sweep; do not click tabs (more load) on that server.
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
                        # cx-cloud CX6 on #2648: crawl THIS tab before switching away, under tab-specific names.
                        if deep:
                            _deep_into(trow, f"{vp}-tab-{tslug}-")
                except Exception as e:
                    trow["error"] = str(e)[:150]
                row.setdefault("tabs", []).append(trow)
    except Exception as e:
        row["error"] = str(e)[:300]
    row["console_errors"] = console[:20]
    row["failed_requests"] = failed[:30]
    row["api_calls"] = api[:80]
    row["slow_api"] = [a for a in api if (a.get("ms") or 0) > 3000]
    # cx-openai-4 R6 on #2648: the viewport JSON used to be written HERE, before the deep crawl ran, so the
    # persisted receipt carried none of the details_*/links_* counters while the row in memory did. The receipt is
    # written at the end of the function now, after the deep facts are attached.
    # codex R3 (2026-11-04): the CLI captured screenshots and never invoked the deep crawl, so no detail
    # was ever opened and no completeness check ever ran. The crawl and its evidence are now part of the
    # capture, on the same page and viewport, under the pinned detail budget.
    # cx-cloud CX6 on #2648: desktop tabs are crawled inside the loop above. A viewport that ran no tab crawl
    # (phone, or a route with no hub tabs) crawls the route once, exactly as before.
    if deep:
        if not deep_runs and not sweep.get("abort"):
            _deep_into(row, f"{vp}-")
        merged = {"details": [d for det, _ in deep_runs for d in det.get("details") or []],
                  "refused": [r for det, _ in deep_runs for r in det.get("refused") or []],
                  "links": [l for det, _ in deep_runs for l in det.get("links") or []]}
        row.update(deep_counters(merged, [i for _, idx in deep_runs for i in idx]))
    if sweep.get("abort"):
        row["sweep_abort"] = sweep["abort"]
    assert_leaf_inside_root(d / f"{vp}.json", out).write_text(json.dumps(row, indent=1))
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


#: The per-run receipt, and the stable pointer to the newest one that the lane is observed through.
#: cx-openai-4 R8 on #2648: the lane registry declares `json_key` on `generated_at`, but the CLI wrote only
#: `captured_at`, and it declared a dated, wildcarded path that neither reader (`lane_registry.observe_signal`,
#: `cron_outage_watchdog`) resolves — both require an exact path. A dated directory cannot be observed without
#: globbing, so the run now also drops a pointer beside its own directory, and the registry observes that.
SUMMARY_SCHEMA = "PageAuditCapture@v1"
LATEST_SCHEMA = "PageAuditCaptureLatest@v1"
LATEST_NAME = "page-audit-latest.json"


def build_summary(rows: list[dict], *, stamp: str, base: str, routes, completed: bool = True) -> dict:
    """One run's receipt: a row per page/viewport, plus the run's own timestamp.

    `generated_at` is the key the lane's output signal observes. `captured_at` is kept beside it because the
    receipts already written under PageAuditCapture@v1 carry that spelling; both name the same instant, so a reader
    keyed on either sees a finished run rather than a silent lane.

    `completed` is False for an attempt that stopped early. The attempt still gets its own receipt, but it must not
    advance the successful-run pointer (cx-cloud CX6 on #2648; AGENTS §28.9 defines health as the last successful run).
    """
    return {
        "schema": SUMMARY_SCHEMA, "generated_at": stamp, "captured_at": stamp, "completed": completed, "base": base,
        "routes": len(routes), "rows": len(rows),
        "errors": sum(1 for r in rows if r.get("error")),
        "blank_suspects": sum(1 for r in rows if r.get("blank_suspect")),
        "with_failed_requests": sum(1 for r in rows if r.get("failed_requests")),
        "with_console_errors": sum(1 for r in rows if r.get("console_errors")),
        "h_scroll_phone": [r["route"] for r in rows if r.get("h_scroll") and r["viewport"] != "desktop"],
        "index": [{k: r.get(k) for k in ("route", "label", "viewport", "status", "load_ms", "text_chars",
                                         "blank_suspect", "flags", "h_scroll", "error")}
                  | {"failed": len(r.get("failed_requests", [])), "console": len(r.get("console_errors", [])),
                     "slow_api": len(r.get("slow_api", []))} for r in rows],
    }


def write_receipts(out: Path, rows: list[dict], *, stamp: str, base: str, routes,
                   completed: bool = True) -> dict:
    """Write the run's `index.json` and, only on a completed sweep, the pointer the lane is observed through.

    Both writes go through the R2 leaf guard, and the pointer is a plain leaf beside the dated capture
    directories — never a symlink, never inside the checkout.

    cx-cloud CX6 on #2648: the pointer used to be written by EVERY attempt, including one aborted at the first
    health gate, so `generated_at` stayed fresh while full-site coverage stopped. The attempt keeps its own dated
    receipt and `index.json`; only a sweep that reached the end advances the successful-run pointer. An aborted run
    therefore leaves the previous good pointer untouched (or absent, if there has never been a good run).

    Measured on this head before the change: `main()` referenced `assert_leaf_inside_root` without importing it in
    its own scope (the only import lived inside `capture()`), so a completed crawl raised NameError here and wrote
    no receipt at all. The import is local to this function now, and the test drives this function rather than
    trusting the call site.
    """
    from site_audit.capture_root import assert_leaf_inside_root
    summary = build_summary(rows, stamp=stamp, base=base, routes=routes, completed=completed)
    assert_leaf_inside_root(out / "index.json", out).write_text(json.dumps(summary, indent=1))
    if completed:
        latest = {"schema": LATEST_SCHEMA, "generated_at": stamp, "capture_dir": out.name, "completed": True,
                  "rows": summary["rows"], "errors": summary["errors"],
                  "blank_suspects": summary["blank_suspects"]}
        assert_leaf_inside_root(out.parent / LATEST_NAME, out.parent).write_text(json.dumps(latest, indent=1))
    return summary


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
    # cx-cloud CX4 on #2648: BEFORE route discovery (which navigates the app) or a health probe, refuse a live crawl
    # inside the §28.8 window and require the operator's after-close acknowledgement outside it. Fixtures/replay pass.
    refusal = live_access_refusal(a.base)
    if refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr, flush=True)
        return 2
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
        aborted = False
        #: Invocation-wide abort state: a 5xx anywhere (navigation or API response) stops the whole sweep.
        sweep: dict = {}
        for vp, (w, h) in VIEWPORTS.items():
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      is_mobile=vp != "desktop", has_touch=vp != "desktop")
            for route, label in routes:
                if a.only and (vp, route) not in a.only:
                    continue
                # A sweep can cross 04:00 ET. Re-check the boundary before every page, not only at startup.
                refusal = live_access_refusal(a.base)
                if refusal:
                    print(f"ABORT: {refusal}", flush=True)
                    rows.append({"route": route, "viewport": vp, "error": f"aborted: {refusal}"})
                    aborted = True
                    break
                if not server_healthy(a.base):
                    # cx-openai-4 R7: `break` left the ROUTE loop and the next viewport carried on, so an
                    # aborted sweep kept capturing. The contract says stop the whole invocation.
                    print("ABORT: server not healthy for 5 minutes; stopping the sweep", flush=True)
                    rows.append({"route": route, "viewport": vp, "error": "aborted: server unhealthy"})
                    aborted = True
                    break
                page = ctx.new_page()
                r = capture(page, a.base, route, label, vp, out, HUB_TABS.get(route, []),
                            deep=not a.no_deep, sweep=sweep)
                page.close()
                rows.append(r)
                print(f"{vp:8} {route:40} {'ERR ' + r['error'][:60] if r.get('error') else ('BLANK? ' if r.get('blank_suspect') else 'ok')}"
                      f" fail={len(r.get('failed_requests', []))} console={len(r.get('console_errors', []))}", flush=True)
                if sweep.get("abort"):
                    # cx-cloud CX5 on #2648: AGENTS §28.8 says stop at the FIRST 5xx. A 503 on a linked
                    # destination or an API call ends the invocation; nothing else is loaded.
                    print(f"ABORT: {sweep['abort']}; stopping the sweep", flush=True)
                    aborted = True
                    break
                time.sleep(effective_pause(a.pause))
            ctx.close()
            if aborted:
                break
        browser.close()
    summary = write_receipts(out, rows, stamp=stamp, base=a.base, routes=routes, completed=not aborted)
    print(json.dumps({k: v for k, v in summary.items() if k != "index"}, indent=1))
    print(f"OUT {out}")
    # An aborted sweep is not a successful run: exit non-zero so an n8n caller cannot read a green step (rule 8).
    return 0 if not aborted else 1


if __name__ == "__main__":
    sys.exit(main())
