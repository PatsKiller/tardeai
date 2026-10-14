"""Scalp / premarket dispatcher onboarding (operator directive 2026-10-14, n8nmat/scalp-premarket-onboard-20261014).

Pins:
  * the two scalp hot-tier R1 `ingest` lanes (finviz-enrichment-scalp-hot, scalp-hot-list) are shadow cron rows the
    R1 gate admits: dispatch.mode dry_run, allowlist live_arg null, lock == the cron line's flock lock, timeout <
    cadence, market_gate true, a LaneRunReceipt@v1 output_signal, no broker credential name;
  * the market_day_gate.sh policy exception is bounded to exactly three lanes;
  * the hot-list line writes its LaneRunReceipt@v1 on a real run only (dry run prints, writes nothing);
  * the lanes this PR does NOT onboard stay off the dispatcher: active-trader-premarket-watch (direct Telegram sender,
    moomoo quote context), finviz-momentum-scalp-early-lane (proposal + paper validation + advisory send handoff) and
    momentum-scalp-advisory-alerts (advisory Telegram sender, paper_trade_proposals writer).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import lane_dispatch as LD  # noqa: E402
from lib import scalp_hot_tier as hot  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
ONBOARDED = {
    # lane: (cron line flock lock, cron timeout, cadence minutes)
    "finviz-enrichment-scalp-hot": ("/tmp/finviz_enrichment_scalp_hot.lock", 240, 5),
    "scalp-hot-list": ("/tmp/tradeai_scalp_hot_list.lock", 110, 2),
}
NOT_ONBOARDED = ("active-trader-premarket-watch", "finviz-momentum-scalp-early-lane", "momentum-scalp-advisory-alerts")


@pytest.mark.parametrize("lane", sorted(ONBOARDED))
def test_onboarded_lane_is_an_admitted_r1_shadow_cron_row(lane):
    row, entry = ROWS[lane], ALLOW[lane]
    lock, timeout, cadence_min = ONBOARDED[lane]
    sched = row["scheduler"]
    assert sched["kind"] == "cron" and sched["stage"] == "shadow" and sched["wave"] == "W5"
    assert row["dispatch"]["mode"] == "dry_run" and row["dispatch"]["class"] == "ingest"
    assert row["dispatch"]["tz"] == "America/New_York" and row["dispatch"]["cron"] == [sched["expression"]]
    assert row["adopted_reason"] and "generated_by" not in row
    assert LD.dispatch_eligible(row) == (True, "eligible:policy_exception:market_day_gate.sh")
    assert LD.r1_class_admission(row) == (True, "r1_admitted:ingest")
    assert LD.validate_dispatch_block(row) == []
    # allowlist: cron-exact lock, timeout, gate; shadow has no live argv
    assert entry["lock"] == lock and entry["lock_kind"] == "flock"
    assert LD.cron_flock_locks(sched["command_text"]) == [lock]
    assert entry["timeout_s"] == timeout and timeout < cadence_min * 60
    assert entry["market_gate"] is True and "market_day_gate.sh" in sched["command_text"]
    assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]
    assert entry["output_signal"] == row["output_signal"]["path"] == f"data/runtime/{lane}_last.json"
    assert entry["command"][:2] == ["env", "SCALP_HOT_TIER=1"]
    assert not [n for n in entry["env_names"] if any(f in n for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS)]
    assert LD.forbidden_text_hits(" ".join(entry["command"] + entry["dry_run_arg"])) == []


def test_canary_shape_would_pass_once_staged():
    """The canary registry PR flips mode live + live_arg; the gate must then accept it on the cron lock."""
    for lane, (lock, _t, _c) in ONBOARDED.items():
        row = json.loads(json.dumps(ROWS[lane]))
        row["scheduler"]["stage"] = "canary"
        row["dispatch"]["mode"] = "live"
        entry = dict(ALLOW[lane], live_arg=(["--apply"] if lane == "scalp-hot-list" else []))
        assert LD.r1_canary_lock_matches(row, entry) == (True, "canary_on_cron")
        assert LD.r1_class_admission(row, entry) == (True, "r1_admitted:ingest")
        assert LD.r1_class_admission(row, dict(entry, lock=lock + ".other"))[0] is False


def test_policy_exception_bounded_to_three_lanes():
    exc = LD.load_policy_exceptions()
    assert set(exc) == {"trade-ai-scalp-live", "finviz-enrichment-scalp-hot", "scalp-hot-list"}
    assert all(v == frozenset({"market_day_gate.sh"}) for v in exc.values())
    # an unlisted lane with the same gate stays ineligible
    row = json.loads(json.dumps(ROWS["scalp-hot-list"]))
    row["lane_id"] = "some-other-gated-lane"
    assert LD.dispatch_eligible(row)[0] is False


@pytest.mark.parametrize("lane", NOT_ONBOARDED)
def test_advisory_lanes_are_not_runnable_before_7_0_0(lane):
    """No allowlist entry (a forced relay fire is impossible) and no live/dry dispatch until AGENTS 7.0.0 is ACTIVE."""
    row = ROWS[lane]
    assert lane not in ALLOW and row["scheduler"].get("stage") is None
    assert LD.dispatch_mode(row) == "off"


#: The allowlist entry the post-ratification activation PR adds (copy in the packet,
#: lanes/active-trader-premarket-watch.allowlist.json). Pinned here so the activation is a reviewed diff.
PREMARKET_ENTRY = {
    "lane_id": "active-trader-premarket-watch",
    "env_names": ["ACTIVE_TRADER_ALERTS_DIR", "DB_CONN_TRACE", "DB_HOST", "DB_NAME", "DB_PASSWORD", "DB_PORT", "DB_USER",
                  "PROJECT_ROOT", "SAFE_FLOCK_LOG_DIR", "TRADEAI_PERSISTENT_STATE_ROOT", "TRADEAI_ROOT"],
    "env_allowlist_mode": "report",
    "command": ["$PY", "scripts/active_trader/premarket_watch.py"],
    "lock": "/tmp/at_premarket.lock", "lock_kind": "flock", "timeout_s": 240,
    "dry_run_arg": [], "live_arg": None, "market_gate": False,
    "output_signal": "data/active_trader/momentum_alerts_premarket_heartbeat.json",
}


def test_premarket_watch_is_staged_inert_and_admissible_once_7_0_0_is_active():
    row = ROWS["active-trader-premarket-watch"]
    assert row["dispatch"]["mode"] == "off" and row["dispatch"]["class"] == "pipeline"
    assert row["dispatch"]["cron"] == [row["scheduler"]["expression"]] == ["*/5 6-9 * * 1-5"]
    assert LD.cron_flock_locks(row["scheduler"]["command_text"]) == [PREMARKET_ENTRY["lock"]]
    assert row["advisory_md_staged"]["policy"].startswith("AGENTS.md 7.0.0 §23.20")
    # The activation shape (stage shadow, dry_run). premarket_watch.py has no --dry-run flag: its bare command is the
    # dry run (no journal, no throttle state, no heartbeat, send_fn None) and the cron line passes --apply, which the
    # 7.0.0 gate accepts as an explicit-apply dry run (lane_dispatch._explicit_apply_dry_run).
    active = json.loads(json.dumps(row))
    active["scheduler"]["stage"], active["dispatch"]["mode"] = "shadow", "dry_run"
    assert LD.advisory_md_admission(active, PREMARKET_ENTRY, status="PROPOSED")[0] is False
    assert LD.advisory_md_admission(active, PREMARKET_ENTRY, status="ACTIVE") == (True, "advisory_md_admitted")
    canary = dict(PREMARKET_ENTRY, live_arg=["--apply"])
    assert LD.advisory_md_admission(active, canary, status="ACTIVE") == (True, "advisory_md_admitted")
    assert LD.advisory_md_static_errors(active, PREMARKET_ENTRY) == []


def test_early_lane_command_text_is_the_live_line_without_submit():
    ct = ROWS["finviz-momentum-scalp-early-lane"]["scheduler"]["command_text"]
    assert "--submit-validation" not in ct and "--run-validation-fast-path" in ct
    assert LD.cron_flock_locks(ct) == ["/tmp/tradeai_finviz_momentum_scalp.lock"]


def test_hot_list_line_has_its_own_row_and_early_lane_match_is_narrowed():
    line = ("*/2 6-9 * * 1-5 cd $PROJ && SCALP_HOT_TIER=1 MOMENTUM_SCALP_OUTER_DEADLINE_S=100 flock -n "
            "/tmp/tradeai_scalp_hot_list.lock timeout 110 bash scripts/market_day_gate.sh $PY "
            "scripts/run_finviz_momentum_scalp_scan.py --hot-list-only --apply >> logs/scalp_hot_list.log 2>&1  "
            "# TRADEAI_LANE scalp-hot-list")
    early = ("*/5 6-11 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_finviz_momentum_scalp.lock timeout 280 env "
             "MOMENTUM_SCALP_OUTER_DEADLINE_S=260 $PY scripts/run_finviz_momentum_scalp_scan.py --window early --apply")
    hits = [k for k, r in ROWS.items() if r.get("state") == "ACTIVE" and isinstance(r["scheduler"].get("match"), str)
            and r["scheduler"]["match"] and r["scheduler"]["match"] in line]
    assert hits == ["scalp-hot-list"]
    assert ROWS["finviz-momentum-scalp-early-lane"]["scheduler"]["match"] in early
    assert ROWS["finviz-momentum-scalp-early-lane"]["scheduler"]["match"] not in line


# ── the hot-list LaneRunReceipt@v1 ────────────────────────────────────────────


import run_finviz_momentum_scalp_scan as scan  # noqa: E402


@pytest.fixture
def hot_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv(hot.ENV_FLAG, "1")
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(scan.lane, "refresh_age_min", lambda *a, **k: 5.0)
    monkeypatch.setattr(scan.lane, "stage_finviz_scan",
                        lambda **k: calls.append(k) or {"stage": "finviz_scan", "ran": True, "ok": True, "rc": 0})
    return tmp_path, calls


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run_finviz_momentum_scalp_scan.py", "--hot-list-only", *argv])
    return scan.main()


def _receipt(root):
    return root / "data" / "runtime" / "scalp-hot-list_last.json"


def test_hot_list_dry_run_writes_no_receipt(hot_state, monkeypatch, capsys):
    root, calls = hot_state
    assert _run(monkeypatch, "--dry-run", "--now", "2026-10-12T07:00:00") == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "scalp-hot-list_last.json" in out and "dry_run_no_refresh" in out
    assert calls == [] and not _receipt(root).exists()
    assert sorted(p.name for p in (root / "data" / "runtime").iterdir()) == []


def test_hot_list_apply_writes_receipt_and_failure_keeps_ok_at(hot_state, monkeypatch):
    root, calls = hot_state
    assert _run(monkeypatch, "--apply", "--now", "2026-10-12T07:00:00") == 0
    rec = json.loads(_receipt(root).read_text())
    assert rec["ok_at"] and rec["lane_id"] == "scalp-hot-list" and len(calls) == 1
    ok_at = rec["ok_at"]
    monkeypatch.setattr(scan.lane, "stage_finviz_scan", lambda **k: {"stage": "finviz_scan", "ok": False, "rc": 1})
    assert _run(monkeypatch, "--apply", "--now", "2026-10-12T07:02:00") == 1
    rec = json.loads(_receipt(root).read_text())
    assert rec["ok_at"] == ok_at and rec.get("status") == "failed"


def test_hot_list_off_window_and_flag_off_write_nothing(hot_state, monkeypatch, capsys):
    root, calls = hot_state
    assert _run(monkeypatch, "--apply", "--now", "2026-10-12T12:10:00") == 0
    assert "SKIPPED_OFF_HOT_WINDOW" in capsys.readouterr().out
    monkeypatch.delenv(hot.ENV_FLAG)
    assert _run(monkeypatch, "--apply", "--now", "2026-10-12T07:00:00") == 0
    assert "SKIPPED_FLAG_OFF" in capsys.readouterr().out
    assert calls == [] and not _receipt(root).exists()
