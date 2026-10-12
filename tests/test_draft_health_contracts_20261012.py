"""The 66 grandfathered DRAFT health contracts are tested in place.

Status stays DRAFT. scripts/check_n8n_health_contracts.py already rejects a DRAFT
contract on a canary or cutover lane. This test checks the committed file: each
DRAFT row is still DRAFT, no DRAFT row is at canary or cutover, and every
scripts/*.py path the contract names exists.

Hermetic. No network, no n8n, no .env.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))


def _script_paths(contract: dict) -> list[str]:
    found = []
    for item in contract.get("connects_to") or []:
        name = str(item.get("name") or "")
        for token in shlex.split(name):
            if token.startswith("scripts/") and token.endswith(".py"):
                found.append(token)
    return found


def test_checker_accepts_the_committed_drafts():
    from scripts.check_n8n_health_contracts import main

    assert main(["--json"]) == 0


def test_every_draft_contract_stays_draft_and_names_a_real_script():
    drafts = [c for c in DOC["contracts"] if c.get("status") == "DRAFT"]
    assert len(drafts) == 66
    grandfathered = set(DOC["grandfathered_draft"])
    missing = []
    for contract in drafts:
        cid = contract["id"]
        assert cid in grandfathered
        assert contract["status"] == "DRAFT"
        assert contract.get("stage") not in ("canary", "cutover")
        for rel in _script_paths(contract):
            if not (ROOT / rel).is_file():
                missing.append(f"{cid} {rel}")
    assert missing == []
