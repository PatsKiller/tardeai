"""positions_store phase-3 reader batch #3 — the Home do-now held filter (operator 2026-10-22).

Operator reply, verbatim: "yes i approve 'approve all' (A–L)" — item G: "Home reads positions from the broker-synced
store (reader batch #3; you already said yes, this confirms it)". AGENTS.md §7A / §17: the grant is the
approved_readers batch 3 row in config/data_source_authority.json.

1. The registry records batch 3 with a complete operator approval, surfaces ["home"].
2. The switch admits "home" (and still not an unnamed caller).
3. A fresh store answer drops risk-snapshot positions the broker no longer holds from Home items.
4. Stale / empty / unreadable store -> holdings.json with an explicit fallback reason, never silently; a held probe
   that did not answer is labelled held_reader_unavailable.

Fakes only: no database, no network, no broker.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_data_source_authority as gate  # noqa: E402
from lib.data_broker import home_do_now as hdn  # noqa: E402
from lib.data_broker import watch_decision as wd  # noqa: E402
from lib.data_broker import watch_domains as wdom  # noqa: E402

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text(encoding="utf-8"))


def _snapshot():
    return {"computed_at": NOW.isoformat(), "portfolio": {"heat_pct": 1.0}, "positions": [
        {"symbol": "NAVN", "market_value": 13000.0, "account": "schwab_rollover_ira", "stop_price": None},
        {"symbol": "SCHD", "market_value": 137409.0, "account": "schwab_rollover_ira", "stop_price": None},
    ]}


def _held(source="positions_store.positions_current", stale=False, symbols=("SCHD",), fallback=None):
    return {"symbols": set(symbols), "source": source, "as_of": NOW.isoformat(), "stale": stale,
            "fallback_reason": fallback}


def test_registry_records_batch_3_for_home():
    row = next(d for d in AUTH["domains"] if d["domain"] == "positions_store")
    (r,) = [x for x in row["approved_readers"] if x["batch"] == 3]
    assert r["surfaces"] == ["home"] and r["tables"] == ["positions_current"]
    assert r["reader"] == "scripts/lib/data_broker/watch_domains.py::held_positions"
    a = r["approval"]
    assert a["approved_by"] == "operator" and a["approved_on"] == "2026-10-22"
    assert "approve all" in a["reference"] and "batch #3" in a["scope"]
    assert gate.check_readers(AUTH, gate._files()) == [] and gate.check_approvals(AUTH) == []


def test_switch_admits_home_and_not_an_unnamed_caller():
    held = wd.load_config()["held"]
    assert held["positions_store_reader"] is True and "home" in held["positions_store_reader_surfaces"]
    assert wdom.HOME_SURFACE == "home"
    assert wdom.store_reader_on(held, "home") is True
    assert wdom.store_reader_on(held, None) is False and wdom.store_reader_on(held, "advice_digest") is False


def test_fresh_store_drops_positions_the_broker_no_longer_holds():
    items, nums = hdn.rule_risk(_snapshot(), None, NOW, held=_held())
    titles = " | ".join(i["title"] for i in items)
    assert "NAVN" not in titles and "SCHD" in titles
    assert nums["not_held_per_store"] == ["NAVN"] and nums["positions_store_fallback_reason"] is None
    assert nums["positions_source"].startswith("positions_store.positions_current (reader batch #3")


def test_stale_store_falls_back_with_a_reason():
    items, nums = hdn.rule_risk(_snapshot(), None, NOW,
                                held=_held(source="holdings_accounts.holdings_json", fallback="positions_store_stale"))
    assert "NAVN" in " | ".join(i["title"] for i in items)
    assert nums["positions_store_fallback_reason"] == "positions_store_stale"
    assert "fallback: positions_store_stale" in nums["positions_source"] and nums["not_held_per_store"] == []


def test_stale_flag_on_store_answer_is_not_trusted():
    _items, nums = hdn.rule_risk(_snapshot(), None, NOW, held=_held(stale=True))
    assert nums["not_held_per_store"] == [] and nums["positions_store_fallback_reason"] == "holdings_stale"


def test_held_probe_that_did_not_answer_is_labelled():
    _items, nums = hdn.rule_risk(_snapshot(), None, NOW, held="unavailable")
    assert nums["positions_store_fallback_reason"] == "held_reader_unavailable"


def test_build_passes_the_held_probe_to_the_risk_rule():
    out = hdn.build({"risk": _snapshot, "held": _held}, now=NOW, timeout_s=5)
    numbers = out.get("numbers") or {}
    assert numbers.get("not_held_per_store") == ["NAVN"], out.get("numbers")
    assert out["sources"]["held"]["status"] == "OK"
