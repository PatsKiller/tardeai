"""account_display — the one short human NAME per account (operator 2026-10-23).

"you need to actually put which account right here ... two SpaceX and two different accounts." /
"just a name, not the account numbers."  Shared by Command Center rows and Telegram notices; the API
(account_label, canonical_key, labels_map, label_row, label_rows, looks_like_number, multi_account_symbols,
UNLABELLED) is kept small and stable.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import account_display as ad  # noqa: E402

CONFIG = ROOT / "config" / "account_display_names.json"


def _cfg() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_config_names_are_names_only_and_unique():
    names = [v["name"] for v in _cfg()["names"].values()]
    assert names
    for n in names:
        assert not re.search(r"\d", n), f"account name carries digits: {n!r}"
        assert not ad.looks_like_number(n)
    assert len(set(names)) == len(names), "two accounts share a name"


def test_labels_for_live_keys():
    assert ad.account_label("schwab_rollover_ira") == "Schwab Rollover IRA"
    assert ad.account_label("schwab_taxable") == "Schwab Individual"
    assert ad.account_label("schwab_roth") == "Schwab Roth IRA"  # holdings.json alias
    assert ad.canonical_key("schwab_roth") == "schwab_roth_ira"
    assert ad.account_label("tradeai_automated") == "Alpaca Paper"
    assert ad.account_label("moomoo_taxable_live") == "moomoo Taxable"  # operator-confirmed 2026-10-23


def test_never_echoes_an_account_number():
    for raw in ("12345678", "...258", "··1234", "acct_9876543", "**4321"):
        assert ad.account_label(raw) == ad.UNLABELLED, raw
    assert ad.account_label("") == ad.UNLABELLED
    assert ad.account_label(None) == ad.UNLABELLED
    assert ad.account_label("fidelity_roth_ira") == "Fidelity Roth IRA"


def test_label_rows_copy_and_multi_account():
    rows = [
        {"symbol": "SPCX", "account": "schwab_taxable"},
        {"symbol": "SPCX", "account": "schwab_rollover_ira"},
        {"symbol": "SCHD", "account": "schwab_rollover_ira"},
        {"symbol": "X", "account": "...469"},
    ]
    out = ad.label_rows(rows)
    assert "account_label" not in rows[0]  # a cached input is never mutated
    assert [r["account_label"] for r in out[:3]] == ["Schwab Individual", "Schwab Rollover IRA", "Schwab Rollover IRA"]
    assert out[0]["account_id"] == "schwab_taxable"
    assert out[3]["account_label"] == ad.UNLABELLED
    assert ad.multi_account_symbols(out) == {"SPCX": ["schwab_taxable", "schwab_rollover_ira"]}
    assert ad.labels_map(["schwab_roth"]) == {"schwab_roth": "Schwab Roth IRA"}
