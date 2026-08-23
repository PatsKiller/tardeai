"""R1 — source-hash skip gate, no local judgment LLM, reentry T1-WATCH."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_source_index import (
    RESEARCH_EXECUTED,
    RESEARCH_TRIGGERED,
    SKIP_FRESH,
    SKIP_UNCHANGED,
    compute_hash,
    decide,
    freshness_days_for,
    source_id_for_symbol,
    source_payload_for_symbol,
    upsert_row,
)
from scripts.lib.research_skip_ledger import append_entry, summarize_rates
from scripts.lib.holdings_universe import is_held_equity_ticker
from scripts.research_scheduler import (
    TIER_SLA,
    _is_symbol,
    allow_local_research_llm,
    lanes_for,
    load_reentry_ready_near_symbols,
    load_universe,
    maybe_dispatch_metered,
    result_is_budget_throttle,
    skip_gate_enabled,
)


def _cio_env(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    idx = tmp_path / "research_source_index.json"
    led = tmp_path / "research_skip_ledger.jsonl"
    monkeypatch.setenv("RESEARCH_SOURCE_INDEX_PATH", str(idx))
    monkeypatch.setenv("RESEARCH_SKIP_LEDGER_PATH", str(led))
    return idx, led


def _seed_match(sym="SCHD", tier="T0-HOLD", *, catalyst=False, days=30, extra=None):
    payload = source_payload_for_symbol(
        sym, tier=tier, catalyst=catalyst, thesis_version=None, source_as_of=None, extra=extra,
    )
    h = compute_hash(payload)
    sid = source_id_for_symbol(sym, "deepseek")
    now = datetime.now(timezone.utc)
    upsert_row(
        sid,
        content_hash=h,
        last_researched_at=now.isoformat(),
        fresh_until=(now + timedelta(days=days)).isoformat(),
        now=now,
        tier=tier,
        symbol=sym,
    )
    return sid, h, payload


def test_byte_identical_payload_same_hash():
    a = source_payload_for_symbol(
        "SCHD", tier="T0-HOLD", catalyst=False, thesis_version=1, source_as_of="2026-08-01",
    )
    b = source_payload_for_symbol(
        "SCHD", tier="T0-HOLD", catalyst=False, thesis_version=1, source_as_of="2026-08-01",
    )
    assert compute_hash(a) == compute_hash(b)
    # Recommendation/confidence must not enter the skip hash even if stuffed into extra.
    leaked = source_payload_for_symbol(
        "SCHD", tier="T0-HOLD", catalyst=False, thesis_version=1, source_as_of="2026-08-01",
        extra={"recommendation": "BUY", "confidence": 0.9, "note": "keep"},
    )
    assert "recommendation" not in json.dumps(leaked)
    assert leaked["extra"] == {"note": "keep"}


def test_skip_unchanged_does_not_call_metered(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKIP_GATE", "1")
    _cio_env(monkeypatch, tmp_path)
    _seed_match()
    called: list = []

    def fake_dispatch(*a, **k):
        called.append((a, k))
        return {"ok": True, "tail": "status=sent"}

    import scripts.research_scheduler as rs
    monkeypatch.setattr(rs, "dispatch", fake_dispatch)
    out = maybe_dispatch_metered("SCHD", "deepseek", "T0-HOLD", True, catalyst=False)
    assert out["code"] == SKIP_UNCHANGED
    assert out["dispatched"] is False
    assert called == []
    rows = [json.loads(l) for l in (tmp_path / "research_skip_ledger.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["code"] == SKIP_UNCHANGED
    assert rows[0]["metered"] is True
    assert rows[0]["authority"] == "READ_ONLY_ADVISORY"
    assert rows[0]["symbol"] == "SCHD"
    assert rows[0]["lane"] == "deepseek"


def test_gate_off_dispatches_even_if_hash_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKIP_GATE", "0")
    _cio_env(monkeypatch, tmp_path)
    _seed_match()
    called: list = []

    def fake_dispatch(*a, **k):
        called.append(a[1] if a else k.get("lane"))
        return {"ok": True, "tail": "status=sent"}

    import scripts.research_scheduler as rs
    monkeypatch.setattr(rs, "dispatch", fake_dispatch)
    assert skip_gate_enabled() is False
    out = maybe_dispatch_metered("SCHD", "deepseek", "T0-HOLD", True, catalyst=False)
    assert out["dispatched"] is True
    assert called == ["deepseek"]
    # No ledger required when the gate is off.
    led = tmp_path / "research_skip_ledger.jsonl"
    assert not led.exists() or led.read_text().strip() == ""


def test_catalyst_triggered_dispatches_even_if_hash_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKIP_GATE", "1")
    _cio_env(monkeypatch, tmp_path)
    # Seed with catalyst=True so the source hash still matches the triggered call.
    _seed_match(catalyst=True)
    called: list = []

    def fake_dispatch(*a, **k):
        called.append(True)
        return {"ok": True, "tail": "status=sent"}

    import scripts.research_scheduler as rs
    monkeypatch.setattr(rs, "dispatch", fake_dispatch)
    out = maybe_dispatch_metered("SCHD", "deepseek", "T0-HOLD", True, catalyst=True)
    assert out["code"] == RESEARCH_TRIGGERED
    assert out["dispatched"] is True
    assert called == [True]
    rows = [json.loads(l) for l in (tmp_path / "research_skip_ledger.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["code"] == RESEARCH_TRIGGERED


def test_decide_stale_hash_match_is_executed(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKIP_GATE", "1")
    idx, _ = _cio_env(monkeypatch, tmp_path)
    payload = source_payload_for_symbol(
        "JEPI", tier="T0-HOLD", catalyst=False, thesis_version=None, source_as_of=None,
    )
    h = compute_hash(payload)
    sid = source_id_for_symbol("JEPI", "deepseek")
    past = datetime.now(timezone.utc) - timedelta(days=40)
    upsert_row(
        sid,
        content_hash=h,
        last_researched_at=past.isoformat(),
        fresh_until=(past + timedelta(days=14)).isoformat(),
        path=idx,
        now=past,
        tier="T0-HOLD",
        symbol="JEPI",
    )
    assert decide(sid, h, triggered=False, now=datetime.now(timezone.utc), path=idx) == RESEARCH_EXECUTED


def test_hours_window_is_skip_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKIP_GATE", "1")
    _cio_env(monkeypatch, tmp_path)
    called: list = []

    def fake_dispatch(*a, **k):
        called.append(True)
        return {"ok": True, "tail": "status=sent"}

    import scripts.research_scheduler as rs
    monkeypatch.setattr(rs, "dispatch", fake_dispatch)
    out = maybe_dispatch_metered(
        "SCHD", "deepseek", "T0-HOLD", True, catalyst=False, hours_window_fresh=True,
    )
    assert out["code"] == SKIP_FRESH
    assert out["dispatched"] is False
    assert called == []


def test_cash_is_not_a_research_ticker():
    assert not is_held_equity_ticker("CASH")
    assert not is_held_equity_ticker("SPAXX")
    assert not _is_symbol("CASH")
    assert not _is_symbol("USD")
    assert _is_symbol("JEPI")
    assert _is_symbol("AVAV")


def test_reentry_ready_near_are_t1_watch_wait_excluded(tmp_path, monkeypatch):
    import scripts.research_scheduler as rs

    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    desk = {
        "ok": True,
        "rows": [
            {"symbol": "AVAV", "intel": {"state": "READY TO REVIEW"}},
            {"symbol": "AXTI", "intel": {"state": "NEAR ENTRY"}},
            {"symbol": "DHX", "status": "READY"},
            {"symbol": "MOGU", "intel": {"state": "NEAR"}},
            {"symbol": "WAITX", "intel": {"state": "WAIT"}},
            {"symbol": "OVSX", "intel": {"state": "OVERSOLD REVIEW"}},
            {"symbol": "HELDX", "intel": {"state": "CURRENTLY HELD"}, "held": True},
            {"symbol": "CASH", "intel": {"state": "READY TO REVIEW"}},
        ],
    }
    (runtime / "reentry_decision_desk_latest.json").write_text(json.dumps(desk), encoding="utf-8")
    monkeypatch.setattr(rs, "_q", lambda *a, **k: [])
    monkeypatch.setattr(rs, "ROOT", tmp_path)

    ready = load_reentry_ready_near_symbols(root=tmp_path)
    assert "AVAV" in ready
    assert "AXTI" in ready
    assert "DHX" in ready
    assert "MOGU" in ready
    assert "WAITX" not in ready
    assert "OVSX" not in ready
    assert "HELDX" not in ready
    assert "CASH" not in ready

    uni = load_universe(root=tmp_path)
    assert uni["AVAV"]["tier"] == "T1-WATCH"
    assert uni["AXTI"]["tier"] == "T1-WATCH"
    assert uni["DHX"]["tier"] == "T1-WATCH"
    assert uni["MOGU"]["tier"] == "T1-WATCH"
    assert uni["AVAV"].get("reentry_ready_near") is True
    assert "WAITX" not in uni
    assert "OVSX" not in uni
    assert "HELDX" not in uni
    assert "CASH" not in uni
    assert "T1-WATCH" in {v["tier"] for v in uni.values()}
    assert "T1-WAIT" not in {v["tier"] for v in uni.values()}


def test_missing_reentry_file_fail_soft(tmp_path, monkeypatch):
    import scripts.research_scheduler as rs
    monkeypatch.setattr(rs, "_q", lambda *a, **k: [])
    assert load_reentry_ready_near_symbols(root=tmp_path) == []
    uni = load_universe(root=tmp_path)
    assert uni == {}


def test_t3_deepseek_listed_but_catalyst_gated():
    """T3 may call DeepSeek on catalyst; the 14d sweep is not the safety net."""
    assert "deepseek" in TIER_SLA["T3-COLD"][2]
    src = (ROOT / "scripts/research_scheduler.py").read_text()
    assert 'if tier in ("T2-INCUB", "T3-COLD") and not catalyst:' in src
    assert "ext_lanes = []" in src
    assert "DEPRECATED 2026-08-22: 14d T3 sweep" in src


def test_allow_local_research_llm_default_off(monkeypatch):
    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    assert allow_local_research_llm() is False
    t0 = lanes_for("T0-HOLD")
    assert "local-gemma" not in t0
    assert "internal-deep" not in t0
    assert "deepseek" in t0
    assert "local-gemma" not in lanes_for("T1-WATCH")
    monkeypatch.setenv("RESEARCH_ALLOW_LOCAL_LLM", "1")
    assert allow_local_research_llm() is True
    assert "local-gemma" in lanes_for("T0-HOLD")
    assert "internal-deep" in lanes_for("T0-HOLD")


def test_run_dry_does_not_use_local_lanes(monkeypatch):
    import scripts.research_scheduler as rs

    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    monkeypatch.setenv("RESEARCH_SKIP_GATE", "0")
    monkeypatch.setattr(rs, "load_universe", lambda **k: {"SCHD": {"tier": "T0-HOLD"}})
    monkeypatch.setattr(rs, "catalyst_signals", lambda: {})
    monkeypatch.setattr(rs, "load_high_value_thesis_gaps", lambda *a, **k: {})
    called: list[str] = []

    def fake_dispatch(sym, lane, tier, apply, **k):
        called.append(lane)
        return {"ok": True, "tail": "would enqueue"}

    monkeypatch.setattr(rs, "dispatch", fake_dispatch)
    rs.run("holdings", apply=False, budget=5)
    assert "local-gemma" not in called
    assert "internal-deep" not in called
    assert "maria" not in called


def test_run_apply_skip_gate_blocks_metered(tmp_path, monkeypatch):
    import scripts.research_scheduler as rs

    monkeypatch.setenv("RESEARCH_SKIP_GATE", "1")
    monkeypatch.delenv("RESEARCH_ALLOW_LOCAL_LLM", raising=False)
    _cio_env(monkeypatch, tmp_path)
    _seed_match()
    monkeypatch.setattr(rs, "load_universe", lambda **k: {"SCHD": {"tier": "T0-HOLD"}})
    monkeypatch.setattr(rs, "catalyst_signals", lambda: {})
    monkeypatch.setattr(rs, "load_high_value_thesis_gaps", lambda *a, **k: {})
    monkeypatch.setattr(rs, "surface_holding_event", lambda *a, **k: False)
    called: list = []

    def fake_dispatch(*a, **k):
        called.append(a)
        return {"ok": True, "tail": "status=sent"}

    monkeypatch.setattr(rs, "dispatch", fake_dispatch)
    rs.run("holdings", apply=True, budget=5)
    assert called == []
    led = (tmp_path / "research_skip_ledger.jsonl").read_text()
    assert "SKIP_UNCHANGED" in led


def test_skip_gate_default_off(monkeypatch):
    monkeypatch.delenv("RESEARCH_SKIP_GATE", raising=False)
    assert skip_gate_enabled() is False
    monkeypatch.setenv("RESEARCH_SKIP_GATE", "1")
    assert skip_gate_enabled() is True


def test_result_is_budget_throttle():
    assert result_is_budget_throttle({"tail": "SKIPPED_BUDGET NXPI COST_CAP_EXCEEDED: daily request cap"})
    assert result_is_budget_throttle({"budget_throttled": True, "tail": "x"})
    assert result_is_budget_throttle({"tail": "[ERROR] COST_CAP_EXCEEDED: daily request cap"})
    assert not result_is_budget_throttle({"tail": "stored hermes_external_research id=1 status=sent\nrecommendation: Hold"})


def test_freshness_class_defaults():
    assert freshness_days_for(tier="T0-HOLD", portfolio_role="INCOME") == 14
    assert freshness_days_for(tier="T0-HOLD", symbol="BND") == 90
    assert freshness_days_for(tier="T0-HOLD") == 30
    assert freshness_days_for(tier="T1-WATCH") == 45
    assert freshness_days_for(tier="T1-WATCH", reentry_ready_near=True) == 14


def test_summarize_rates(tmp_path):
    p = tmp_path / "led.jsonl"
    append_entry(source_id="symbol:A:lane:deepseek", code=SKIP_UNCHANGED, symbol="A",
                 lane="deepseek", reason="hash", metered=True, path=p)
    append_entry(source_id="symbol:B:lane:deepseek", code=RESEARCH_EXECUTED, symbol="B",
                 lane="deepseek", reason="changed", metered=True, path=p)
    out = summarize_rates(p, hours=24)
    assert out["total"] == 2
    assert out["by_code"][SKIP_UNCHANGED] == 1
    assert out["by_code"][RESEARCH_EXECUTED] == 1
    assert out["metered_skipped"] == 1


def test_skip_gate_code_default_stays_zero():
    sched = (ROOT / "scripts/research_scheduler.py").read_text()
    ledger = (ROOT / "scripts/lib/research_skip_ledger.py").read_text()
    assert 'os.getenv("RESEARCH_SKIP_GATE", "0")' in sched
    assert 'os.getenv("RESEARCH_SKIP_GATE", "0")' in ledger


def test_skip_gate_report_missing(tmp_path, monkeypatch, capsys):
    import research_skip_gate_report as rpt

    monkeypatch.setenv("RESEARCH_SKIP_LEDGER_PATH", str(tmp_path / "missing.jsonl"))
    assert rpt.main() == 0
    assert capsys.readouterr().out.strip() == "ledger empty / gate off"


def test_skip_gate_report_empty_file(tmp_path, monkeypatch, capsys):
    import research_skip_gate_report as rpt

    p = tmp_path / "research_skip_ledger.jsonl"
    p.write_text("")
    monkeypatch.setenv("RESEARCH_SKIP_LEDGER_PATH", str(p))
    assert rpt.main() == 0
    assert capsys.readouterr().out.strip() == "ledger empty / gate off"


def test_skip_gate_report_counts_by_code(tmp_path, monkeypatch, capsys):
    import research_skip_gate_report as rpt

    p = tmp_path / "research_skip_ledger.jsonl"
    append_entry(source_id="symbol:A:lane:deepseek", code=SKIP_UNCHANGED, symbol="A",
                 lane="deepseek", reason="hash", metered=True, path=p)
    append_entry(source_id="symbol:A:lane:deepseek", code=SKIP_UNCHANGED, symbol="A",
                 lane="deepseek", reason="hash", metered=True, path=p)
    append_entry(source_id="symbol:B:lane:deepseek", code=RESEARCH_EXECUTED, symbol="B",
                 lane="deepseek", reason="changed", metered=True, path=p)
    monkeypatch.setenv("RESEARCH_SKIP_LEDGER_PATH", str(p))
    assert rpt.main() == 0
    out = capsys.readouterr().out
    assert "SKIP_UNCHANGED" in out
    assert "RESEARCH_EXECUTED" in out
    assert "ledger empty / gate off" not in out
    data = json.loads(out[: out.rfind("}") + 1])
    assert data["by_code"][SKIP_UNCHANGED] == 2
    assert data["by_code"][RESEARCH_EXECUTED] == 1
    assert data["total"] == 3
