"""The n8n lane cio-prospect-shadow at SHADOW (ANCHOR CIO_PROSPECT_SHADOW_LANE_20261022).

Stacked on the CIO prospect foundation PR (AGENTS.md §26). The lane runs scripts/cio_prospect_shadow_build.py
--with-db --dry-run every 30 min in market hours; the dispatcher's stage clamp forces dry_run and the allowlist has
live_arg null, so a fire prints and writes nothing. Its health contract is DRAFT until the cio owner marks it
REVIEWED (AGENTS.md §23.19) — the contract gates fail until then, by design; canary (--write-shadow) is a later
registry PR.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _row(path: str, key: str, lane: str, coll: str = "lanes") -> dict:
    return next(r for r in json.loads((ROOT / path).read_text())[coll] if r.get(key) == lane)


def test_lane_is_registered_at_shadow_and_dry_run_only():
    reg = _row("config/lane_registry.json", "lane_id", "cio-prospect-shadow")
    assert reg["scheduler"]["kind"] == "n8n" and reg["scheduler"]["expression"] == "dispatcher"
    assert reg["scheduler"]["stage"] == "shadow" and reg["dispatch"]["mode"] == "dry_run"
    assert reg["dispatch"]["class"] == "report" and reg["scheduler"]["match"] == "scripts/cio_prospect_shadow_build.py"
    al = _row("config/n8n_run_allowlist.json", "lane_id", "cio-prospect-shadow")
    assert al["live_arg"] is None and al["dry_run_arg"] == ["--dry-run"]
    assert al["command"] == ["$PY", "scripts/cio_prospect_shadow_build.py", "--with-db"]
    assert not any(n.startswith(("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR", "TELEGRAM"))
                   for n in al["env_names"])
    c = _row("config/n8n_health_contracts.json", "id", "cio-prospect-shadow", "contracts")
    # Operator approve-all item F (2026-10-22): contract REVIEWED; stage stays shadow.
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow" and c["workflow_id"] == "dispatcher"
    assert c["healthy"][0]["check"] == "dry_run_writes_nothing"


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/cio_prospect_shadow_lane_20261022.json").read_text())
    assert doc["anchor"] == "CIO_PROSPECT_SHADOW_LANE_20261022"
    assert "tests/test_cio_prospect_shadow_lane_20261022.py" in doc["files"]
