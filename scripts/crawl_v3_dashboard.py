#!/usr/bin/env python3
"""crawl_v3_dashboard.py — visual/error audit of the Command Center v3 dashboard.

Visits every v3 hub and flags real problems: failed API responses (4xx/5xx → dead endpoints / data
sources), console errors, uncaught page exceptions, and pages stuck on "Loading…". The single-threaded
server can pile up heavy requests during a fast crawl and time out a goto — so any route that fails the
fast pass is AUTO-RETESTED individually (fresh page, longer timeout, server allowed to settle) before being
reported, to avoid crawl-speed false positives.

Exit code 0 = clean; 1 = real issues found (CI/cron friendly).

  python3 scripts/crawl_v3_dashboard.py [--base http://localhost:7777] [--screenshots DIR]
"""
import argparse
import os
import sys
import time
import urllib.request


def _send_telegram(message):
    """Alert on confirmed issues via telegram_alert chokepoint."""
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        send_telegram(message)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="crawl_v3_dashboard", subject_key="ops:v3_crawl",
                retention_class="operational", severity="warning",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def _server_up(base, tries=20, gap=2.0):
    """The v3 dashboard is served by a SINGLE-THREADED server; a fast crawl can momentarily overwhelm it
    (watchdog restart → ERR_CONNECTION_REFUSED). Poll a light endpoint so we never mistake a transient
    server blip for a dead route."""
    url = base.replace("/v3", "") + "/api/v2/data-source-health"
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=5)
            return True
        except Exception:
            time.sleep(gap)
    return False

ROUTES = ["", "portfolio", "risk", "trading", "manual-execution", "strategy", "agents", "intelligence",
          "hermes", "retirement", "journal", "watchlist", "watchpool", "sectors", "reports", "rotation",
          "rec-intel", "advisor-changes", "system"]


def _visit(pg, url, settle_ms, timeout_ms):
    """Load a route, return (loaded_ok, failed_api[], console_errs[], page_errs[], stuck)."""
    failed, cerr, perr = [], [], []
    pg.on("response", lambda r, F=failed: (
        F.append((r.url.split("/v2/")[-1].split("?")[0] if "/v2/" in r.url else r.url, r.status))
        if (r.status >= 400 and "/api/" in r.url) else None))
    pg.on("console", lambda m, C=cerr: (C.append(m.text[:120]) if m.type == "error" else None))
    pg.on("pageerror", lambda e, P=perr: P.append(str(e)[:120]))
    stuck = False
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        pg.wait_for_timeout(settle_ms)
        body = pg.inner_text("body")
        stuck = len(body) < 200 or body.strip().lower().endswith(("loading…", "loading..."))
        loaded = not stuck
    except Exception as e:
        perr.append("NAV FAIL: " + str(e)[:90]); loaded = False; stuck = True
    return loaded, failed, cerr, perr, stuck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:7777")
    ap.add_argument("--screenshots", default="")
    ap.add_argument("--telegram", action="store_true", help="Alert via Telegram on confirmed issues")
    args = ap.parse_args()
    if args.telegram:
        try:
            from pathlib import Path as _P
            for _l in (_P(__file__).resolve().parent.parent / ".env").read_text().splitlines():
                if "=" in _l and not _l.strip().startswith("#"):
                    _k, _, _v = _l.partition("="); os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
        except Exception:
            pass
    base = args.base.rstrip("/") + "/v3"
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("ABORT: playwright not installed (.venv/bin/python -m playwright install chromium)")
        return 2
    if args.screenshots:
        import os
        os.makedirs(args.screenshots, exist_ok=True)

    issues = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        # Pass 1 — gentle sequential crawl (delay between routes so we don't overwhelm the
        # single-threaded server and trip its watchdog — that would create false ERR_CONNECTION_REFUSED).
        for route in ROUTES:
            _server_up(base)  # wait out any transient blip before loading the next route
            pg = b.new_page(viewport={"width": 1500, "height": 1000})
            loaded, failed, cerr, perr, stuck = _visit(pg, f"{base}/{route}", 3500, 25000)
            time.sleep(1.2)
            if args.screenshots:
                try: pg.screenshot(path=f"{args.screenshots}/{route or 'home'}.png", full_page=True)
                except Exception: pass
            if failed or cerr or perr or stuck:
                issues[route or "home"] = {"failed": failed, "console": cerr, "pageerr": perr, "stuck": stuck}
            pg.close()
        # Pass 2 — auto-retest each flagged route individually (kills crawl-speed false positives)
        confirmed = {}
        for route, _ in list(issues.items()):
            rk = "" if route == "home" else route
            time.sleep(3)
            if not _server_up(base):     # server itself is down — that's an availability issue, not a route bug
                confirmed["__server__"] = {"failed": [], "console": [], "pageerr": ["server not responding"], "stuck": True}
                break
            pg = b.new_page(viewport={"width": 1500, "height": 1000})
            loaded, failed, cerr, perr, stuck = _visit(pg, f"{base}/{rk}", 5000, 45000)
            pg.close()
            if failed or cerr or perr or stuck:
                confirmed[route] = {"failed": failed[:6], "console": cerr[:3], "pageerr": perr[:3], "stuck": stuck}
        b.close()

    print(f"=== v3 crawl: {len(ROUTES)} routes | flagged in pass-1: {len(issues)} | "
          f"confirmed after retest: {len(confirmed)} ===")
    if not confirmed:
        print("  ✓ CLEAN — no dead endpoints, console errors, or broken routes "
              f"({len(issues) - len(confirmed)} pass-1 flags were crawl-speed false positives).")
        return 0
    lines = []
    for route, info in confirmed.items():
        print(f"  ✗ /{route}:")
        parts = []
        if info["failed"]: print("      failed API:", info["failed"]); parts.append(f"API {info['failed']}")
        if info["pageerr"]: print("      page errors:", info["pageerr"]); parts.append(f"err {info['pageerr']}")
        if info["console"]: print("      console errors:", info["console"]); parts.append("console errors")
        if info["stuck"]: print("      STUCK on loading"); parts.append("stuck")
        lines.append(f"/{route}: {'; '.join(parts)}")
    if args.telegram:
        _send_telegram("🕷 v3 dashboard crawl — issues on "
                       + f"{len(confirmed)} route(s):\n" + "\n".join(lines[:10]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
