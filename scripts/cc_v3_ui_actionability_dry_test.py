#!/usr/bin/env python3
"""Dry test for CC v3 actionability sprint — static checks + live API contract."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V3_SRC = ROOT / "apps" / "command-center-v3" / "src"


def check_static_links() -> list[str]:
    fails = []
    text = ""
    for p in V3_SRC.rglob("*.tsx"):
        text += p.read_text(encoding="utf-8", errors="replace") + "\n"
    if re.search(r"['\"]/v2/inbox['\"]", text):
        fails.append("v3 src still references dead dashboard /v2/inbox")
    # bare watchlist links (redirect routes in App.tsx are OK)
    for m in re.finditer(r"['\"](/v3/watchlist[^'\"]*)['\"]", text):
        if "Navigate" not in text[max(0, m.start() - 200):m.start()]:
            fails.append(f"stale watchlist path: {m.group(1)}")
    if "snapshot only" in text:
        fails.append('Home still says "snapshot only"')
    strat = (V3_SRC / "pages" / "StrategyHub.tsx").read_text()
    if "'Backtest'" in strat and "const TABS" in strat and "'Backtest'" in strat.split("const TABS")[1].split("]")[0]:
        fails.append("StrategyHub TABS still includes Backtest")
    if "IntelligenceRotationTab" in (V3_SRC / "pages" / "IntelligenceHub.tsx").read_text():
        fails.append("IntelligenceHub still imports Rotation tab")
    if "'Changelog'" in (V3_SRC / "pages" / "RotationIntelligence.tsx").read_text():
        fails.append("Rotation still uses Changelog tab label")
    if "OperatorInboxPanel" not in (V3_SRC / "pages" / "HomeHub.tsx").read_text():
        fails.append("HomeHub missing OperatorInboxPanel")
    if "_CTA_BY_TYPE" not in (ROOT / "scripts" / "health_agent.py").read_text():
        fails.append("health_agent missing cta attachment")
    return fails


def run_sub(script: str) -> tuple[int, str]:
    py = ROOT / ".venv" / "bin" / "python"
    if not py.exists():
        py = Path(sys.executable)
    r = subprocess.run([str(py), str(ROOT / script)], capture_output=True, text=True, cwd=ROOT, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out[-2000:]


def main() -> int:
    print("=== CC v3 actionability dry test ===\n")
    static_fails = check_static_links()
    for f in static_fails:
        print(f"STATIC FAIL: {f}")
    if not static_fails:
        print("STATIC OK — link/tab conventions")

    print("\n--- hub contract ---")
    code, out = run_sub("tests/test_cc_v3_hub_contract.py")
    print(out)
    contract_ok = code == 0

    print("\n--- inbox API ---")
    code2, out2 = run_sub("scripts/cc_v3_site_health_probe.py")
    inbox_ok = "/api/v2/inbox" in out2 or True  # probe lists all; check separately
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:7777/api/v2/inbox", timeout=15) as resp:
            body = resp.read(50000).decode()
            inbox_ok = resp.status == 200 and '"items"' in body
            print(f"INBOX API {'OK' if inbox_ok else 'FAIL'}")
    except Exception as e:
        inbox_ok = False
        print(f"INBOX API FAIL: {e}")

    ok = not static_fails and contract_ok and inbox_ok
    print(f"\n{'PASS' if ok else 'FAIL'} dry test")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())