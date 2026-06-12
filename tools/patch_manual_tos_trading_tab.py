#!/usr/bin/env python3
"""Safely add Manual ToS as a TradingHub tab.

This intentionally performs small string-anchored edits only after verifying the
restored TradingHub shape. It does not touch broker code, routes, Schwab
transport, or validation scripts.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRADING = ROOT / "apps" / "command-center-v3" / "src" / "pages" / "TradingHub.tsx"

IMPORT_ANCHOR = "import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'\n"
IMPORT_ADD = "import ManualTosDesk from './ManualTosDesk'\n"
OLD_TABS = "const TABS = ['Trade AI', 'Open Trades', 'Proposals', 'Execution', 'Broker Recon', 'Scalp', 'ATM Controls', 'Broker Orders', 'Schwab Accounts'] as const"
NEW_TABS = "const TABS = ['Trade AI', 'Open Trades', 'Proposals', 'Manual ToS', 'Execution', 'Broker Recon', 'Scalp', 'ATM Controls', 'Broker Orders', 'Schwab Accounts'] as const"
RENDER_ANCHOR = "\n      {tab === 'ATM Controls' && <ATMControlPanel />}"
RENDER_ADD = "\n      {tab === 'Manual ToS' && <ManualTosDesk />}"


def main() -> int:
    text = TRADING.read_text()
    if "export default function TradingHub" not in text:
        raise SystemExit("ABORT: TradingHub function not found; refusing to patch")
    if "Broker Orders" not in text or "Schwab Accounts" not in text or "Trade AI" not in text:
        raise SystemExit("ABORT: expected restored TradingHub tabs not found; refusing to patch")
    if OLD_TABS not in text and "'Manual ToS'" not in text:
        raise SystemExit("ABORT: exact original TABS array not found; refusing to patch")

    changed = False
    if IMPORT_ADD not in text:
        if IMPORT_ANCHOR not in text:
            raise SystemExit("ABORT: import anchor not found; refusing to patch")
        text = text.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_ADD, 1)
        changed = True

    if OLD_TABS in text:
        text = text.replace(OLD_TABS, NEW_TABS, 1)
        changed = True

    if "tab === 'Manual ToS'" not in text:
        if RENDER_ANCHOR not in text:
            raise SystemExit("ABORT: render anchor not found; refusing to patch")
        text = text.replace(RENDER_ANCHOR, RENDER_ADD + RENDER_ANCHOR, 1)
        changed = True

    if not changed:
        print("Manual ToS tab already present; no changes made.")
        return 0

    TRADING.write_text(text)
    print("Patched TradingHub.tsx: Manual ToS tab added without removing existing tabs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
