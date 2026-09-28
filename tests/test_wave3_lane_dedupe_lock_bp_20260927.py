"""Wave 3 (operator 2026-09-27): (a) the researched-watchlist options lane reads catalysts from
catalyst_events instead of two columns watchlist_items never had, and a failing lane is logged,
not hidden; (b) a rejected CIO review releases the governed lane's dedupe mark; (c) a manual
lifecycle run takes the scheduler's lock; (d) submit re-reads buying power for place_order's
own readiness pass. Hermetic."""
from __future__ import annotations

import ast
import fcntl
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]


def test_research_lane_query_uses_catalyst_events_and_logs_failure(capsys, monkeypatch):
    import options_engine as oe
    src = (ROOT / "scripts" / "options_engine.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_researched_watchlist_rows")
    body = "\n".join(l for l in ast.get_source_segment(src, fn).splitlines() if not l.strip().startswith("#"))
    assert "wi.catalyst_headline" not in body and "wi.catalyst_at" not in body
    assert "catalyst_events" in body and "LATERAL" in body
    # a failing read is named, not swallowed
    import db_adapter
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(db_adapter, "_execute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("column does not exist")))
    oe.INCOME_SCREEN_DROPS.clear()
    assert oe._researched_watchlist_rows() == []
    assert "researched-watchlist lane unavailable" in capsys.readouterr().err
    assert oe.INCOME_SCREEN_DROPS and oe.INCOME_SCREEN_DROPS[0]["reason"] == "RESEARCH_LANE_UNAVAILABLE"
    # and rows come through with the catalyst from the lateral join
    monkeypatch.setattr(db_adapter, "_execute", lambda *a, **k: [{"symbol": "DELL", "card_rec": "BUY", "synth_rec": None,
                                                                   "hermes_composite_score": 0.7, "catalyst_headline": "8-K Item 2.02",
                                                                   "catalyst_at": "2026-09-01", "research_card_at": None, "synthesis_at": None}])
    rows = oe._researched_watchlist_rows()
    assert rows[0]["symbol"] == "DELL" and rows[0]["catalyst"] == "8-K Item 2.02" and rows[0]["source_lanes"] == ["watchlist"]


def test_rejected_review_releases_the_lane_dedupe_mark(tmp_path, monkeypatch):
    import importlib
    from scripts.lib import options_cio_review as ocr
    # the review resolves the lane as lib.agent_flash_governance (scripts/ on sys.path); patch
    # every loaded alias of the module so the test sees one dedupe store
    mods = [importlib.import_module(n) for n in ("lib.agent_flash_governance", "scripts.lib.agent_flash_governance")]
    store = {}
    for m in mods:
        monkeypatch.setattr(m, "_load_dedupe", lambda: dict(store))
        monkeypatch.setattr(m, "_save_dedupe", lambda c: (store.clear(), store.update(c)))
        m._DEDUPE_CACHE.clear()
    afg = mods[0]
    afg.mark_completed("ek1")
    assert afg.already_completed("ek1") is True
    P = {"symbol": "DELL", "strategy": "credit_spread", "option_strategy_guid": "g", "strike": 520.0, "premium": 6.35,
         "options_thesis": {"pin": "opt_g@v1"}}
    r = ocr.review(dict(P), mode="live", llm_fn=lambda _p: {"success": True, "response": "not json", "evidence_hash": "ek1"})
    assert r["status"] == "INVALID" and r["lane_completion_released"] is True
    assert afg.already_completed("ek1") is False
    assert afg.release_completed("") is False and afg.release_completed("never-seen") is False


def test_manual_lifecycle_run_yields_to_the_scheduler_lock(tmp_path):
    lock = tmp_path / "lifecycle.lock"
    holder = open(lock, "a+")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "options_thesis_lifecycle.py"),
                           "--lock", str(lock), "--proposals", str(tmp_path / "missing.json")],
                          capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert proc.returncode == 0 and out["skipped"].startswith("lifecycle lock held")
    holder.close()


def test_submit_rereads_buying_power_for_place_orders_readiness(monkeypatch):
    from brokers import options_order_pilot as oop
    import schwab_transport
    seen = {}
    monkeypatch.setattr(schwab_transport, "place_order", lambda acct, spec, intent, kind="options": seen.update(
        ev=dict(intent.meta.signal_evidence)) or {"status": "blocked_by_test"})
    p = {"symbol": "DELL", "underlying": "DELL", "strategy": "credit_spread", "account": "rollover", "option_type": "put",
         "short_strike": 520.0, "long_strike": 500.0, "strike": 520.0, "expiration": "2026-11-20", "contracts": 1,
         "premium": 6.35, "id": "x"}
    intent = oop.build_intent("rollover", p, held_qty=0, buying_power=1.0, buying_power_as_of="2026-09-27T00:00:00+00:00")
    oop.submit("rollover", oop.order_from_intent(intent), intent, buying_power_reader=lambda k: {"status": "active", "buying_power": 77_000.0})
    assert seen["ev"]["buying_power"] == 77_000.0 and seen["ev"]["buying_power_read_at"] == "submit" and seen["ev"]["buying_power_as_of"] != "2026-09-27T00:00:00+00:00"
    oop.submit("rollover", oop.order_from_intent(intent), intent, buying_power_reader=lambda k: {"status": "degraded"})
    assert seen["ev"]["buying_power"] is None   # a failed read leaves it unknown: readiness fails closed
