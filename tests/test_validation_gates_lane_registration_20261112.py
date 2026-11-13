"""VALIDATION_GATES_LANE_REGISTRATION_20261112 - the validation-gates-sync lane is registered, and it is SHADOW.

LQ-20261107-2141. Registration is not execution: this pins the registry row, allowlist entry, health contract and
freshness contract to each other and to the script, and pins the stage to shadow / dispatch dry_run so nothing writes
Postgres until the lead flips it. The dry argv is emulated against a synthetic source; no DB, no network.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cron_schedule as CRON  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402

LID = "validation-gates-sync"
TZ = "America/New_York"
SIGNAL = "data/runtime/validation-gates-sync_last.json"
REG = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
ALLOW = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
HEALTH = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
ROW = {r["lane_id"]: r for r in REG["lanes"]}[LID]
ENTRY = {e["lane_id"]: e for e in ALLOW["lanes"]}[LID]
CONTRACT = {c["id"]: c for c in HEALTH["contracts"]}[LID]
FRESH = {c["key"]: c for c in REG["freshness_contracts"]}["home.validation_gates"]


def test_row_is_a_shadow_dispatcher_row_for_the_real_script():
    s = ROW["scheduler"]
    assert (s["kind"], s["expression"], s["stage"], s["timezone"]) == ("n8n", "dispatcher", "shadow", TZ)
    assert s["match"] == "scripts/validation_gates_sync.py" and (ROOT / s["match"]).is_file()
    assert ROW["dispatch"]["mode"] == "dry_run"  # flipping to live is the lead's act, not this commit's
    assert LR.validate_row(ROW) == []
    policies = json.loads((ROOT / "config/n8n_retry_policies.json").read_text(encoding="utf-8"))["policies"]
    assert LD.validate_dispatch_block(ROW, known_lane_ids=[r["lane_id"] for r in REG["lanes"]],
                                      retry_policy_names=list(policies)) == []
    assert LD.dispatch_eligible(ROW)[0] is True


def test_cadence_is_every_five_minutes_all_week():
    assert ROW["dispatch"]["cron"] == ["*/5 * * * *"] == [ROW["scheduler"]["cadence"]]
    start = datetime(2026, 11, 9, 0, 0, tzinfo=ZoneInfo(TZ))
    fires = list(CRON.fires_between(ROW["dispatch"]["cron"][0], start - timedelta(seconds=1),
                                    start + timedelta(days=7) - timedelta(seconds=1), TZ))
    assert len(fires) == 288 * 7 and sorted(ROW["active_days"]) == list(range(7))


def test_signal_files_agree():
    assert ROW["output_signal"]["path"] == SIGNAL == ENTRY["output_signal"]
    assert FRESH["signal"] == {"kind": "db_max", "table": "validation_gates", "column": "last_evaluated_at"}
    assert FRESH["lane_id"] == LID and FRESH["max_age_hours"] == 0.25 and FRESH["severity"] == "P1"


def test_allowlist_entry_is_the_apply_form_with_its_own_lock():
    assert ENTRY["command"] == ["$PY", "scripts/validation_gates_sync.py"]
    assert ENTRY["dry_run_arg"] == [] and ENTRY["live_arg"] == ["--apply"]
    assert ENTRY["lock"] == "/tmp/validation_gates_sync.lock" and ENTRY["market_gate"] is False
    assert not any("KEY" in n or "TOKEN" in n or "SCHWAB" in n for n in ENTRY["env_names"])
    assert ENTRY["timeout_s"] == 120


def test_health_contract_is_a_reviewed_shadow_copy_of_the_row():
    assert CONTRACT["status"] == "REVIEWED" and CONTRACT["stage"] == ROW["scheduler"]["stage"] == "shadow"
    assert CONTRACT["baseline"]["timeout_s"] == ENTRY["timeout_s"]
    assert any("last_evaluated_at" in t["text"] for t in CONTRACT["healthy"])


def test_allowlist_env_names_are_the_ones_the_script_reads():
    assert ENTRY["env_names"] == ["DB_HOST", "DB_NAME", "DB_PASSWORD", "DB_PORT", "DB_USER", "TRADEAI_STATE_ROOT"]
    assert ENTRY["env_allowlist_mode"] == "report" and ENTRY["env_report_reason"] and ENTRY["env_evidence"]


def test_both_migrations_exist_with_downs_and_carry_the_spec_checks():
    mig = ROOT / "migrations"
    for n in ("validation_gates", "validation_events"):
        assert (mig / f"2026_11_12_{n}.sql").is_file() and (mig / f"2026_11_12_{n}.down.sql").is_file()
    g = (mig / "2026_11_12_validation_gates.sql").read_text()
    assert "closed_by = 'operator'" in g and "closed_by <> declared_by" in g
    assert "dedupe_key       TEXT NOT NULL UNIQUE" in (mig / "2026_11_12_validation_events.sql").read_text()
