#!/usr/bin/env python3
"""Step-7 isolation — the scalp engine can neither import nor reference any proposal/order path.

Two AST passes over every scalp-engine module:
  (1) IMPORT NODES — no import of an order/proposal/adapter module.
  (2) STRING LITERALS with DOCSTRINGS STRUCTURALLY EXCLUDED — no literal names the
      `paper_trade_proposals` table (a SQL write would need the string), catching dynamic use that a
      raw grep would miss AND avoiding the false positive from the modules' negative "does NOT touch"
      docstrings.
Plus the M3-S4 mutual-isolation rule: the outcome backfill and the rollup import NEITHER the scorer
NOR the shadow logger, and vice-versa."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

ENGINE_MODULES = [
    "symbol_volume_profile_builder.py",
    "scalp_t0_metrics.py",
    "scalp_ignition_scorer.py",
    "scalp_trigger_engine.py",
    "scalp_shadow_logger.py",
    "scalp_shadow_outcome_backfill.py",
    "scalp_shadow_rollup.py",
    "scalp_trigger_r_diagnostics.py",
    "market_observations/observation.py",
    "market_observations/concurrency.py",
    "market_observations/arbitration.py",
    "market_observations/providers.py",
    "market_observations/fabric.py",
]

FORBIDDEN_IMPORT_SUBSTR = (
    "paper_trade_proposals", "alpaca_paper_adapter", "alpaca_adapter",
    "auto_proposal", "proposal_generator", "order_submit", "submit_order", "order_manager",
)
FORBIDDEN_STRING_SUBSTR = ("paper_trade_proposals",)


def _tree(name: str) -> ast.AST:
    return ast.parse((SCRIPTS / name).read_text(encoding="utf-8"), filename=name)


def _import_targets(tree: ast.AST) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
            names += [f"{node.module or ''}.{a.name}" for a in node.names]
    return names


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """id() of every Constant node that is a docstring (first stmt of Module/Class/Func)."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def _non_docstring_strings(tree: ast.AST) -> list[str]:
    doc = _docstring_nodes(tree)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc]


@pytest.mark.parametrize("mod", ENGINE_MODULES)
def test_no_forbidden_imports(mod):
    for tgt in _import_targets(_tree(mod)):
        low = tgt.lower()
        assert not any(f in low for f in FORBIDDEN_IMPORT_SUBSTR), f"{mod} imports forbidden: {tgt}"


@pytest.mark.parametrize("mod", ENGINE_MODULES)
def test_no_forbidden_string_literals_excluding_docstrings(mod):
    tree = _tree(mod)
    for s in _non_docstring_strings(tree):
        low = s.lower()
        assert not any(f in low for f in FORBIDDEN_STRING_SUBSTR), \
            f"{mod} has a non-docstring literal naming a forbidden target: {s[:60]!r}"


def test_backfill_and_rollup_do_not_import_scorer_or_logger():
    for mod in ("scalp_shadow_outcome_backfill.py", "scalp_shadow_rollup.py"):
        tgts = " ".join(_import_targets(_tree(mod))).lower()
        assert "scalp_ignition_scorer" not in tgts, f"{mod} must not import the scorer"
        assert "scalp_shadow_logger" not in tgts, f"{mod} must not import the logger"


def test_scorer_and_logger_do_not_import_backfill_or_rollup():
    for mod in ("scalp_ignition_scorer.py", "scalp_shadow_logger.py"):
        tgts = " ".join(_import_targets(_tree(mod))).lower()
        assert "outcome_backfill" not in tgts, f"{mod} must not import the backfill"
        assert "scalp_shadow_rollup" not in tgts, f"{mod} must not import the rollup"


def test_docstring_exclusion_actually_excludes():
    # sanity: the logger DOES mention the forbidden table in its docstring (negative statement),
    # and the string scan must NOT flag it (proves docstrings are excluded structurally).
    tree = _tree("scalp_shadow_logger.py")
    doc_blob = " ".join(v.value for v in ast.walk(tree)
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                        and id(v) in _docstring_nodes(tree))
    assert "paper_trade_proposals" in doc_blob          # it's there in the docstring
    assert "paper_trade_proposals" not in " ".join(_non_docstring_strings(tree)).lower()  # but excluded


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
