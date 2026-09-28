"""m2_substrate_check — pure parts (no database): the structure differ, the finding rules, the production refusal."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import m2_substrate_check as chk  # noqa: E402


def test_refuse_production_port():
    for bad in ("postgresql://u:p@127.0.0.1:5432/trade_ai", "postgresql://u:p@localhost:5432", "host=x port=5432"):
        with pytest.raises(RuntimeError, match="PRODUCTION_PORT_FORBIDDEN"):
            chk.refuse_production(bad)
    chk.refuse_production("postgresql://m2:x@127.0.0.1:55432/m2_shadow_test")   # isolated port passes


def test_diff_structure_names_every_difference():
    a = {"columns": {"v": ["a:text", "b:int"], "only_prod": ["x:text"]}, "functions": {"f": "def1"}}
    b = {"columns": {"v": ["a:text", "b:bigint"]}, "functions": {"f": "def1", "g": "def2"}}
    d = chk.diff_structure(a, b)
    kinds = {(x["section"], x["name"]): x["kind"] for x in d}
    assert kinds == {("columns", "v"): "differs", ("columns", "only_prod"): "missing_in_shadow", ("functions", "g"): "missing_in_production"}
    assert chk.diff_structure(a, a) == []


def test_findings_rules():
    rls = {"memory_fact_version": {"enabled": True, "forced": True, "policies": 1},
           "provenance_edge": {"enabled": True, "forced": False, "policies": 1},
           "memory_identity": {"enabled": False, "forced": False, "policies": 0}}
    counts = {"MemoryFactVersion@v2": {"base": 10, "view": 0, "tenant": "t"}, "ProvenanceEdge@v1": {"base": 0, "view": 0, "tenant": "t"},
              "MemoryIdentity@v1": {"base": 5, "view": 5, "tenant": "t"}}
    f = {x["finding"] for x in chk.findings_from(rls, counts)}
    assert f == {"RLS_POLICIES_ABSENT:provenance_edge", "RLS_POLICIES_ABSENT:memory_identity", "VIEW_EMPTY_BASE_POPULATED:MemoryFactVersion@v2"}
    assert chk.findings_from({}, {}) == []


def test_module_declares_no_consumer_reason_and_views_map():
    assert chk.NO_CONSUMER_REASON and set(chk.VIEWS.values()) == {"memory_identity", "memory_fact_version", "adjudication_receipt", "provenance_edge"}
