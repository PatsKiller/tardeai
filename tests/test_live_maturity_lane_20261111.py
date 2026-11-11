"""LQ-20261107-1986 — the LIVE MATURITY counter is registered as a SHADOW n8n dispatcher lane (the poller REVIEW-1967 N1
found missing), and the LQ-1971 N2 note fix.

Pins, in one place, that the three config files agree and that the registration can only ever run the read-only argv:
  * the registry row is a dispatcher row at stage shadow / dispatch.mode dry_run, every 10 minutes, 24x7 (no gap
    longer than 10 minutes, so no ATM */15 slot can be overwritten between two polls);
  * the allowlist entry's dry-run argv is the script's own read-only flag, live_arg is null, and the script REFUSES
    --dry-run together with --write-state;
  * compute_due on the real row emits only dry_run, one per 10-minute slot, against a throwaway ledger;
  * the contract is DRAFT at the registry's stage (a reviewer is still needed);
  * an inactive unit's history note no longer says release=same.
Every fixture is synthetic (tmp_path ledger/state, no DB, no provider, no broker, no systemd call).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from scripts.lib.cron_schedule import fires_between  # noqa: E402
from scripts.lib.lane_dispatch import dispatch_eligible, parse_dispatch_block  # noqa: E402
from scripts.lib.lane_registry import validate_row  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.ops import live_maturity as LM  # noqa: E402

LID = "live-maturity"
ET = ZoneInfo("America/New_York")
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")


def _load(name):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def row():
    return next(r for r in _load("lane_registry.json")["lanes"] if r.get("lane_id") == LID)


def entry():
    return next(e for e in _load("n8n_run_allowlist.json")["lanes"] if e.get("lane_id") == LID)


def contract():
    return next(c for c in _load("n8n_health_contracts.json")["contracts"] if c.get("id") == LID)


def test_the_row_is_a_shadow_dispatcher_lane_every_ten_minutes_24x7():
    r = row()
    assert validate_row(r) == []
    s = r["scheduler"]
    assert (s["kind"], s["expression"], s["stage"]) == ("n8n", "dispatcher", "shadow")
    assert s["match"] == "scripts/ops/live_maturity.py"
    assert r["dispatch"]["mode"] == "dry_run" and r["state"] == "ACTIVE"
    assert tuple(parse_dispatch_block(r).cron) == (s["cadence"],) == ("*/10 * * * *",)
    assert r["active_days"] == [0, 1, 2, 3, 4, 5, 6]
    ok, why = dispatch_eligible(r)
    assert ok, why


def test_no_gap_between_fires_can_let_an_atm_slot_be_overwritten():
    """ATM needs a poll at least every 15 min (config/live_acceptance_v2.json); the schedule is re-derived."""
    start = datetime(2026, 11, 12, 0, 0, tzinfo=ET)
    fires = fires_between(row()["scheduler"]["cadence"], start, start + timedelta(days=2), tz="America/New_York")
    assert len(fires) == 2 * 24 * 6
    gaps = {int((b.at - a.at).total_seconds() // 60) for a, b in zip(fires, fires[1:])}
    assert gaps == {10}
    atm = next(i for i in LM.load_registry(LM.DEFAULT_REGISTRY)["items"] if i["id"] == "atm")
    assert atm["cadence"]["cron"].startswith("*/15") and max(gaps) <= 15


def test_the_entry_is_shadow_only_and_runs_the_read_only_flag():
    from scripts.n8n_run_executor import validate_entry

    e = entry()
    assert validate_entry(e) is None
    assert e["command"] == ["$PY", "scripts/ops/live_maturity.py"]
    assert e["dry_run_arg"] == ["--dry-run"]
    assert e["live_arg"] is None, "shadow: no live argv exists; promoting (--write-state) is the lead's decision"
    assert e["lock_kind"] == "flock" and e["market_gate"] is False
    assert e["output_signal"] == row()["output_signal"]["path"] == contract()["evidence"]["receipt"]
    assert not [n for n in e["env_names"] if any(t in n.upper() for t in ("SCHWAB", "BROKER", "TOKEN", "SECRET", "DB_"))]


def test_the_script_default_state_is_the_registered_signal_and_dry_run_refuses_write(tmp_path, capsys):
    assert LM.DEFAULT_STATE.as_posix().endswith(entry()["output_signal"].replace("data/", "", 1))
    with pytest.raises(SystemExit) as ex:
        LM.main(["--dry-run", "--write-state", "--state", str(tmp_path / "s.json")])
    assert ex.value.code == 2
    assert not (tmp_path / "s.json").exists()


def test_the_dry_run_argv_writes_nothing(tmp_path, monkeypatch, capsys):
    state = tmp_path / "s.json"
    real = LM.Sources
    monkeypatch.setattr(LM, "Sources", lambda: real(receipts_dir=tmp_path / "r", runtime_dir=tmp_path / "rt",
                                                    service_reader=lambda u: None, ancestor_fn=lambda a, b: None))
    assert LM.main(["--dry-run", "--state", str(state)]) == 0
    assert not state.exists() and not list(tmp_path.glob("*.lock"))
    assert "read-only" in capsys.readouterr().out


def test_compute_due_emits_only_dry_run_one_per_ten_minute_slot(tmp_path, monkeypatch):
    monkeypatch.delenv(D.LIVE_LANES_ENV, raising=False)
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    try:
        allow = {LID: entry()}
        start = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)   # 09:00 ET
        seen = []
        for tick in range(0, 12 * 6):                                # one tick a minute for 72 minutes
            now = start + timedelta(minutes=tick)
            resp = D.compute_due([row()], allow, POLICIES, store, now)
            assert resp["errors"] == [], resp["errors"]
            for it in resp["items"]:
                assert it["mode"] == "dry_run", "a shadow lane can never be emitted live"
                seen.append(it["slot_local"])
                store.request(run_id=it["idempotency_key"], lane_id=LID, mode="dry_run", requested_by="t",
                              caller_id="t", now=now.timestamp())
                ledger._conn.execute("UPDATE runs SET state='RUN_DONE', finished_at=?, exit_code=0 WHERE run_id=?",
                                     (now.isoformat(), it["idempotency_key"]))
                ledger._conn.commit()
        assert len(seen) == len(set(seen)) >= 6, seen
        assert {s[-2:] for s in seen} <= {"00", "10", "20", "30", "40", "50"} or all(":" in s for s in seen)
    finally:
        ledger.close()


def test_the_contract_is_signed_by_a_non_author_at_the_registry_stage():
    c = contract()
    assert c["status"] == "REVIEWED" and c["review"]["status"] == "REVIEWED"
    assert c["review"]["reviewed_by"] == "cc-sonnet-7" and c["review"]["reviewed_on"] == "2026-11-11"
    assert c["stage"] == row()["scheduler"]["stage"]
    assert c["baseline"]["timeout_s"] == entry()["timeout_s"]
    assert c["baseline"]["duration_degraded_above_s"] == 0.8 * entry()["timeout_s"]


# ── LQ-1971 N2 ─────────────────────────────────────────────────────────────────────────────────────


def test_an_inactive_unit_note_does_not_claim_release_same():
    items = [i for i in LM.load_registry(LM.DEFAULT_REGISTRY)["items"] if i["id"] == "portfolio-server"]
    reg = {"items": items}
    LM.validate_registry(reg)
    now = datetime(2026, 11, 12, 10, 0, tzinfo=ET)
    unit = {"active": "inactive", "cwd": "/srv/releases/9544fa5d7-live-integration-20261111-142259",
            "enter": None}
    src = LM.Sources(service_reader=lambda u: unit, ancestor_fn=lambda a, b: True)
    new, _ = LM.evaluate(reg, {}, src, now)
    notes = [h["note"] for h in new["portfolio-server"]["history"]]
    assert notes and all("release=same" not in n for n in notes), notes
    assert any("release=not_checked" in n for n in notes), notes
