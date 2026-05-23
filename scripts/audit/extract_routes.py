"""Extract /v2/* routes from the live Command Center sidebar.
Saves to scripts/audit/routes.json — used by the crawler.
"""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROUTES_FILE = Path(__file__).parent / "routes.json"
COMMAND_URL = "http://localhost:7777/v2/command"


def main():
    routes = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(COMMAND_URL, wait_until="networkidle", timeout=30000)

        # All sidebar anchors
        anchors = page.eval_on_selector_all(
            "a[href^='/v2/']",
            "els => els.map(e => ({href: e.getAttribute('href'), text: e.textContent.trim()}))"
        )

        seen = set()
        for a in anchors:
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            routes.append({
                "href": href,
                "label": a["text"],
                "name": re.sub(r"[^a-z0-9]+", "_", href.replace("/v2/", "").lower()).strip("_") or "root",
            })

        browser.close()

    # Add per-agent dashboards explicitly
    agents = ["steph", "maria", "risk_agent", "tax_agent", "alex", "aegis", "iris",
              "social_scalp", "scalp_critic", "maria_research"]
    for a in agents:
        href = f"/v2/agent-dashboard/{a}"
        if href not in {r["href"] for r in routes}:
            routes.append({
                "href": href,
                "label": f"Agent: {a}",
                "name": f"agent_dashboard_{a}",
            })

    # Known tab-variant pages
    tab_variants = [
        {"href": "/v2/pipeline?tab=stage-controller", "label": "Pipeline - Stage Controller",
         "name": "pipeline_stage_controller"},
    ]
    for tv in tab_variants:
        if tv["href"] not in {r["href"] for r in routes}:
            routes.append(tv)

    # Routes that trigger side effects — skip during crawl
    SKIP_ROUTES = {"/v2/morning-brief", "/v2/bot-morning-brief"}
    for r in routes:
        if r["href"] in SKIP_ROUTES:
            r["skip_in_crawler"] = True

    ROUTES_FILE.write_text(json.dumps(routes, indent=2))
    print(f"Wrote {len(routes)} routes to {ROUTES_FILE}")


if __name__ == "__main__":
    main()
