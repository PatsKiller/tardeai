"""JOURNAL_TABS_20261104: source contracts; actual SSR/browser checks live in the Node view test.

Browser geometry is run explicitly with `node src/lib/journalTabs.view.test.mjs --browser`.
These cheap shard checks make no claim about browser layout.
"""

import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/command-center-v3"


def test_phone_rule_targets_the_actual_route_layout_owner():
    css = (APP / "src/components/tradeinview/TradeInViewLayout.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    phone = re.search(r"@media\s*\(max-width:\s*420px\)\s*\{([\s\S]*?)\n\}", css)
    assert phone
    assert re.search(r"\.tradeinview-tabs\s*\{[^}]*flex-wrap:\s*wrap;[^}]*overflow-x:\s*visible;", phone[1])
    assert "TradeInViewPage" in (APP / "src/App.tsx").read_text(encoding="utf-8")


def test_route_navigation_keeps_all_five_sections():
    source = (APP / "src/lib/tradeInViewModel.ts").read_text(encoding="utf-8")
    literal = source.split("export const TRADE_TABS =", 1)[1].split("] as const", 1)[0] + "]"
    assert ast.literal_eval(literal.strip()) == [
        ["journeys", "Journeys"],
        ["calendar", "Calendar"],
        ["replay", "Replay"],
        ["history", "Holding history"],
        ["classic", "Journal (classic tabs)"],
    ]


def test_real_render_check_is_in_the_frontend_build():
    package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["build"].count("node scripts/run-tests.mjs") == 1
    # Discovery is the required build route; assert the real runner includes this SSR suite.
    listed = subprocess.run(
        ["node", "scripts/run-tests.mjs", "--list"],
        cwd=APP,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    inventory = json.loads(listed.stdout)
    assert inventory["run"].count("src/lib/journalTabs.view.test.mjs") == 1
    assert "src/lib/journalTabs.view.test.mjs" not in inventory["dormant"]
