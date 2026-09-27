"""Ring 1 ratchet: direct silo imports may only shrink (01 §2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_memory_chokepoint as cmc  # noqa: E402


def test_baseline_exists_and_ratchet_holds():
    base = cmc.load_baseline()
    assert base is not None and "files" in base
    new, grew = cmc.ratchet(cmc.scan(), base["files"])
    assert not new, f"new direct memory-silo imports (use scripts/lib/intelligence_client.py): {new}"
    assert not grew, f"direct memory-silo imports grew: {grew}"


def test_facade_itself_is_approved_and_patterns_match():
    assert cmc._approved("scripts/lib/intelligence_client.py")
    assert not cmc._approved("scripts/some_new_silo_reader.py")
    hit = sum(len(p.findall("from agent_durable_memory import get_durable_provider\nimport memory_m2_v2\n")) for p in cmc.PATTERNS)
    assert hit == 2
    assert sum(len(p.findall("import intelligence_client\n")) for p in cmc.PATTERNS) == 0


def test_cli_exit_zero_on_current_tree():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_memory_chokepoint.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
