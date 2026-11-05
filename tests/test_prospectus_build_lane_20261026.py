"""prospectus-build as an n8n-native lane at stage shadow (operator 2026-10-26, Ticker Prospectus contract).

Registry row (dispatcher, shadow, dry_run), allowlist entry (dry_run_arg only, live_arg null, flock, no broker env),
REVIEWED health contract, CI gate, and an import closure with no direct sender and only lazy (baselined) broker reach.
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
    """No direct sender anywhere in the closure; broker/order reach only LAZY (the shared llm_consumption ->
    db_adapter write-path chain, baselined under the DD01 ruling); and the lane's own code imports no sender."""
    import ast
    import audit_lane_transitive_capabilities as cap

    res = cap.Resolver(ROOT)
    for entry in ("prospectus_build.py", "prospectus_window.py"):
        order, _parent = res.closure(ROOT / "scripts" / entry)
        caps = set().union(*(res.info(m).caps for m in order))
        assert "direct_sender" not in caps, entry
    row = cap.audit()[LANE]["capabilities"]
    assert "direct_sender" not in row
    for c in ("broker_module", "order_placement"):
        assert c not in row or row[c]["at_import"] is False, (c, row[c])
    own = [ROOT / "scripts/prospectus_window.py", ROOT / "scripts/prospectus_build.py",
           *sorted((ROOT / "scripts/lib/prospectus").glob("*.py"))]
    senders = {"telegram_alert", "email_notifier", "telegram_transport", "smtp" + "lib"}
    for path in own:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not [n for n in names if n.split(".")[-1] in senders], (path.name, names)


def test_ci_gate_registered():
    from scripts.lib import ci_gates

    doc = _json("config/ci_gates/prospectus_build_lane_20261026.json")
    assert ci_gates.validate(doc, stem="prospectus_build_lane_20261026")
    assert doc["files"] == ["tests/test_prospectus_build_lane_20261026.py"]
