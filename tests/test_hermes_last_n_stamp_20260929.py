"""Bounded Hermes last-N identity stamp."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REG = "ecb5ba89-96c6-536c-ba76-89e468a81bf1"


def test_stamp_last_n_fills_missing_guid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "scripts.lib.identity_carriage.resolve_security_identity",
        lambda symbol, *, root=None: {
            "symbol": str(symbol).upper(),
            "subject_guid": REG,
            "issuer_guid": None,
            "identity_lookup": "RESOLVED",
            "identity_status": "CONFIRMED",
        },
    )
    path = tmp_path / "data" / "cio" / "hermes_research_results.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {
            "event": "HERMES_RESEARCH_COMPLETED",
            "symbol": "NFLX",
            "result_id": f"rr_{i}",
            "research_id": f"res_{i}",
            "summary": f"row {i}",
        }
        for i in range(5)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    import scripts.ops.stamp_hermes_results_last_n as mod

    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: type("NS", (), {
            "root": tmp_path, "n": 5, "dry_run": True, "apply": True, "json": False,
        })(),
    )
    assert mod.main() == 0
    out = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    assert len(out) == 5
    assert all(r.get("subject_guid") == REG for r in out)
    assert all(r.get("identity_backfill") == "hermes_last_n_20260929" for r in out)
