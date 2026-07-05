#!/usr/bin/env python3
"""White-Space Stage 3 — strategy discovery: catalog, registry diff, payloads.

Covers: the catalog↔registry diff (live equivalents skipped, parked ones
emitted with provenance, empty registry emits everything), the EXACT
meta.strategy_json schema, hard-forced educational/operator flags, lane-legal
domain pins, runner registration, a full dry-run lane pass that writes
nothing, and the no-order-path grep over every Stage-3 owned file.

NOTE: lib.hermes_discovery.strategy_discovery registers the 'strategy' lane
runner at import time, so this module imports it LAZILY (inside fixtures/
tests) and deregisters on teardown — the Stage-1 pool suite asserts that the
lane has no runner by default and must stay green alongside this file.

    .venv/bin/python -m pytest tests/test_hermes_strategy_discovery.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db_adapter  # noqa: E402
from lib.hermes_discovery import worker_pool  # noqa: E402

# The spec's exact meta.strategy_json key set (Part B).
STRATEGY_JSON_KEYS = [
    "strategy_name", "family", "domain", "underlying_type", "required_data",
    "use_case", "risks", "missing_system_components", "required_backtest",
    "required_policy_gate", "educational_only", "operator_review_required",
]

OWNED_FILES = [
    ROOT / "scripts" / "hermes_strategy_discovery.py",
    ROOT / "scripts" / "lib" / "hermes_discovery" / "strategy_discovery.py",
    ROOT / "scripts" / "options_strategy_research.py",
    ROOT / "scripts" / "lib" / "strategy_research" / "__init__.py",
    ROOT / "scripts" / "lib" / "strategy_research" / "options_chain.py",
]


@pytest.fixture
def sd():
    """Lazy import + teardown deregistration (see module NOTE)."""
    from lib.hermes_discovery import strategy_discovery
    strategy_discovery.register()  # idempotent; module import is cached
    yield strategy_discovery
    worker_pool._RUNNERS.pop("strategy", None)


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(db_adapter, "_execute",
                        lambda sql, params=None, fetch=None: [] if fetch else None)


def _registry(tmp_path: Path, entries: dict[str, str]) -> Path:
    d = tmp_path / "strategies"
    d.mkdir()
    for sid, status in entries.items():
        (d / f"{sid}.yaml").write_text(
            f"strategy_id: {sid}\nstatus: {status}\ndisplay_name: X\n",
            encoding="utf-8")
    # schema-style files (no top-level strategy_id string) must be ignored
    (d / "strategy_schema.yaml").write_text(
        "required_fields:\n  - strategy_id\n", encoding="utf-8")
    return d


# ── catalog + strategy_json schema ───────────────────────────────────────────

def test_catalog_seeds_spec_list_and_skips_tax_loss_harvest(sd):
    ids = [e["catalog_id"] for e in sd.STRATEGY_CATALOG]
    assert len(ids) == len(set(ids))
    for expected in ("deep_itm_call", "covered_call", "cash_secured_put",
                     "collar", "leaps_long_call", "synthetic_long",
                     "protective_put", "call_spread", "diagonal_spread",
                     "dividend_capture", "private_company_proxy",
                     "comparable_basket", "sector_etf_proxy", "listed_pe_proxy"):
        assert expected in ids
    assert "tax_loss_harvest" not in ids  # exists in the registry — never seeded


def test_strategy_json_schema_exact(sd):
    for entry in sd.STRATEGY_CATALOG:
        sj = sd.build_strategy_json(entry)
        assert list(sj) == STRATEGY_JSON_KEYS, entry["catalog_id"]
        assert isinstance(sj["required_data"], list) and sj["required_data"]
        assert isinstance(sj["risks"], list) and sj["risks"]
        assert isinstance(sj["missing_system_components"], list)
        assert sj["required_backtest"] and sj["required_policy_gate"]


def test_educational_flags_hard_forced(sd):
    tampered = dict(sd.STRATEGY_CATALOG[0])
    tampered["educational_only"] = False
    tampered["operator_review_required"] = False
    sj = sd.build_strategy_json(tampered)
    assert sj["educational_only"] is True
    assert sj["operator_review_required"] is True


# ── registry diff ────────────────────────────────────────────────────────────

def test_diff_skips_live_equivalent(sd, tmp_path):
    d = _registry(tmp_path, {"covered_call_income": "TESTING"})
    diff = sd.catalog_diff(d)
    skipped = {s["catalog_id"]: s for s in diff["skipped"]}
    assert "covered_call" in skipped
    assert skipped["covered_call"]["registry_id"] == "covered_call_income"
    assert all(e["catalog_id"] != "covered_call" for e in diff["missing"])


def test_diff_emits_parked_equivalent_with_provenance(sd, tmp_path):
    d = _registry(tmp_path, {"covered_call_income": "PARKED"})
    diff = sd.catalog_diff(d)
    entry = next(e for e in diff["missing"] if e["catalog_id"] == "covered_call")
    assert entry["_registry_equivalent"] == "covered_call_income"
    assert entry["_registry_status"] == "PARKED"
    assert diff["skipped"] == []


def test_diff_empty_registry_emits_full_catalog(sd, tmp_path):
    d = _registry(tmp_path, {})
    diff = sd.catalog_diff(d)
    assert len(diff["missing"]) == len(sd.STRATEGY_CATALOG)
    assert diff["registry_ids"] == {}  # schema file ignored


def test_diff_against_real_registry(sd):
    diff = sd.catalog_diff()
    assert "tax_loss_harvest" in diff["registry_ids"]
    # every skipped entry must point at a LIVE registry id
    for s in diff["skipped"]:
        assert diff["registry_ids"][s["registry_id"]] not in sd.PARKED_STATUSES
    assert diff["missing"], "real registry should still leave white space"


# ── payloads ─────────────────────────────────────────────────────────────────

def test_payloads_shape_and_lane_legal_domains(sd, tmp_path):
    d = _registry(tmp_path, {})
    payloads = sd.build_payloads(d)
    assert len(payloads) == len(sd.STRATEGY_CATALOG)
    allowed = set(worker_pool.load_lanes()["strategy"]["allowed_domains"])
    for p in payloads:
        assert p["candidate_type"] == "STRATEGY_CANDIDATE"
        assert p["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
        assert p["normalized_key"].startswith("strategy:")
        assert p["evidence"], "registry-diff evidence required"
        meta = p["meta"]
        assert meta["research_domain"] in allowed, p["label"]
        sj = meta["strategy_json"]
        assert list(sj) == STRATEGY_JSON_KEYS
        assert sj["educational_only"] is True
        assert sj["operator_review_required"] is True
        assert sj["domain"] == meta["research_domain"]


def test_parked_equivalent_stamped_into_meta(sd, tmp_path):
    d = _registry(tmp_path, {"covered_call_income": "PARKED"})
    p = next(x for x in sd.build_payloads(d)
             if x["meta"]["catalog_id"] == "covered_call")
    assert p["meta"]["registry_equivalent"] == "covered_call_income"
    assert p["meta"]["registry_status"] == "PARKED"
    assert len(p["evidence"]) == 2


# ── lane runner ──────────────────────────────────────────────────────────────

def test_import_registers_strategy_lane_runner(sd):
    assert worker_pool.get_lane_runner("strategy") is sd.strategy_lane_runner
    sd.register()  # idempotent (replace=True) — must not raise


def test_dry_run_lane_pass_writes_nothing(sd, no_db, tmp_path):
    report = worker_pool.run_lane("strategy", dry_run=True,
                                  lock_dir=tmp_path / "locks",
                                  state_path=tmp_path / "state.json")
    assert "error" not in report
    assert report["dry_run"] is True
    assert report["upserted"] == 0
    assert report["scanned"] == len(sd.build_payloads())
    cap = worker_pool.load_lanes()["strategy"]["max_candidates_per_run"]
    assert len(report["candidates"]) <= cap
    assert report["skipped_reasons"].get("lane_run_cap") == report["scanned"] - cap
    # no fenced domains: every payload pins a lane-allowed research domain
    assert not any(k.startswith("lane_domain") for k in report["skipped_reasons"])
    assert not (tmp_path / "state.json").exists()  # dry runs leave no state


def test_runner_is_read_only(sd, monkeypatch):
    """The runner itself must never touch the DB — the pool owns all writes."""
    def _boom(*a, **k):
        raise AssertionError("runner touched the DB")
    monkeypatch.setattr(db_adapter, "_execute", _boom)
    payloads = sd.strategy_lane_runner({"lane_id": "strategy"}, dry_run=False)
    assert payloads and all(p["candidate_type"] == "STRATEGY_CANDIDATE"
                            for p in payloads)


# ── HARD RULE: no order / submit / approval path anywhere in Stage-3 files ───

FORBIDDEN = re.compile(
    r"place_order|cancel_order|replace_order|submit_order|submit_oco"
    r"|orderLegCollection|order_spec|execution_guard|evidence_approval"
    r"|approval_queue|trade_queue|NotProvenWrite|require\(intent"
    r"|schwab_oco_bracket|options_pilot_arm|alpaca_trade_api", re.IGNORECASE)


def test_no_order_path_grep():
    for path in OWNED_FILES:
        text = path.read_text(encoding="utf-8")
        hit = FORBIDDEN.search(text)
        assert hit is None, f"{path.name}: forbidden token {hit.group(0)!r}"


def test_no_execution_module_imports():
    import ast
    deny = {"execution_guard", "schwab_oco_bracket", "options_pilot_arm",
            "trade_executor", "order_manager", "alpaca_trade_api", "brokers"}
    for path in OWNED_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for m in mods:
                root = m.split(".")[0]
                assert root not in deny, f"{path.name} imports {m}"
