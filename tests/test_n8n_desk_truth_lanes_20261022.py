"""Desk truth lanes, 2026-10-22 (operator: "fix all of these n8n first for scheduling and monitoring").

Pins the registry PR that puts the scripts of tests/test_n8n_desk_truth_20261022.py on the n8n dispatcher:
  * three read-only monitors are n8n-native dispatcher rows at SHADOW (the stage clamp runs them dry), with allowlist
    entries (--dry-run, live_arg null, own flock lock) and health contracts;
  * the quote-only options refresh and the holdings writer (schwab-position-sync) are STAGED INERT: dispatch off, no
    allowlist entry, an f09_staged record with the activation entry and needs — the dispatcher refuses their broker
    reach until the operator admits it;
  * every new contract was DRAFT until its owner REVIEWed it (no agent self-certifies); the operator REVIEWED all
    five on 2026-10-22 ("You just start executing immediately with multiple agents for everything that's not built
    and not live", replying to "#1928: OK for a fresh PR, and approve its 5 contracts?");
  * no crontab line: schwab-position-sync stays PAUSED with its line commented.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import desk_truth_monitor as DTM  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

REG = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}
MONITORS = {spec["lane"]: check for check, spec in DTM.CHECKS.items()}
STAGED = ("options-desk-quote-refresh", "schwab-position-sync")


def test_monitor_rows_are_native_shadow_dispatcher_rows():
    for lane, check in MONITORS.items():
        row = REG[lane]
        s = row["scheduler"]
        assert (s["kind"], s["expression"], s["stage"]) == ("n8n", "dispatcher", "shadow"), lane
        assert s["match"] == f"scripts/desk_truth_monitor.py --check {check}"
        assert row["dispatch"]["mode"] == "dry_run" and row["dispatch"]["class"] == "monitor"
        assert row["dispatch"]["cron"] == [s["cadence"]] and row["state"] == "ACTIVE"
        assert row["output_signal"]["path"] == f"data/runtime/{lane}_last.json"
        ok, why = LD.dispatch_eligible(row)
        assert ok and why == "eligible", (lane, why)
        assert LD.dispatchable(row)


def test_monitor_allowlist_entries_are_dry_run_only_with_their_own_locks():
    locks = set()
    for lane, check in MONITORS.items():
        e = ALLOW[lane]
        assert e["command"] == ["$PY", "scripts/desk_truth_monitor.py", "--check", check]
        assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
        assert e["lock_kind"] == "flock" and e["lock"].startswith("/tmp/tradeai_desk_truth_")
        locks.add(e["lock"])
        assert e["output_signal"] == f"data/runtime/{lane}_last.json" and e["output_receipt"] == "v2"
        assert not any(n.startswith(("SCHWAB", "ALPACA", "MOOMOO", "SNAPTRADE", "TELEGRAM")) for n in e["env_names"])
        assert LD.forbidden_text_hits(" ".join(e["command"])) == []
    assert len(locks) == 3


def test_staged_lanes_are_inert_and_carry_their_activation_record():
    for lane in STAGED:
        row = REG[lane]
        assert lane not in ALLOW, lane  # the only list the gateway and executor read
        assert LD.dispatch_mode(row) == "off" and not LD.dispatchable(row)
        rec = row["f09_staged"]
        assert rec["activation_allowlist_entry"]["lane_id"] == lane
        assert rec["activation_allowlist_entry"]["live_arg"] is None
        # broker READ-ONLY lanes on n8n wait for AGENTS.md 19.0.0 (operator-directed 2026-10-22, not yet ratified)
        assert "19.0.0" in rec["gated_on"]["policy"] and rec["gated_on"]["status_required"] == "ACTIVE"
        assert rec["activation_needs"][0].startswith("AGENTS.md 19.0.0 ACTIVE")
    qr = REG["options-desk-quote-refresh"]
    # kind none until admitted: a kind-n8n dispatcher row must have an allowlist entry (4.1.0 amendment test)
    assert qr["state"] == "NEVER_SCHEDULED" and qr["scheduler"]["kind"] == "none"
    act = qr["f09_staged"]["activation_registry"]
    assert act["scheduler"]["cadence"] == "5,20,35,50 9-11 * * 1-5" and act["dispatch"]["mode"] == "dry_run"
    assert qr["f09_staged"]["request_budget"]["per_run_cap"] == 25
    assert "GPU" in qr["f09_staged"]["gpu_window"]
    sps = REG["schwab-position-sync"]
    assert sps["state"] == "PAUSED" and sps["scheduler"]["kind"] == "cron"
    assert sps["f09_staged"]["access_mode"]["required"] == "read_only"
    assert sps["f09_staged"]["cron_lines"][0]["text"].startswith("# PAUSED 2026-10-15")


def test_every_new_contract_is_owned_and_operator_reviewed():
    for lane in (*MONITORS, *STAGED):
        c = CONTRACTS[lane]
        assert c["status"] == "REVIEWED" and c["review"]["status"] == "REVIEWED", lane
        assert c["review"]["reviewed_by"].startswith("operator PatsKiller 2026-10-22"), lane
        assert "approve its 5 contracts" in c["review"]["reviewed_by"], lane
        assert c["review"]["reviewed_on"] == "2026-10-22", lane
        assert c["owner"] and c["expected_output"]["schema"] == "N8nExpectedOutput@v1"
        assert c["alerting"]["failed"]["notifier_priority"] == "P2"
    assert CONTRACTS["options-desk-quote-refresh"]["purpose"]["text"].count("GPU") == 1


def test_no_monitor_reaches_a_sender_broker_or_order_module():
    import audit_lane_transitive_capabilities as cap

    res = cap.Resolver()
    order, _ = res.closure(ROOT / "scripts" / "desk_truth_monitor.py")
    caps = set().union(*(res.info(m).caps for m in order))
    assert not caps & {"direct_sender", "broker_module", "order_placement", "chokepoint_send"}, caps
