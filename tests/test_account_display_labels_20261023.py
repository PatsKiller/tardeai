"""Account name on every Command Center position / trade row (operator 2026-10-23).

"you need to actually put which account right here. Like, for example, there are two SpaceX and two
different accounts." … "just a name, not the account numbers."
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
TS_LIB = ROOT / "apps" / "command-center-v3" / "src" / "lib" / "accountLabels.ts"


def _cfg() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_config_names_are_names_only():
    names = [v["name"] for v in _cfg()["names"].values()]
    assert names, "no account names configured"
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


def test_never_echoes_an_account_number():
    for raw in ("12345678", "...258", "··1234", "acct_9876543"):
        assert ad.account_label(raw) == ad.UNLABELLED, raw
    assert ad.account_label("") == ad.UNLABELLED
    assert ad.account_label("fidelity_roth_ira") == "Fidelity Roth IRA"


def test_label_row_and_multi_account():
    rows = ad.label_rows(
        [
            {"symbol": "SPCX", "account": "schwab_taxable", "day_change": 507.0},
            {"symbol": "SPCX", "account": "schwab_rollover_ira", "day_change": 1488.0},
            {"symbol": "SCHD", "account": "schwab_rollover_ira", "day_change": -850.0},
            {"symbol": "X", "account": "...469"},
        ]
    )
    assert [r["account_label"] for r in rows[:3]] == ["Schwab Individual", "Schwab Rollover IRA", "Schwab Rollover IRA"]
    assert rows[0]["account_id"] == "schwab_taxable"
    assert rows[3]["account_label"] == ad.UNLABELLED
    assert ad.multi_account_symbols(rows) == {"SPCX": ["schwab_taxable", "schwab_rollover_ira"]}


def test_ts_map_mirrors_config():
    src = TS_LIB.read_text(encoding="utf-8")
    block = re.search(r"ACCOUNT_NAMES: Record<string, string> = \{(.*?)\n\}", src, re.S).group(1)
    ts = dict(re.findall(r"(\w+): '([^']+)'", block))
    assert ts == {k: v["name"] for k, v in _cfg()["names"].items()}
    ablock = re.search(r"ACCOUNT_ALIASES: Record<string, string> = \{(.*?)\n\}", src, re.S).group(1)
    assert dict(re.findall(r"(\w+): '([^']+)'", ablock)) == _cfg()["aliases"]


def test_overview_top_movers_carry_account():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('"top_movers": [\n            {\n                "symbol": m.get("symbol")')
    block = src[i : i + 1200]
    assert '"account_id": _acct_disp.canonical_key' in block
    assert '"account_label": _acct_disp.account_label' in block
