"""LQ-20261107-1238 / LQ-20261107-1256: replay corpus schema and runbook resolution (SYNTHETIC fixtures only).

Schema: tests/fixtures/self_heal_runbooks/README.md.

The replay drives every fixture through the LQ-1231 engine (``scripts/lib/self_heal_runbooks.py``) the way the fixer
calls it -- ``plan_runbook(failure_class, evidence, contract, now)``. Three inputs are built here, per fixture,
because a fixture is an INPUT and never a plan:

* ``evidence`` -- the fixture's receipt plus the two names the engine reads (``lane`` and ``signature``). The receipt
  is the fixer's incident record; its fields are copied, never invented.
* ``contract`` -- the lane's synthetic health contract (timeout, freshness threshold). An entry that needs a
  threshold refuses without one, so the replay supplies the one a lane would carry.
* ``now`` -- a fixed clock. Deferral jitter, cooldowns and the idempotency key all depend on ``now``; a replay that
  reads the wall clock proves something different every hour.

The replay resolves all 22 fixtures to a definite plan and prints each fixture's expectation beside the engine's
answer. It also pins, as a ceiling, the signatures the catalog cannot classify yet: those fall through to the K05
catch-all and are reported to the catalog owner (LQ-1231). The ceiling may only shrink -- a NEW unclassified
signature fails this test.

The replay reads no live coordination store (the hermetic guard refuses one under pytest, AGENTS.md §24.6) and no
taxonomy: the corpus is self-contained, and its provenance is recorded in the fixtures README.
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "self_heal_runbooks"
CATALOG = ROOT / "config" / "self_heal_runbook_catalog.json"
ENGINE = ROOT / "scripts" / "lib" / "self_heal_runbooks.py"

#: The replay's clock. A literal, never ``datetime.now()``: the plan's deferral, jitter, cooldown and idempotency
#: key are all functions of this value, and a corpus that changes with the hour proves nothing.
NOW = datetime(2026, 11, 8, 17, 0, tzinfo=timezone.utc)
#: The synthetic lane contract every fixture is replayed against: one lane timeout, one freshness threshold.
CONTRACT_BASELINE = {"timeout_s": 1800, "freshness_failed_after_h": 26}
#: The engine's catch-all. A fixture that resolves here has no catalog entry of its own.
CATCH_ALL = "K05-unclassified-catch-all"
#: Signatures with no catalog entry as of 2026-11-08 (engine/catalog at 647380c2a). These are catalog gaps reported
#: to LQ-1231, not desired behaviour: the engine answers them with the catch-all, which escalates every one of them.
#: This is a CEILING: closing a gap is green, and the id can be deleted; a new unclassified signature fails.
CATALOG_GAPS_20261108 = frozenset({
    "db-error-while-updating",
    "discovery-empty-key",
    "effect-already-claimed",
    "effect-no-owner",
    "env-names-missing",
    "flock-skipped-pid-running",
    "log-path-not-a-directory",
    "output-unverifiable",
    "rollback-connection-closed",
    "setup-step-timeout",
    "timeout-exit-124",
    "upstream-verification-failed",
})

CATEGORIES = frozenset("ABCDEFGHIJK")
TIERS = frozenset({"auto", "auto_notify", "human_only"})
ACTIONS = frozenset({"noop_wait_recheck", "rerun_once_via_gateway", "defer_until", "release_stale_flock",
                     "release_stale_sqlite_wal_lock", "open_breaker_cooldown", "mark_weekend_expected",
                     "escalate_finding"})
ENTRY_ID = re.compile(r"[A-K]-[a-z0-9]+(-[a-z0-9]+)*")
RECEIPT_KEYS = frozenset({"lane_id", "exit_code", "status", "reason", "exception", "failure_class", "ts_et"})
# Public repo: no IPv4 addresses, no e-mail addresses, no token-looking strings in fixtures.
FORBIDDEN = re.compile(r"(\b\d{1,3}(\.\d{1,3}){3}\b|[\w.+-]+@[\w-]+\.[\w.]+|\b(sk|ghp|xox[bp])[-_][A-Za-z0-9]{8,})")


def _fixture_paths() -> list[Path]:
    return sorted(p for p in FIXTURES.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _engine():
    """The LQ-1231 engine, loaded by path (``scripts`` is a namespace package, not importable as a module)."""
    spec = importlib.util.spec_from_file_location("self_heal_runbooks", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence(doc: dict) -> dict:
    """The fixer's incident for this fixture: its receipt, with the two names the engine matches and keys on."""
    receipt = doc["receipt"]
    return dict(receipt, lane=receipt["lane_id"], signature=doc["signature_id"])


def _contract(doc: dict) -> dict:
    return {"lane": doc["receipt"]["lane_id"], "baseline": dict(CONTRACT_BASELINE)}


