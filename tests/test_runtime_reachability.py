"""Runtime reachability: a library with no caller is not a delivered edge.

Campaign m2-canary-20260907. Lanes G and I each shipped a correct, well-tested
module and no entry point. Every per-lane suite was green, the handoff gate
accepted both, and the integrated candidate 59cd04fa5 still could not produce a
single gateway settlement or inbound consumption, because nothing in the
deployed runtime ever calls them:

    grep -rn deliver_agent_outbound    scripts/  -> no caller
    grep -rn normalize_inbound_update  scripts/  -> no caller

Unit tests prove a function is CORRECT. They say nothing about whether it RUNS.
These gates close that gap: they analyse production source only, and a test file
can never satisfy them.

Deliberately expected to FAIL on 59cd04fa5 and pass only once the runtime wiring
lands. That is the point -- a gate that cannot go red proves nothing.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

#: Production source only. A caller inside tests/ is not a runtime caller.
def _production_files() -> list[Path]:
    return [p for p in SCRIPTS.rglob("*.py") if "test" not in p.name]


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def _calls_and_imports(path: Path) -> tuple[set[str], set[str]]:
    """Names called, and names imported, in one module."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return set(), set()
    calls: set[str] = set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                calls.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                calls.add(fn.attr)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                imports.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                imports.add((a.asname or a.name).split(".")[0])
    return calls, imports


def _reachable_from(entrypoint: Path, target: str, *, max_depth: int = 6) -> list[str]:
    """Call path from entrypoint to `target` through production modules only.

    Follows imports breadth-first. Returns the module chain, or [] if the target
    is never called from anything the entrypoint can reach.
    """
    by_module = {_module_name(p): p for p in _production_files()}
    seen: set[str] = set()
    frontier: list[tuple[Path, list[str]]] = [(entrypoint, [_module_name(entrypoint)])]
    depth = 0
    while frontier and depth < max_depth:
        nxt: list[tuple[Path, list[str]]] = []
        for path, chain in frontier:
            calls, imports = _calls_and_imports(path)
            if target in calls:
                return chain
            for imported in imports:
                for mod, p in by_module.items():
                    if mod in seen:
                        continue
                    if mod.endswith(f".{imported}") or mod.split(".")[-1] == imported:
                        seen.add(mod)
                        nxt.append((p, chain + [mod]))
        frontier = nxt
        depth += 1
    return []


# --- 1. outbound gateway is reachable from the wake runner -------------------

def test_deliver_agent_outbound_has_a_reachable_non_test_caller():
    entry = SCRIPTS / "run_persistent_wake.py"
    assert entry.exists(), "wake runner missing"
    chain = _reachable_from(entry, "deliver_agent_outbound")
    assert chain, (
        "deliver_agent_outbound is never called from run_persistent_wake.py. "
        "Lane G shipped a library with no entry point: the wake hook exists but "
        "nothing constructs the outbound callable, so gateway_settlements can "
        "only ever be 0 no matter how long the soak runs."
    )


# --- 2. inbound is reachable from the canonical poller/webhook ---------------

def _inbound_entrypoints() -> list[Path]:
    """The canonical Telegram callback poller / webhook, whatever it is named."""
    out = []
    for p in _production_files():
        txt = p.read_text(errors="replace")
        if "getUpdates" in txt or "callback_poller" in txt or "webhook" in txt.lower():
            out.append(p)
    return out


def test_normalize_inbound_update_has_a_reachable_non_test_caller():
    entries = _inbound_entrypoints()
    assert entries, "no Telegram poller/webhook found in production source"
    for entry in entries:
        if _reachable_from(entry, "normalize_inbound_update"):
            return
    pytest.fail(
        "normalize_inbound_update is not reachable from any Telegram poller or "
        "webhook. Lane I shipped a normalizer that takes an update dict and "
        "filed no SFR for the ingestion wiring, so inbound_consumptions can "
        f"only ever be 0. Entrypoints searched: {[str(e.relative_to(ROOT)) for e in entries]}"
    )


# --- 3. construction confined to CANARY scope --------------------------------

def test_transport_is_constructed_only_inside_canary_scope():
    """A transport built outside an explicit CANARY guard could send in ACTIVE."""
    # Scope to the GATEWAY transport only. An earlier version matched any
    # `transport=` and flagged three unrelated pre-existing files (moomoo_t2,
    # cio_acceptance_v4, packet_f_moomoo_stage0). A gate that fires on unrelated
    # code trains people to ignore it.
    offenders = []
    for p in _production_files():
        txt = p.read_text(errors="replace")
        if "deliver_agent_outbound" not in txt and "gateway_settlement" not in txt:
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            if "transport=" in line and "None" not in line:
                window = "\n".join(txt.splitlines()[max(0, i - 12):i])
                if "CANARY" not in window:
                    offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, (
        "transport constructed outside an explicit CANARY scope: " + ", ".join(offenders)
    )


# --- 4. fail-closed ----------------------------------------------------------

def test_missing_transport_fails_closed():
    from scripts.lib.gateway_settlement import SettlementError, _require_transport
    with pytest.raises(SettlementError):
        _require_transport(None)


def test_wake_outbound_hook_defaults_to_absent():
    """No injected callable => no delivery path exists at all."""
    import inspect

    from scripts.lib.persistent_agent_wake import WakeEngine

    fields = getattr(WakeEngine, "__dataclass_fields__", {})
    assert "_outbound" in fields, "wake has no outbound injection point"
    default = fields["_outbound"].default
    assert default is None, f"outbound must default to None, got {default!r}"
    src = inspect.getsource(
        __import__("scripts.lib.persistent_agent_wake", fromlist=["x"])
    )
    assert "gateway_settlement" not in src, (
        "the wake module must not import a transport itself; injection only"
    )
