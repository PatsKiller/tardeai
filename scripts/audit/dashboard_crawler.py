"""
Crawl every route in scripts/audit/routes.json against one or more base URLs.
Capture: full-page PNG, console messages, network failures, timing.
Output: docs/playwright/audit_<timestamp>.tgz (keeps last 3 runs).
"""
import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROUTES_FILE = Path(__file__).parent / "routes.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = str(PROJECT_ROOT / "docs" / "playwright")

DEFAULT_BASES = [
    "http://localhost:7777",
]

PER_ROUTE_TIMEOUT_MS = 25000
WAIT_AFTER_LOAD_MS = 1200
VIEWPORT = {"width": 1440, "height": 900}


def crawl_one(page, base_url, route, out_dir):
    url = base_url + route["href"]
    console_msgs = []
    network_failures = []

    def on_console(m):
        console_msgs.append({"type": m.type, "text": m.text[:500]})

    def on_reqfailed(r):
        network_failures.append({"url": r.url[:300], "failure": r.failure})

    page.on("console", on_console)
    page.on("requestfailed", on_reqfailed)

    start = time.time()
    status = "ok"
    error = None
    http_status = None
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=PER_ROUTE_TIMEOUT_MS)
        http_status = resp.status if resp else None

        if http_status == 401:
            status = "auth_required"
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                pass
            page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

            screenshot_path = out_dir / f"{route['name']}.png"
            page.screenshot(path=str(screenshot_path), full_page=True, timeout=15000)
    except PWTimeout as e:
        status = "timeout"
        error = str(e)[:300]
    except Exception as e:
        status = "error"
        error = f"{type(e).__name__}: {e}"[:300]

    elapsed_ms = int((time.time() - start) * 1000)

    page.remove_listener("console", on_console)
    page.remove_listener("requestfailed", on_reqfailed)

    return {
        "route": route["href"],
        "label": route["label"],
        "name": route["name"],
        "status": status,
        "http_status": http_status,
        "elapsed_ms": elapsed_ms,
        "error": error,
        "console_msgs": console_msgs[-20:],
        "console_error_count": sum(1 for m in console_msgs if m["type"] == "error"),
        "network_failure_count": len(network_failures),
        "network_failures": network_failures[:10],
    }


def crawl_base(base_url, routes, root_out):
    port = base_url.rsplit(":", 1)[-1]
    out_dir = root_out / port
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, ignore_https_errors=True)
        page = ctx.new_page()

        for i, route in enumerate(routes, 1):
            if route.get("skip_in_crawler"):
                print(f"[{port}] {i}/{len(routes)}  SKIP {route['href']} (side-effect)", flush=True)
                results.append({
                    "route": route["href"], "label": route["label"], "name": route["name"],
                    "status": "skipped", "http_status": None, "elapsed_ms": 0, "error": "skip_in_crawler",
                    "console_msgs": [], "console_error_count": 0,
                    "network_failure_count": 0, "network_failures": [],
                })
                continue

            print(f"[{port}] {i}/{len(routes)}  {route['href']}", flush=True)
            r = crawl_one(page, base_url, route, out_dir)
            results.append(r)

        ctx.close()
        browser.close()

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bases", nargs="*", default=DEFAULT_BASES,
                    help="Base URLs to crawl (default: localhost:7777)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="Parent dir for audit output")
    ap.add_argument("--routes", default=str(ROUTES_FILE),
                    help="Routes JSON file from extract_routes.py")
    args = ap.parse_args()

    # Always refresh routes from live sidebar before crawling
    sys.path.insert(0, str(Path(__file__).parent))
    from extract_routes import main as extract_routes_main
    print("Refreshing route list from live sidebar...")
    extract_routes_main()

    routes = json.loads(Path(args.routes).read_text())
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = Path(args.out)
    out_path.mkdir(parents=True, exist_ok=True)

    import tarfile

    all_summaries = []
    for base in args.bases:
        port = base.rsplit(":", 1)[-1]
        print(f"\n=== Crawling {base} ===")

        # Crawl into a temp directory
        tmp_dir = out_path / f"_tmp_{port}_{ts}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        port_dir = tmp_dir / port
        port_dir.mkdir(parents=True, exist_ok=True)
        results = crawl_base(base, routes, tmp_dir)

        totals = {
            "ok": sum(1 for r in results if r["status"] == "ok"),
            "timeout": sum(1 for r in results if r["status"] == "timeout"),
            "error": sum(1 for r in results if r["status"] == "error"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "console_error_routes": sum(1 for r in results if r["console_error_count"] > 0),
            "network_failure_routes": sum(1 for r in results if r["network_failure_count"] > 0),
        }

        manifest = {
            "run_id": ts,
            "started_at": datetime.now().isoformat(),
            "base": base,
            "port": port,
            "route_count": len(routes),
            "totals": totals,
            "results": results,
        }
        (port_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # Delete old tarballs for this port, then create new one
        for old in out_path.glob(f"audit_{port}_*.tgz"):
            old.unlink()
            print(f"  Deleted old: {old.name}")

        tarball = out_path / f"audit_{port}_{ts}.tgz"
        with tarfile.open(tarball, "w:gz") as tf:
            tf.add(tmp_dir, arcname=f"audit_{port}_{ts}")
        shutil.rmtree(tmp_dir)

        all_summaries.append((base, port, tarball, totals))

    print(f"\nDone.")
    for base, port, tarball, totals in all_summaries:
        print(f"  {base}: {tarball.name}")
        print(f"    {totals['ok']} ok / {totals['timeout']} timeout / {totals['error']} error / "
              f"{totals['skipped']} skipped / {totals['console_error_routes']} console errors")


if __name__ == "__main__":
    main()
