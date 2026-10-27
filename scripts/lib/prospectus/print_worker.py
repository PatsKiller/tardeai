"""Headless Chromium worker for the Prospectus print renders (run as a separate process by print_render).

Usage: ``python print_worker.py JOB.json`` (stdlib + playwright only; no repo imports, so it starts fast and a
crash or hang is contained to this process, which the caller kills on timeout).

JOB keys:
  html_path      the self-contained page to load (read from disk, injected with set_content; never navigated to)
  pdf_path       optional: write a print-to-PDF here (header/footer templates, paper, margins below)
  paper          "Letter" | "A4"
  margin         {"top": "0.8in", ...}
  header_html, footer_html   Chromium header/footer templates (pageNumber/totalPages spans)
  shots          [{"selector": "#chart-x svg", "path": "/out/x.png"}] element screenshots (charts as PNG)
  shot_width_px  CSS width the page is laid out at for screenshots
  scale          device scale factor for screenshots (2 = crisp in Word)
  full_page_png  optional: a full-page screenshot path (fidelity check only)
  chromium_args  extra launch flags

Safety: JavaScript is disabled, every network request is aborted (the page is self-contained: inline CSS, inline
SVG, data: images), and the browser is launched headless with a fresh temporary profile. Prints one JSON line.
"""
from __future__ import annotations

import json
import sys
import time


def run(job: dict) -> dict:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - optional dependency, worker-only

    html = open(job["html_path"], encoding="utf-8").read()
    out: dict = {"ok": True, "pdf": None, "shots": [], "blocked_requests": 0}
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=list(job.get("chromium_args") or []))
        try:
            ctx = browser.new_context(java_script_enabled=False, offline=True,
                                      viewport={"width": int(job.get("shot_width_px") or 816), "height": 1056},
                                      device_scale_factor=float(job.get("scale") or 2))

            def block(route):  # every request leaves nothing: the page is self-contained
                out["blocked_requests"] += 1
                route.abort()

            ctx.route("**/*", block)
            page = ctx.new_page()
            page.set_content(html, wait_until="load", timeout=int(job.get("timeout_ms") or 30000))
            for shot in job.get("shots") or []:
                el = page.query_selector(shot["selector"])
                if el is None:
                    continue
                el.screenshot(path=shot["path"], omit_background=False)
                out["shots"].append(shot["path"])
            if job.get("full_page_png"):
                page.screenshot(path=job["full_page_png"], full_page=True)
            if job.get("pdf_path"):
                page.emulate_media(media="print")
                page.pdf(path=job["pdf_path"], format=job.get("paper") or "Letter", print_background=True,
                         display_header_footer=bool(job.get("header_html") or job.get("footer_html")),
                         header_template=job.get("header_html") or "<span></span>",
                         footer_template=job.get("footer_html") or "<span></span>",
                         margin=job.get("margin") or {}, prefer_css_page_size=False)
                out["pdf"] = job["pdf_path"]
        finally:
            browser.close()
    out["seconds"] = round(time.time() - t0, 2)
    return out


def main(argv: list[str]) -> int:
    try:
        job = json.loads(open(argv[1], encoding="utf-8").read())
        res = run(job)
    except Exception as exc:  # noqa: BLE001 - the caller falls back and logs the reason
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}))
        return 1
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
