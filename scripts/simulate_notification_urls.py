#!/usr/bin/env python3
"""Simulate notification URL rewriting for ALERT-URL-FQDN-1."""
import argparse, json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

CASES = [
    ("Trade opened: CMCSA 120sh @ $24.97\nDashboard: http://192.168.50.16:7777/v2/automated-trade-journal", "rewrite"),
    ("Stop hit: GCTS stopped @ $1.37\nDetails: http://localhost:7777/v2/paper-proposals", "rewrite"),
    ("Full report: http://192.168.50.16:7777/reports/monthly/monthly_2026-05.html", "rewrite"),
    ("Full detail: http://192.168.50.16:7777/v2/alerts", "rewrite"),
    ("Dashboard: 192.168.50.16:7777/v2/morning-brief", "rewrite"),
    ("View: http://100.66.120.124:7777/v2/journal", "rewrite"),
    ("https://ms01-openclaw.tail163d14.ts.net/v2/overview", "already_fqdn"),
    ("Internal health check to localhost:7777 — this is code, not user message", "internal"),
]

BANNED = ["192.168.50.16", "localhost:7777", "127.0.0.1:7777", "100.66.120.124"]
FQDN = "ms01-openclaw.tail163d14.ts.net"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    from notification_url_builder import publicize_message

    results = []
    passed = failed = 0

    for msg, expected in CASES:
        rewritten = publicize_message(msg)
        has_banned = any(b in rewritten for b in BANNED)
        has_fqdn = FQDN in rewritten

        if expected == "rewrite":
            ok = has_fqdn and not has_banned
        elif expected == "already_fqdn":
            ok = has_fqdn
        else:
            ok = True  # internal — no requirement

        if ok: passed += 1
        else: failed += 1
        results.append({"input": msg[:60], "output": rewritten[:80], "expected": expected, "pass": ok})
        if args.verbose:
            print(f"  {'PASS' if ok else 'FAIL'} [{expected}] {msg[:50]}...")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump({"passed": passed, "failed": failed, "results": results}, f, indent=2)
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_md, "w") as f:
            f.write(f"# Notification URL Simulation\n\nPassed: {passed}/{len(CASES)}\n\n")
            for r in results:
                f.write(f"- {'PASS' if r['pass'] else 'FAIL'} [{r['expected']}] {r['input']}\n")

    print(f"\nSimulation: {passed}/{len(CASES)} passed, {failed} failed")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
