"""trade-ai-scalp-live as an n8n-driven lane (operator 2026-10-09: "n8n drives a governed lane (Recommended)").

Live allowed by the AGENTS 4.0.0 §23.3 exception (APPROVE_AGENTS_POLICY_4_0_0, 2026-10-09): live_arg [] is the exact
cron argv (the live cycle is a Finviz ingest + trade_ai_scans writer + Telegram sender, so nothing else may change). Pins: the dry run writes nothing, every
completed run writes the receipt the executor and the fan-in read, the registry output_signal resolves (no '~'),
the generated workflows exist and are inactive, and the fan-in raises one STALLED finding in RTH only.
Hermetic: tmp state root, fake clocks, no network, no DB.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts import n8n_run_executor as X  # noqa: E402

ET = ZoneInfo("America/New_York")
LANE = "trade-ai-scalp-live"
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
ENTRY = next(e for e in ALLOW["lanes"] if e["lane_id"] == LANE)


def test_allowlist_entry_runs_the_cron_argv_and_shares_the_cron_lock():
    assert X.validate_entry(ENTRY) is None
    assert ENTRY["command"] == ["$PY", "scripts/run_trade_ai_scalp_live.py"]
    assert ENTRY["dry_run_arg"] == ["--dry-run"]
    assert ENTRY["live_arg"] == []                                # AGENTS 4.0.0 §23.3 exception: exact cron argv
    assert ENTRY["lock"] == "/tmp/tradeai_scalp_live.lock" and ENTRY["lock_kind"] == "flock"
    assert ENTRY["timeout_s"] == 295 and ENTRY["market_gate"] is True
    assert ENTRY["output_signal"] == "data/runtime/trade_ai_scalp_live_last.json"
    env = {"TRADEAI_VENV_PYTHON": "/py"}
    live = X.build_argv(ENTRY, "live", env=env, state_root=Path("/s"), code_root=Path("/c"))
    assert live[-2:] == ["/py", "scripts/run_trade_ai_scalp_live.py"]
    assert ["timeout", "-k", str(X.KILL_AFTER_S), "295", "bash", "scripts/market_day_gate.sh"] == live[5:11]
    argv = X.build_argv(ENTRY, "dry_run", env=env, state_root=Path("/s"), code_root=Path("/c"))
    assert argv[:5] == ["flock", "-n", "-E", str(X.FLOCK_CONFLICT_EXIT), "/tmp/tradeai_scalp_live.lock"]
    assert argv[-3:] == ["/py", "scripts/run_trade_ai_scalp_live.py", "--dry-run"]
    crontab_line = next(l for l in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]
                        if l["lane_id"] == LANE)["scheduler"]["expression"]
    assert ENTRY["lock"] in crontab_line                           # n8n and cron can never overlap


def test_registry_output_signal_resolves_against_the_state_root(tmp_path):
    from scripts.lib.lane_registry import observe_signal

    row = next(l for l in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"] if l["lane_id"] == LANE)
    sig = row["output_signal"]
    assert not str(sig["path"]).startswith("~")                     # observe_signal never expands '~'
    assert sig["path"] == ENTRY["output_signal"]
    p = tmp_path / sig["path"]
    p.parent.mkdir(parents=True)
    p.write_text("{}")
    got = observe_signal(sig, root=tmp_path)
    assert got["last_output_at"] is not None and str(p) in got["detail"]


def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    import continuous_runner as cr

    monkeypatch.setattr(cr, "run_live_cycle", lambda *a, **k: (_ for _ in ()).throw(AssertionError("scanned")))
    assert r.main(["--dry-run"]) == 0
    assert list(tmp_path.rglob("*")) == []
    out = capsys.readouterr().out
    assert out.startswith("[scalp-live] dry-run ") and '"mode": "dry_run"' in out


def test_completed_runs_write_the_receipt_and_carry_last_ok(tmp_path, monkeypatch):
    import continuous_runner as cr
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(cr, "run_live_cycle", lambda *a, **k: [{"symbol": "wff", "decision": "GO"}])
    assert r.main(["--force"]) == 0
    doc = json.loads(r.receipt_path().read_text())
    assert doc["schema"] == "TradeAIScalpLiveReceipt@v1" and doc["status"] == "ok" and doc["universe"] == 1
    assert doc["last_ok_at"] == doc["as_of"]
    later = datetime.now(ET) + timedelta(minutes=7)
    doc2 = r.write_receipt("outside_rth", later)
    assert doc2["status"] == "outside_rth" and doc2["last_ok_at"] == doc["last_ok_at"]
    assert not list(tmp_path.rglob("*.tmp"))


def test_generated_workflows_exist_inactive_in_rth():
    gen = ROOT / "docs/implementation/n8n-parallel/workflows/generated"
    idx = json.loads((gen / "INDEX.json").read_text())
    row = next(w for w in idx["workflows"] if w["lane_id"] == LANE) if "workflows" in idx else None
    for name in (f"{LANE}-shadow.json", f"{LANE}.json"):
        wf = json.loads((gen / name).read_text())
        assert wf.get("active") is False
        text = json.dumps(wf)
        assert "*/5 9-15 * * 1-5" in text and "America/New_York" in text   # = the cron line; script gates RTH
    assert row is None or row.get("committed") is True
    assert LANE in json.dumps(idx)


def _fanin_now(et_h, et_m, day=(2026, 10, 9)):
    return datetime(*day, et_h, et_m, tzinfo=ET).astimezone(timezone.utc)


def test_fanin_raises_one_stalled_finding_in_rth_only(tmp_path, monkeypatch):
    from scripts import n8n_incident_fanin as F
    import market_session

    monkeypatch.setattr(market_session, "is_trading_day", lambda *a, **k: True)
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    now = _fanin_now(14, 0)
    (rt / "trade_ai_scalp_live_last.json").write_text(json.dumps(
        {"status": "ok", "last_ok_at": (now - timedelta(minutes=30)).isoformat()}))
    found = F._scalp_lane_findings(tmp_path, now)
    assert len(found) == 1 and found[0]["item"] == "trade-ai-scalp-live:STALLED" and found[0]["severity"] == "P2"
    assert found[0]["detected_at"].endswith("T00:00:00+00:00")          # stable per day = one event
    assert F._scalp_lane_findings(tmp_path, _fanin_now(9, 35)) == []      # first cycle still landing
    assert F._scalp_lane_findings(tmp_path, _fanin_now(16, 5)) == []      # after the close
    assert F._scalp_lane_findings(tmp_path, _fanin_now(14, 0, (2026, 10, 10))) == []   # Saturday
    (rt / "trade_ai_scalp_live_last.json").write_text(json.dumps(
        {"status": "ok", "last_ok_at": (now - timedelta(minutes=6)).isoformat()}))
    assert F._scalp_lane_findings(tmp_path, now) == []
    monkeypatch.setattr(market_session, "is_trading_day", lambda *a, **k: False)
    (rt / "trade_ai_scalp_live_last.json").write_text(json.dumps({"status": "ok", "last_ok_at": None}))
    assert F._scalp_lane_findings(tmp_path, now) == []                     # holiday


def test_fanin_without_receipt_is_a_note_not_a_finding(tmp_path):
    from scripts import n8n_incident_fanin as F

    assert F._scalp_lane_findings(tmp_path, _fanin_now(14, 0)) == []
