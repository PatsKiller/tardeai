"""Every identity/memory module must have a production consumer — Phase D.

The identity and memory area accumulated 32 modules, and the recurring defect was
never a bad design: it was building a contract and never wiring the caller. On
2026-08-27 that pattern was found four times in one day — `position_truth` built
and never called, `complete_to_checkpoint` computed and read by nothing,
`production_root_map` reporting a real fault nobody consumed, and the identity
spine itself specified to four levels with zero production writers.

Each of those passed its own unit tests. That is precisely why unit tests did not
catch them, and why this guard is structural rather than behavioural: it asserts
that a module is *reachable from production code*, which no amount of testing the
module in isolation can establish.

A new module must therefore either be wired to a caller under `scripts/` or be
declared below with a reason. The declaration is the point — it forces the choice
to be conscious instead of accidental.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "scripts" / "lib"

# Modules in this area. Narrow on purpose: the guard is only credible where the
# recurrence actually happened.
PATTERN = re.compile(r"identity|memory|lineage|graph")

# Lab and benchmark harnesses. These legitimately have no production consumer --
# measuring a thing is not the same as running it -- and each says so in its own
# docstring. Not a backlog.
BENCHMARK_OR_LAB = {
    "memory_m2_v2",                    # isolated M2 harness, refuses production :5432
    "memory_vector_index_benchmark",   # deterministic vector-index harness
    "langgraph_complexity_gate",       # measures whether to adopt LangGraph at all
    "memory_consolidator_shadow",      # SHADOW-ONLY consolidator schedule, MBI=0
}

# Real gaps: written, tested, and reachable from nothing that runs. This set must
# shrink or hold — never grow. Adding to it is an explicit admission, which is
# the behaviour this guard is trying to produce.
KNOWN_DARK = {
    # Gate-B agent alias resolution (guardian/ledger vs legacy risk_agent/tax_agent).
    # Test-only. Retire or wire during the Gate-B follow-up; deleting it blind
    # risks dropping a governance assumption nothing else encodes.
    "cio_identity_resolver",
    # Immutable decision disposition identity. Test-only. Supersedes the legacy
    # position:<symbol>:<account> key, and wants a consumer on the decision path.
    "cio_disposition_identity",
}


def _modules() -> list[str]:
    return sorted(
        p.stem for p in LIB.glob("*.py")
        if not p.stem.startswith("_") and PATTERN.search(p.stem)
    )


def _production_consumers(module: str) -> set[str]:
    """Files under scripts/ that reference the module, excluding itself.

    Tests are deliberately not counted. A module whose only caller is its own
    test suite is exercised, not used — which is the exact failure mode here.
    """
    hits: set[str] = set()
    needle = module
    for path in (ROOT / "scripts").rglob("*.py"):
        if path.name == f"{module}.py":
            continue
        try:
            if needle in path.read_text(encoding="utf-8", errors="ignore"):
                hits.add(str(path.relative_to(ROOT)))
        except OSError:
            continue
    return hits


def test_no_new_dark_identity_or_memory_modules():
    """A new module must be wired, or explicitly declared as lab/known-dark."""
    dark = {m for m in _modules() if not _production_consumers(m)}
    undeclared = dark - BENCHMARK_OR_LAB - KNOWN_DARK

    assert not undeclared, (
        "These identity/memory modules have no production consumer and are not "
        "declared:\n  " + "\n  ".join(sorted(undeclared)) +
        "\n\nWire one, or add it to BENCHMARK_OR_LAB (a harness) / KNOWN_DARK (a "
        "tracked gap) with a reason. Building a contract and never wiring the "
        "caller is the defect this guard exists to catch."
    )


def test_known_dark_set_does_not_grow():
    """KNOWN_DARK is a debt register. It may shrink; it may not grow silently."""
    assert len(KNOWN_DARK) <= 2, (
        "KNOWN_DARK grew. Each entry is a module that is written, tested and "
        "unreachable from anything that runs — adding another means the pattern "
        "is still happening."
    )


def test_declared_dark_modules_are_still_dark():
    """Once wired, a module must leave the register — stale entries hide progress."""
    still_dark = {m for m in KNOWN_DARK if not _production_consumers(m)}
    resolved = KNOWN_DARK - still_dark

    assert not resolved, (
        f"These are no longer dark and should be removed from KNOWN_DARK: {sorted(resolved)}"
    )


def test_the_spine_is_wired():
    """The modules Phases A–C switched on must stay switched on.

    security_identity and memory_fact were specified for months with no
    production writer; identity_registry and catalyst_graph are what changed
    that. A regression here means the spine went dark again.
    """
    for module in ("security_identity", "identity_registry", "memory_fact",
                   "event_identity", "catalyst_graph"):
        assert _production_consumers(module), f"{module} has lost its production consumer"
