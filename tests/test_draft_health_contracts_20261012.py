"""Grandfathered DRAFT health contracts are tested in place.

The count is not pinned. Every contract that is still DRAFT must be in
grandfathered_draft. A grandfathered id may later be REVIEWED; that is an
operator act and is not put back to DRAFT here. scripts/check_n8n_health_contracts.py
rejects a DRAFT contract on a canary or cutover lane. This test checks the same
file: no DRAFT row is at canary or cutover, and every scripts/*.py path the
contract names exists.

Hermetic. No network, no n8n, no .env.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
_SCRIPT = re.compile(r"(?<![A-Za-z0-9_])scripts/[A-Za-z0-9_./-]+\.py")


def _script_paths(contract: dict) -> list[str]:
    found = []
    for item in contract.get("connects_to") or []:
        found.extend(_SCRIPT.findall(str(item.get("name") or "")))
    return found


def test_checker_accepts_the_committed_drafts():
    from scripts.check_n8n_health_contracts import main

    assert main(["--json"]) == 0


def test_every_draft_contract_stays_draft_and_names_a_real_script():
    from scripts.lib.n8n_health_contracts import stage_of

    contracts = {c["id"]: c for c in DOC["contracts"]}
    drafts = [c for c in contracts.values() if c.get("status") == "DRAFT"]
    draft_ids = {c["id"] for c in drafts}
    grandfathered = set(DOC["grandfathered_draft"])
    rows = {r["lane_id"]: r for r in REGISTRY["lanes"]}
    assert draft_ids <= grandfathered
    for cid in (grandfathered & set(contracts)) - draft_ids:
        assert contracts[cid]["status"] == "REVIEWED"
    missing = []
    for contract in drafts:
        cid = contract["id"]
        assert cid in grandfathered
        assert contract["status"] == "DRAFT"
        assert contract.get("stage") not in ("canary", "cutover")
        assert stage_of(rows.get(cid)) not in ("canary", "cutover")
        for rel in _script_paths(contract):
            if not (ROOT / rel).is_file():
                missing.append(f"{cid} {rel}")
    assert missing == []
