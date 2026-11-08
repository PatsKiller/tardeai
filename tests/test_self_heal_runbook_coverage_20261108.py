"""LQ-20261107-1238: replay corpus schema and runbook coverage (SYNTHETIC fixtures only).

Schema: tests/fixtures/self_heal_runbooks/README.md. The coverage replay needs the taxonomy
(SELFHEAL-FAILURE-TAXONOMY-20261108.json, LQ-1237) and the engine (scripts/lib/self_heal_runbooks.py, LQ-1231);
until both exist the replay test skips with the reason shown.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "self_heal_runbooks"
COORD = Path(os.environ.get("TRADEAI_COORDINATION_DIR", "/nonexistent-coordination-dir"))
TAXONOMY = COORD / "SELFHEAL-FAILURE-TAXONOMY-20261108.json"
CATALOG = ROOT / "config" / "self_heal_runbook_catalog.json"
ENGINE = ROOT / "scripts" / "lib" / "self_heal_runbooks.py"

CATEGORIES = frozenset("ABCDEFGHIJK")
TIERS = frozenset({None, "auto", "auto_notify", "human_only"})
RECEIPT_KEYS = frozenset({"lane_id", "exit_code", "status", "reason", "exception", "failure_class", "ts_et"})
# Public repo: no IPv4 addresses, no e-mail addresses, no token-looking strings in fixtures.
FORBIDDEN = re.compile(r"(\b\d{1,3}(\.\d{1,3}){3}\b|[\w.+-]+@[\w-]+\.[\w.]+|\b(sk|ghp|xox[bp])[-_][A-Za-z0-9]{8,})")


def _fixture_paths() -> list[Path]:
    return sorted(p for p in FIXTURES.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixture_dir_exists_and_schema_doc_is_present():
    assert FIXTURES.is_dir()
    assert (FIXTURES / "README.md").is_file()


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
def test_each_fixture_matches_schema(path: Path):
    doc = _load(path)
    assert doc["fixture_id"] == path.stem
    assert isinstance(doc["signature_id"], str) and doc["signature_id"]
    assert doc["category"] in CATEGORIES
    assert doc["synthetic"] is True
    receipt = doc["receipt"]
    assert RECEIPT_KEYS <= set(receipt), sorted(RECEIPT_KEYS - set(receipt))
    assert isinstance(receipt["exit_code"], int)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", receipt["ts_et"]), receipt["ts_et"]
    expect = doc["expect"]
    assert expect["classified"] is True
    assert expect.get("tier") in TIERS
    assert FORBIDDEN.search(path.read_text(encoding="utf-8")) is None, "fixture holds a forbidden pattern"


@pytest.mark.skipif(not (TAXONOMY.exists() and CATALOG.exists() and ENGINE.exists()),
                    reason="needs LQ-1237 taxonomy, LQ-1231 catalog and engine (not on origin/main yet)")
def test_replay_zero_unclassified_and_print_coverage():
    import importlib.util

    spec = importlib.util.spec_from_file_location("self_heal_runbooks", ENGINE)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    counted = {s["signature_id"] for s in taxonomy.get("signatures", []) if s.get("count", 0) >= 2}
    have = {_load(p)["signature_id"] for p in _fixture_paths()}
    assert counted <= have, sorted(counted - have)
    unclassified = []
    per_category: dict[str, list[int]] = {}
    for path in _fixture_paths():
        doc = _load(path)
        plan = engine.plan_runbook(doc["receipt"])
        ok = plan is not None and getattr(plan, "status", None) != "unclassified"
        per_category.setdefault(doc["category"], []).append(1 if ok else 0)
        if not ok:
            unclassified.append(doc["fixture_id"])
    for cat in sorted(per_category):
        vals = per_category[cat]
        print(f"coverage {cat}: {sum(vals)}/{len(vals)} = {100 * sum(vals) // len(vals)}%")
    assert unclassified == []
