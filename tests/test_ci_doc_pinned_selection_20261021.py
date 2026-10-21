"""PR selection sees tests that pin document text (alignment audit H4, 2026-10-21).

PR #1904 merged a docs edit with `cio-hardening` green: the docs-only (LOW) selection ran the
smoke set, and tests/test_n8n_audit_findings_20261015.py -- which reads
docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md through ``ROOT / "docs" / ... `` -- never ran;
main went red 28 minutes later. scripts/lib/test_impact.py now follows constant path joins
and document strings, and every test that reads a changed document directly is mandatory.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("test_impact_docpin", ROOT / "scripts" / "lib" / "test_impact.py")
ti = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ti)
_spec2 = importlib.util.spec_from_file_location(
    "run_cio_hardening_ci_docpin", ROOT / "scripts" / "run_cio_hardening_ci.py"
)
ci = importlib.util.module_from_spec(_spec2)
assert _spec2.loader is not None
_spec2.loader.exec_module(ci)


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "src,want",
    [
        ('ROOT / "docs" / "a" / "b.md"', {"docs/a/b.md", "docs", "docs/a"}),
        ('X = ROOT / "docs"\nY = X / "a"\nZ = Y / "b.md"', {"docs", "docs/a", "docs/a/b.md"}),
        ('ROOT.joinpath("docs", "a/b.md")', {"docs/a/b.md"}),
        ('Path("docs/a/b.md")', {"docs/a/b.md"}),
        ('Path(__file__).resolve().parents[1] / "AGENTS.md"', {"AGENTS.md"}),
        ('ROOT / name / "x.md"', set()),  # a non-constant segment cannot be resolved
        ("n / 2", set()),
    ],
)
def test_path_join_refs(src, want):
    assert ti._path_join_refs(ast.parse(src)) == want


def test_map_follows_path_joins_and_document_strings(tmp_path):
    root = _write(
        tmp_path,
        {
            "AGENTS.md": "# policy\n",
            "docs/n8n/CONTRACTS.md": "67 effect-keyed lanes\n",
            "docs/n8n/OTHER.md": "x\n",
            "tests/test_join.py": 'ROOT = None\nD = ROOT / "docs" / "n8n"\nTEXT = (D / "CONTRACTS.md").read_text()\n',
            "tests/test_str.py": 'P = "docs/n8n/OTHER.md"\n',
            "tests/test_agents.py": 'A = (ROOT / "AGENTS.md").read_text()\n',
            "tests/test_unrelated.py": "import os\n",
        },
    )
    m = ti.build_map(root)
    assert ti.impacted_tests(["docs/n8n/CONTRACTS.md"], m) == {"tests/test_join.py": 1}
    assert ti.impacted_tests(["docs/n8n/OTHER.md"], m) == {"tests/test_str.py": 1}
    assert ti.impacted_tests(["AGENTS.md"], m) == {"tests/test_agents.py": 1}
    # a reference to a file that does not exist is not an edge
    assert "docs/n8n/MISSING.md" not in m["rdeps"]


def _sel(changed, rdeps, budget=0):
    gates = [("smoke", ["tests/test_s.py"]), ("doc", ["tests/test_doc.py"]), ("other", ["tests/test_o.py"])]
    tiers = {
        "budget_seconds": budget,
        "smoke_gates": ["smoke"],
        "high": {"policy": {"globs": ["AGENTS.md"], "gates": []}},
        "low": {"globs": ["docs/**", "**/*.md"], "gates": []},
    }
    return ti.select(changed, gates, impact_map={"rdeps": rdeps}, tiers=tiers, hints={})


def _files(sel):
    return {f for _n, fs in sel["gates"] for f in fs}


def test_docs_only_change_selects_its_pinning_test_even_with_zero_budget():
    sel = _sel(["docs/a.md"], {"docs/a.md": ["tests/test_doc.py"]})
    assert sel["tier"] == "low"
    assert _files(sel) == {"tests/test_s.py", "tests/test_doc.py"}
    assert sel["doc_pinned"] == ["tests/test_doc.py"] and sel["deferred"] == []


def test_a_docs_change_nobody_pins_still_runs_smoke_only():
    sel = _sel(["docs/b.md"], {"docs/a.md": ["tests/test_doc.py"]})
    assert _files(sel) == {"tests/test_s.py"} and sel["doc_pinned"] == []


def test_only_direct_readers_are_mandatory_not_transitive_ones():
    rdeps = {"docs/a.md": ["scripts/gen.py"], "scripts/gen.py": ["tests/test_o.py"]}
    sel = _sel(["docs/a.md"], rdeps)
    assert sel["doc_pinned"] == [] and "tests/test_o.py" not in _files(sel)


def test_high_tier_document_pins_are_mandatory_over_budget():
    sel = _sel(["AGENTS.md"], {"AGENTS.md": ["tests/test_doc.py", "tests/test_o.py"]}, budget=0)
    assert sel["tier"] == "high"
    assert {"tests/test_doc.py", "tests/test_o.py"} <= _files(sel)
    assert sel["deferred"] == []


# ----------------------------------------------------------------------------- the real repository


@pytest.fixture(scope="module")
def real_map(tmp_path_factory):
    m, _status = ti.load_map(ROOT, tmp_path_factory.mktemp("impact") / "map.json", use_cache=False)
    return m


def _real(changed, real_map):
    return ti.select(
        changed,
        ci.GATES,
        impact_map=real_map,
        tiers=ti.load_tiers(),
        hints=ci.load_duration_hints(),
        default_seconds=1.0,
    )


def test_n8n_contracts_doc_change_selects_the_audit_findings_test(real_map):
    sel = _real(["docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md"], real_map)
    assert "tests/test_n8n_audit_findings_20261015.py" in _files(sel)
    assert "tests/test_n8n_audit_findings_20261015.py" in sel["doc_pinned"]


def test_agents_md_change_selects_the_n8n_onboarding_standard_gate(real_map):
    sel = _real(["AGENTS.md"], real_map)
    gates = {n for n, _f in sel["gates"]}
    assert "n8n_onboarding_standard_20261010" in gates
    assert "tests/test_n8n_onboarding_standard_20261010.py" in sel["doc_pinned"]


def test_schema_bumped_so_a_stale_v1_cache_is_rebuilt(tmp_path):
    root = _write(tmp_path, {"scripts/x.py": "A = 1\n", "tests/test_x.py": "import x\n"})
    cache = tmp_path / "cache.json"
    m, _ = ti.load_map(root, cache)
    m["schema"] = "TestImpactMap@v1"
    cache.write_text(__import__("json").dumps(m), encoding="utf-8")
    assert ti.load_map(root, cache)[1] == "rebuilt"
