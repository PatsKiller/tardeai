"""prospectus-build as an n8n-native lane at stage shadow (operator 2026-10-26, Ticker Prospectus contract).

Registry row (dispatcher, shadow, dry_run), allowlist entry (dry_run_arg only, live_arg null, flock, no broker env),
DRAFT health contract awaiting the owner's review, CI gate, and an import closure free of senders, brokers and orders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

LANE = "prospectus-build"


def _json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_lane_is_n8n_native_shadow_dry_run():
    from scripts.lib import lane_dispatch as LD
    from scripts.lib.lane_stage_clamp import clamp_mode

    rows = _json("config/lane_registry.json")["lanes"]
    row = next(r for r in rows if r["lane_id"] == LANE)
    sched = row["scheduler"]
    assert (sched["kind"], sched["expression"], sched["stage"]) == ("n8n", "dispatcher", "shadow")
    assert sched["match"] == "scripts/prospectus_window.py"  # run windows (2026-10-26)
    assert row["dispatch"]["mode"] == "dry_run" and row["dispatch"]["cron"] == [sched["cadence"]]
    assert row["output_signal"]["path"] == f"data/runtime/{LANE}_last.json"
    assert LD.validate_dispatch_block(row) == []
    assert LD.dispatchable(row)
    assert clamp_mode(LANE, "live", rows)["effective_mode"] == "dry_run"

    allow = _json("config/n8n_run_allowlist.json")
    entry = next(e for e in allow["lanes"] if e["lane_id"] == LANE)
    assert entry["command"][:2] == ["$PY", "scripts/prospectus_window.py"] and "--apply" not in entry["command"]
    assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] is None
    assert entry["lock_kind"] == "flock" and entry["output_signal"] == row["output_signal"]["path"]
    assert not any(n.startswith(("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR")) for n in entry["env_names"])
    assert LANE not in json.dumps(allow.get("never"))

    contract = next(c for c in _json("config/n8n_health_contracts.json")["contracts"] if c["id"] == LANE)
    assert contract["stage"] == "shadow" and contract["evidence"]["receipt"] == row["output_signal"]["path"]
    from scripts.lib.n8n_output_verdict import validate_expected_output

    assert validate_expected_output(contract["expected_output"]) == []


def test_no_forbidden_capability_in_import_closure():
    import audit_lane_transitive_capabilities as cap

    res = cap.Resolver(ROOT)
    for entry in ("prospectus_build.py", "prospectus_window.py"):
        order, _parent = res.closure(ROOT / "scripts" / entry)
        caps = set().union(*(res.info(m).caps for m in order))
        assert not caps & {"direct_sender", "broker_module", "order_placement", "chokepoint_send"}, (entry, caps)
        paths = {str(res.info(m).path) for m in order}
        assert not [p for p in paths if "active_trader/" in p or "brokers/" in p], paths
        assert not [p for p in paths if p.endswith(("telegram_alert.py", "email_notifier.py"))], paths


def test_ci_gate_registered():
    from scripts.lib import ci_gates

    doc = _json("config/ci_gates/prospectus_build_lane_20261026.json")
    assert ci_gates.validate(doc, stem="prospectus_build_lane_20261026")
    assert doc["files"] == ["tests/test_prospectus_build_lane_20261026.py"]