def _plan(engine, catalog: dict, doc: dict) -> dict:
    return engine.plan_runbook(doc["receipt"]["failure_class"], _evidence(doc), _contract(doc), NOW, catalog=catalog)


def test_fixture_dir_exists_and_schema_doc_is_present():
    assert FIXTURES.is_dir()
    assert (FIXTURES / "README.md").is_file()


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
def test_each_fixture_matches_schema(path: Path):
    doc = _load(path)
    assert doc["fixture_id"] == path.stem
    assert isinstance(doc["signature_id"], str) and doc["signature_id"]
    assert isinstance(doc["taxonomy_signature"], str) and doc["taxonomy_signature"]
    assert isinstance(doc["count_30d"], int) and doc["count_30d"] >= 2
    assert doc["category"] in CATEGORIES
    assert doc["synthetic"] is True
    receipt = doc["receipt"]
    assert RECEIPT_KEYS <= set(receipt), sorted(RECEIPT_KEYS - set(receipt))
    assert isinstance(receipt["exit_code"], int)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", receipt["ts_et"]), receipt["ts_et"]
    expect = doc["expect"]
    assert expect["classified"] is True
    assert expect["category"] == doc["category"]
    assert ENTRY_ID.fullmatch(expect["entry_id"]), expect["entry_id"]
    assert expect["entry_id"].startswith(doc["category"] + "-"), (expect["entry_id"], doc["category"])
    assert expect["action"] in ACTIONS, expect["action"]
    assert expect["tier"] in TIERS
    assert FORBIDDEN.search(path.read_text(encoding="utf-8")) is None, "fixture holds a forbidden pattern"


def test_corpus_has_one_fixture_per_signature_with_count_at_least_two():
    ids = [_load(p)["signature_id"] for p in _fixture_paths()]
    assert len(ids) == len(set(ids)) == 22


def test_replay_resolves_every_fixture_to_a_definite_plan():
    """22/22 fixtures resolve at the fixed clock; the corpus expectation is printed beside each answer.

    The expectation is the corpus's specification, not the engine's contract: where the two differ the replay says
    so per fixture (see the printed table and the DONE note) instead of rewriting either side here.
    """
    engine = _engine()
    catalog = engine.load_catalog(CATALOG)
    paths = _fixture_paths()
    resolved = 0
    matching = 0
    for path in paths:
        doc = _load(path)
        plan = _plan(engine, catalog, doc)
        assert plan["schema"] == engine.PLAN_SCHEMA
        assert plan["at"] == NOW.isoformat(), "the replay must answer at the fixed clock, not the wall clock"
        assert plan["lane"] == doc["receipt"]["lane_id"]
        assert plan["entry"] in catalog, plan["entry"]
        assert plan["action"] in engine.ACTION_WHITELIST, plan["action"]
        assert plan["tier"] in engine.TIERS, plan["tier"]
        assert plan["fallback"] == (plan["entry"] == CATCH_ALL), "fallback flag and catch-all entry disagree"
        again = _plan(engine, catalog, doc)
        assert (again["entry"], again["action"], again["tier"], again["idempotency_key"]) == (
            plan["entry"], plan["action"], plan["tier"], plan["idempotency_key"]
        ), f"{doc['fixture_id']}: the plan is not deterministic at a fixed clock"
        expect = doc["expect"]
        matched = (plan["entry"] == expect["entry_id"] and plan["action"] == expect["action"]
                   and plan["tier"] == expect["tier"])
        print(f"replay {doc['fixture_id']:32s} expect {expect['entry_id']:34s} {expect['action']:26s} "
              f"{expect['tier']:11s} -> got {plan['entry']:24s} {plan['action']:26s} {plan['tier']:11s} "
              f"{'MATCH' if matched else 'DIFF'}")
        resolved += 1
        matching += int(matched)
    print(f"replay resolved {resolved}/{len(paths)} fixtures; {matching}/{len(paths)} match the corpus expectation")
    assert resolved == 22


def test_replay_unclassified_set_cannot_grow():
    """Every signature the catalog cannot classify is already on the known-gaps list; none may be added silently."""
    engine = _engine()
    catalog = engine.load_catalog(CATALOG)
    unclassified = set()
    for path in _fixture_paths():
        doc = _load(path)
        if _plan(engine, catalog, doc)["entry"] == CATCH_ALL:
            unclassified.add(doc["fixture_id"])
    assert unclassified <= CATALOG_GAPS_20261108, (
        f"new signatures with no catalog entry: {sorted(unclassified - CATALOG_GAPS_20261108)}; add an entry to "
        "config/self_heal_runbook_catalog.json (owner LQ-1231), do not widen the gap set"
    )
    closed = sorted(CATALOG_GAPS_20261108 - unclassified)
    if closed:
        print(f"catalog gaps now closed (delete from CATALOG_GAPS_20261108): {closed}")
