"""Defense option (b): the defense-engine-build lane reaches no broker module, with no baseline exception.

* The lane's import closure (scripts/audit_lane_transitive_capabilities.py, lazy imports included) has no
  broker_module / order_placement / direct_sender flag.
* The lane is registered rehearsing only: dry-run argv, live_arg null, and absent from the capability baseline.
* The builder reads stops from the stored DefenseStopsSlice@v1 file; a live-fed and a slice-fed build agree.

Synthetic tickers and values only (the repo is public).
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_lane_transitive_capabilities as audit  # noqa: E402
from lib import defense_engine as de  # noqa: E402

LANE = "defense-engine-build"
NOW = datetime(2030, 1, 7, 15, 0, tzinfo=timezone.utc)


def _lane_row() -> dict:
    lanes = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]
    rows = [r for r in lanes if r["lane_id"] == LANE]
    assert len(rows) == 1
    return rows[0]


def test_lane_closure_reaches_no_forbidden_capability(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"lanes": [_lane_row()]}))
    row = audit.audit(allow)[LANE]
    assert "error" not in row, row.get("error")
    caps = row["capabilities"]
    for cap in audit.FORBIDDEN:
        assert cap not in caps, (cap, caps.get(cap, {}).get("chain"))


def test_lane_is_rehearsing_only_and_has_no_baseline_exception():
    row = _lane_row()
    assert row["dry_run_arg"] == ["--dry-run"]
    assert row["live_arg"] is None
    baseline = json.loads((ROOT / "config" / "n8n_lane_capability_baseline.json").read_text(encoding="utf-8"))
    assert LANE not in (baseline.get("lanes") or {})


def test_builder_source_never_imports_the_broker_reaching_readers():
    tree = ast.parse((ROOT / "scripts" / "defense_engine_build.py").read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    mods |= {f"{n.module}.{a.name}" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    for bad in ("cio_truth", "holdings_document", "db_adapter", "defense_stops_slice"):
        assert not any(bad in m for m in mods), (bad, sorted(mods))


def _truth() -> dict:
    return {"as_of": NOW.isoformat(), "portfolio": {"holdings": ["dropped from the slice"]}, "positions": {
        "rows": [{"symbol": "ZZAA", "account_label": "Acct A", "account_id": "a1", "market_value": 1000.0,
                  "stop_category": "planned", "counted": True, "distance_to_stop_pct": 3.0, "stop_price": 9.0},
                 {"symbol": "ZZBB", "account_label": "Acct B", "account_id": "b1", "market_value": 500.0,
                  "stop_category": "none", "counted": True, "distance_to_stop_pct": None}],
        "stop_breakdown": {"none": {"count": 1, "value_usd": 500.0}, "planned": {"count": 1, "value_usd": 1000.0}}}}


def test_slice_round_trip_keeps_only_read_fields():
    sl = de.stops_slice(_truth())
    assert sl["schema"] == de.STOPS_SLICE_SCHEMA and sl["as_of"] == NOW.isoformat()
    assert all(set(r) <= set(de.STOPS_SLICE_ROW_FIELDS) for r in sl["positions"]["rows"])
    assert "portfolio" not in sl
    truth, gap = de.truth_from_slice(sl)
    assert gap is None and truth["positions"]["stop_breakdown"] == _truth()["positions"]["stop_breakdown"]
    assert de.stops_slice(None) is None
    assert de.truth_from_slice({"schema": "Other@v1"})[1].startswith("stops slice schema")


def test_slice_fed_build_equals_live_fed_build(tmp_path, monkeypatch):
    import defense_engine_build as deb
    monkeypatch.setattr(deb, "load_market_risk", lambda root: (None, "synthetic: no market risk"))
    live = deb.build(tmp_path, now=NOW, truth=_truth())
    missing = deb.build(tmp_path, now=NOW)
    assert missing["stops"]["stale_reason"]  # no slice on file: a stated gap, never calm
    path = tmp_path / de.STOPS_SLICE_REL
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(de.stops_slice(_truth())))
    from_file = deb.build(tmp_path, now=NOW)
    for key in ("stops", "sources", "source_summary"):
        assert from_file[key] == live[key], key
