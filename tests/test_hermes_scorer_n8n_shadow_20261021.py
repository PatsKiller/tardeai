"""hermes-watchlist-scorer n8n SHADOW onboarding 2026-10-21 (operator-approved via coordinator).

Cron L451 `*/15 * * * *` stays the live scheduler (cron freeze). The dispatcher fires the lane in dry_run only:
`--dry-run` is write-free (tests/test_hermes_scorer_hardening_20261021.py proves it), live_arg is null, and the
health contract is DRAFT until the owner reviews it. Hermetic: reads config only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json"]

LANE = "hermes-watchlist-scorer"
RECEIPT = "data/runtime/hermes-watchlist-scorer_last.json"


def _registry_row():
    rows = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    rows = rows["lanes"] if isinstance(rows, dict) else rows
    return next(r for r in rows if r.get("lane_id") == LANE)


def _allowlist_entry():
    a = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    return a, next(x for x in a["lanes"] if x["lane_id"] == LANE)


def test_registry_row_is_cron_shadow_dry_run():
    row = _registry_row()
    sch, d = row["scheduler"], row["dispatch"]
    assert sch["kind"] == "cron" and sch["expression"] == "*/15 * * * *" and sch["stage"] == "shadow"
    assert "flock -n /tmp/hermes_scorer.lock" in sch["command_text"]
    assert d["mode"] == "dry_run" and d["cron"] == ["*/15 * * * *"] and d["tz"] == "America/New_York"
    sig = row["output_signal"]
    assert (sig["kind"], sig["path"], sig["key"]) == ("json_key", RECEIPT, "ok_at")
    assert "generated_by" not in row and row["adopted_from_generator"] == "reconcile_lane_registry@v1"


def test_allowlist_entry_is_shadow_and_not_never_listed():
    a, e = _allowlist_entry()
    assert e["command"] == ["$PY", "scripts/hermes_watchlist_scorer.py", "--once"]
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
    # the executor derives <lock>.dryrun for a dry_run fire; the allowlist names the cron line's own lock
    assert e["lock"] == "/tmp/hermes_scorer.lock" and not e["lock"].endswith(".dryrun") and e["lock_kind"] == "flock"
    assert e["output_signal"] == RECEIPT
    assert not any(n.startswith(("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR")) for n in e["env_names"])
    assert LANE not in json.dumps(a.get("never"))


def test_receipt_path_agrees_with_the_scorer():
    import hermes_watchlist_scorer as hws
    assert hws.LANE_ID == LANE and RECEIPT == f"data/runtime/{hws.LANE_ID}_last.json"


def test_health_contract_is_shadow_draft_with_expected_output():
    c = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    k = next(x for x in c["contracts"] if x["id"] == LANE)
    assert k["stage"] == "shadow" and k["status"] == "DRAFT" and k["evidence"]["receipt"] == RECEIPT
    eo = k["expected_output"]
    assert eo["produced_field"] == "produced_count" and "nothing_due" in eo["empty_allowed_reasons"]


def test_lane_dispatch_admits_the_row():
    from lib.lane_dispatch import dispatch_eligible
    ok = dispatch_eligible(_registry_row())
    assert (ok[0] if isinstance(ok, tuple) else ok), ok
