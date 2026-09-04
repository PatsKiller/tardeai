#!/usr/bin/env python3
"""Run the browser/state matrix and write the evidence.

  python3 -m scripts.cc_browser_matrix --out evidence/whole_site/browser_matrix

Starts the hermetic server over the REAL built bundle, drives Chromium through
every registered route x forced state, and writes:

  BROWSER_STATE_MATRIX.csv    one row per (route, state) with the rendered verdict
  BROWSER_STATE_MATRIX.json   full observations
  MATRIX_SUMMARY.md           counts, failures, and the no-mutation proof

Safety: the server refuses every non-GET, so a control that fires during page load
is recorded as a refused mutation attempt instead of performing one. Nothing here
can reach production.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.cc_browser_matrix import server as srv  # noqa: E402
from scripts.cc_browser_matrix import states as S  # noqa: E402

APP = ROOT / "apps" / "command-center-v3"
DIST = APP / "dist"
DRIVER = APP / "e2e" / "browser_state_matrix_driver.mjs"
ROUTE_RE = re.compile(r'path="([^"]+)"')

#: Concrete URLs for parameterised routes, so a :param route is actually rendered.
PARAM_SAMPLES = {
    "go/order/:intentId": "go/order/matrix-intent-1",
    "go/proposal/:proposalId": "go/proposal/matrix-proposal-1",
    "watch/intelligence/:symbol": "watch/intelligence/AAPL",
}


def registered_routes() -> list[str]:
    app = APP / "src" / "App.tsx"
    return sorted({r for r in ROUTE_RE.findall(app.read_text()) if r not in ("/*", "*")})


def route_url(route: str) -> str:
    concrete = PARAM_SAMPLES.get(route, route)
    return "/v3/" + concrete.lstrip("/")


def load_fixtures() -> dict:
    """POPULATED bodies for the endpoints the shell always reads."""
    f = ROOT / "fixtures" / "cc_runtime" / "positive"
    out: dict[str, object] = {}
    mapping = {
        "overview.json": "/api/v2/overview",
        "risk.json": "/api/v2/risk",
        "trade_ai_summary.json": "/api/v2/trade-ai/summary",
        "risk_regime_latest.json": "/api/v2/risk-regime/latest",
        "paper_trade_readiness.json": "/api/v2/paper-trade-readiness",
        "health.json": "/api/health",
        "build_meta.json": "/v3/build-meta.json",
    }
    for name, path in mapping.items():
        p = f / name
        if p.is_file():
            try:
                out[path] = json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                pass
    return out


def build_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "evidence" / "whole_site" / "browser_matrix"))
    ap.add_argument("--states", nargs="*", default=list(S.STATES))
    ap.add_argument("--routes", nargs="*", default=None)
    ap.add_argument("--settle-ms", type=int, default=1500)
    args = ap.parse_args(argv)

    if not DIST.is_dir() or not (DIST / "index.html").is_file():
        print("BLOCKED: no built bundle at apps/command-center-v3/dist — run `npm run build` first", file=sys.stderr)
        return 2
    if not DRIVER.is_file():
        print(f"BLOCKED: driver missing at {DRIVER}", file=sys.stderr)
        return 2

    routes = args.routes or registered_routes()
    # Absolute: the driver runs with cwd=apps/command-center-v3, so a relative
    # --out would land inside the app directory (or fail outright).
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    httpd, st, base = srv.start(DIST, load_fixtures(), build_sha())
    all_rows: list[dict] = []
    mutation_attempts: list[dict] = []
    try:
        for state in args.states:
            st.reset(state)
            plan = {
                "steps": [{"route": r, "url": route_url(r), "state": state, "settleMs": args.settle_ms} for r in routes]
            }
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(plan, fh)
                plan_path = fh.name
            res_path = str(out_dir / f"raw_{state}.json")
            print(f"[matrix] state={state} routes={len(routes)}", file=sys.stderr)
            rc = subprocess.call(
                ["node", str(DRIVER), base, plan_path, res_path],
                cwd=str(APP),
            )
            if rc != 0:
                print(f"driver exited {rc} for state {state}", file=sys.stderr)
                return rc
            data = json.loads(Path(res_path).read_text())
            for row in data["results"]:
                row["requirement"] = S.REQUIREMENT.get(state, "")
                all_rows.append(row)
            mutation_attempts.extend(st.mutation_attempts)
    finally:
        httpd.shutdown()

    # ── evidence ────────────────────────────────────────────────────────────
    cols = [
        "state",
        "route",
        "url",
        "verdict",
        "elementCount",
        "textLength",
        "apiRequestCount",
        "surfaceMode",
        "bannerDismissible",
        "consoleErrorCount",
        "requirement",
    ]
    with (out_dir / "BROWSER_STATE_MATRIX.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)
    (out_dir / "BROWSER_STATE_MATRIX.json").write_text(json.dumps(all_rows, indent=1))

    verdicts: dict[str, int] = {}
    for r in all_rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    failures = [r for r in all_rows if r["verdict"] in ("shell_only", "crashed", "nav_error")]
    page_mutations = [r for r in all_rows if r["mutatingRequests"]]

    summary = {
        "schema": "BrowserStateMatrixSummary@v1",
        "authority": "READ_ONLY",
        "base_url": base,
        "bundle": str(DIST),
        "build_sha": build_sha(),
        "route_count": len(routes),
        "state_count": len(args.states),
        "cell_count": len(all_rows),
        "verdicts": dict(sorted(verdicts.items())),
        "shell_only_or_worse": len(failures),
        "pages_issuing_non_get_on_load": len(page_mutations),
        "server_refused_mutation_attempts": len(mutation_attempts),
        "mutation_attempts": mutation_attempts[:50],
        "no_write_environment": True,
    }
    (out_dir / "MATRIX_SUMMARY.json").write_text(json.dumps(summary, indent=2))

    lines = [
        "# BROWSER_STATE_MATRIX",
        "",
        f"- bundle: `{DIST}` @ `{summary['build_sha']}`",
        f"- routes: {summary['route_count']} · states: {summary['state_count']} · cells: {summary['cell_count']}",
        f"- verdicts: {summary['verdicts']}",
        f"- shell-only / crashed / nav-error: **{summary['shell_only_or_worse']}**",
        f"- pages issuing a non-GET during load: **{summary['pages_issuing_non_get_on_load']}**",
        f"- mutation attempts refused by the server: **{summary['server_refused_mutation_attempts']}**",
        "",
        "A route returning only the SPA shell is not a pass; `rendered` means hydrated,",
        "route-specific content was measured in a real Chromium page.",
        "",
    ]
    if failures:
        lines += [
            "## Cells that did not render",
            "",
            "| state | route | verdict | elements | text |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {r['state']} | {r['route']} | {r['verdict']} | {r['elementCount']} | {r['textLength']} |"
            for r in failures[:80]
        ]
        lines.append("")
    (out_dir / "MATRIX_SUMMARY.md").write_text("\n".join(lines))

    print(json.dumps({k: v for k, v in summary.items() if k != "mutation_attempts"}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
