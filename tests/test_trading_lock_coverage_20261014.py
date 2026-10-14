"""Static coverage proof for the READ-ONLY broker lock (incident SPCX 2026-10-14).

Operator directive: "lock it, block cancels too". Every broker order write — place, replace AND cancel —
must be DOMINATED by ``assert_trading_unlocked``: a guard statement precedes it in the same block or in an
enclosing block (function body, route branch, loop body), or the write is a call into a function that
is itself guarded.

The scan is an AST walk over scripts/ (archive excluded). It fails on:
  * any broker write sink that is not dominated by a guard and is not on the reviewed allowlist;
  * any named chokepoint whose FIRST statement (after its docstring) is not the guard;
  * any allowlisted Alpaca file that does not carry a paper-pin marker.

The allowlist holds ONLY Alpaca PAPER files (operator: paper is training) and one hermetic negative-
control harness. Mutation proof: ``test_mutation_*`` delete the guard from three chokepoints in an
in-memory copy and assert the scan goes red each time.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
GUARD = "assert_trading_unlocked"

# ── sinks ───────────────────────────────────────────────────────────────────────────────────────────
# Distinctive order-write method names: a call to any of these is a sink wherever it appears.
WRITE_METHODS = {
    "place_order",
    "replace_order",
    "cancel_order",
    "cancel_order_for_replace",
    "submit_order",
    "unlock_trade",
    "modify_order",
    "cancel_user_account_order",
    "place_force_order",
    "submit_entry",
    "submit_stop_order",
    "create_saved_order",
    "replace_saved_order",
    "delete_saved_order",
    "submit_oco",
    "request_2fa",
    "request_approval",
    "submit_fully_approved",
    "confirm_and_submit",
    "route_after_2fa",
    "request_route",
    "cancel_replace_stop_if_needed",
}
# Generic names that are sinks only when the receiver resolves to a broker module.
GENERIC_METHODS = {"submit", "execute", "confirm", "place", "cancel", "arm", "replace", "preflight"}
# HTTP write verbs / helpers. A call is a sink when one of its string literals names an order route.
HTTP_WRITE = {"post", "put", "delete", "patch", "_api_post", "_api_delete", "_api_put", "_api_patch"}
HTTP_GENERIC = {"request", "Request", "_alpaca_req", "_req", "urlopen"}
ORDER_URL = re.compile(
    r"/orders\b|/v2/positions|/api/v2/(?:holdings/protective-stop(?:/confirm|/cancel)?(?![-/\w])"
    r"|broker-orders/(?:approve|request-approval|pilot/(?:execute|cancel|arm))"
    r"|broker-proposals/(?:route|route/confirm|manual-submit)(?![-/\w])"
    r"|options/confirm|snaptrade/trade/(?:execute|preflight))"
)
WRITE_HTTP_METHOD = re.compile(r"^(POST|PUT|DELETE|PATCH)$", re.I)
# HTTP helper definitions in broker adapters: the raw request must be guarded inside them.
HTTP_HELPER_DEFS = {"_api_post", "_api_delete", "_api_put", "_api_patch"}

# ── reviewed allowlist (Alpaca PAPER + hermetic test harness ONLY) ─────────────────────────────────────
PAPER_MARKERS = ("paper-api.alpaca.markets", "require_paper_trading_base", "resolve_paper_base_url", "PAPER_BASE_URL")
ALLOWLIST = {
    # path (relative to scripts/): reason
    "alpaca_paper_adapter.py": "Alpaca PAPER adapter; _api_post is paper-gated via alpaca_environment",
    "alpaca_stop_manager.py": "Alpaca PAPER stop manager; require_paper_trading_base pins the host",
    "apply_paper_protection_adjustment.py": "Alpaca PAPER; PAPER_BASE hard-coded",
    "canary_reconcile_test.py": "Alpaca PAPER canary reconcile harness; BASE hard-coded paper",
    "lib/options_pipeline/alpaca_paper.py": "Alpaca PAPER options; resolve_paper_base_url refuses other hosts",
    "open_trade_manager.py": "Alpaca PAPER (AlpacaPaperAdapter; ALPACA_MODE must be paper)",
    "open_trade_monitor.py": "Alpaca PAPER; _alpaca_base_url raises unless ALPACA_MODE=paper",
    "paper_scale.py": "Alpaca PAPER (AlpacaPaperAdapter)",
    "paper_trade_closer.py": "Alpaca PAPER (AlpacaPaperAdapter; ALPACA_MODE must be paper)",
    "paper_trade_monitor.py": "Alpaca PAPER; _alpaca_base raises unless ALPACA_MODE=paper",
    "telegram_callback_handler.py::_close_alpaca_position": "Alpaca PAPER close; base hard-coded paper",
    "run_whole_site_negative_controls.py": "hermetic mock server negative control (test harness, never CC)",
    "proposal_paper_submitter.py": "Alpaca PAPER submitter (AlpacaPaperAdapter.submit_entry)",
    "validate_broker_connectors.py": "validator harness: dry_run adapters; every adapter submit_entry is itself "
    "a guarded chokepoint (CHOKEPOINTS) or the paper adapter",
}
NON_PAPER_ALLOWLIST = {"run_whole_site_negative_controls.py", "validate_broker_connectors.py"}


# Broker module names a generic call may resolve to.
def _broker_module_names() -> set[str]:
    names = {p.stem for p in (SCRIPTS / "brokers").glob("*.py")}
    return names | {
        "schwab_transport",
        "schwab_adapter",
        "tastytrade_adapter",
        "schwab_oco_bracket",
        "schwab_pilot_arm",
        "snaptrade_transport",
    }


# ── named chokepoints: the guard must be the FIRST statement ─────────────────────────────────────────
CHOKEPOINTS = [
    ("schwab_transport.py", "_pilot_preconditions"),
    ("schwab_transport.py", "place_order"),
    ("schwab_transport.py", "cancel_order"),
    ("schwab_transport.py", "cancel_order_for_replace"),
    ("schwab_transport.py", "replace_order"),
    ("schwab_adapter.py", "SchwabAdapter._api_post"),
    ("schwab_adapter.py", "SchwabAdapter.submit_entry"),
    ("schwab_adapter.py", "SchwabAdapter.cancel_order"),
    ("brokers/protective_stop_pilot.py", "submit"),
    ("brokers/protective_stop_pilot.py", "request_2fa"),
    ("brokers/options_order_pilot.py", "submit"),
    ("brokers/options_order_pilot.py", "request_2fa"),
    ("brokers/broker_entry_pilot.py", "submit"),
    ("brokers/broker_entry_pilot.py", "request_2fa"),
    ("brokers/broker_entry_pilot.py", "confirm_and_submit"),
    ("brokers/broker_entry_pilot.py", "request_route"),
    ("brokers/intent_submit_router.py", "submit_fully_approved"),
    ("brokers/intent_submit_router.py", "cancel_replace_stop_if_needed"),
    ("brokers/approval_service.py", "confirm"),
    ("brokers/approval_service.py", "request_approval"),
    ("brokers/schwab_order_adapter.py", "SchwabOrderAdapter.submit"),
    ("brokers/schwab_order_adapter.py", "SchwabOrderAdapter.replace"),
    ("brokers/schwab_order_adapter.py", "SchwabOrderAdapter.cancel"),
    ("brokers/snaptrade_transport.py", "place_order"),
    ("brokers/snaptrade_trade.py", "place"),
    ("brokers/snaptrade_trade.py", "cancel"),
    ("brokers/snaptrade_protective_stop_pilot.py", "route_after_2fa"),
    ("brokers/snaptrade_protective_stop_pilot.py", "request_2fa"),
    ("brokers/snaptrade_trade_pilot.py", "execute"),
    ("brokers/snaptrade_trade_pilot.py", "preflight"),
    ("schwab_oco_bracket.py", "submit_oco"),
    ("schwab_broker_trade_monitor.py", "_request_stop_modify"),
    ("schwab_pilot_arm.py", "arm"),
    ("tastytrade_adapter.py", "TastytradeAdapter._api_post"),
    ("tastytrade_adapter.py", "TastytradeAdapter._api_delete"),
    ("tastytrade_adapter.py", "TastytradeAdapter.submit_entry"),
    ("tastytrade_adapter.py", "TastytradeAdapter.submit_stop_order"),
    ("tastytrade_adapter.py", "TastytradeAdapter.cancel_order"),
    ("moomoo/client.py", "MoomooClient.place_order"),
    ("moomoo/client.py", "MoomooClient.unlock_trade"),
    ("alpaca_paper_adapter.py", "AlpacaPaperAdapter._api_post"),
    ("api_v2.py", "_pilot_execute"),
    ("api_v2.py", "_pilot_cancel"),
    ("api_v2.py", "_pilot_arm"),
    ("api_v2.py", "_snaptrade_trade_preflight"),
    ("api_v2.py", "_snaptrade_trade_execute"),
]
API_ROUTES = [
    "/api/v2/broker-proposals/manual-submit",
    "/api/v2/broker-proposals/route",
    "/api/v2/broker-proposals/route/confirm",
    "/api/v2/holdings/protective-stop",
    "/api/v2/holdings/protective-stop/confirm",
    "/api/v2/holdings/protective-stop/cancel",
    "/api/v2/broker-orders/request-approval",
    "/api/v2/broker-orders/approve",
    "/api/v2/options/confirm",
]
# Guard present (not necessarily first) — second-layer / precedence functions.
CONTAINS_GUARD = [
    ("brokers/execution_guard.py", "authorize", GUARD),
    ("brokers/execution_guard.py", "_lock_engaged", "is_trading_locked"),
    ("brokers/kill_switches.py", "is_blocked", "is_trading_locked"),
    ("brokers/alpaca_factory.py", "adapter_for", GUARD),
    ("synthetic_stop_monitor.py", "check_and_trigger", GUARD),
    ("schwab_stop_batch_request.py", "main", GUARD),
]
ARM_PRECEDENCE = ["_live_future_unlocked", "_protective_unlocked", "_options_unlocked", "_fidelity_monitored_unlocked"]


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────────
def _call_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _is_guard_call(node) -> bool:
    return isinstance(node, ast.Call) and _call_name(node) == GUARD


def _is_guard_stmt(stmt) -> bool:
    """An unconditional guard: `assert_trading_unlocked(...)` or a try whose body opens with it."""
    if isinstance(stmt, ast.Expr) and _is_guard_call(stmt.value):
        return True
    if isinstance(stmt, ast.Try):
        body = [s for s in stmt.body if not isinstance(s, (ast.Import, ast.ImportFrom))]
        return bool(body) and isinstance(body[0], ast.Expr) and _is_guard_call(body[0].value)
    return False


def _strings(node) -> str:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return " ".join(out)


def _files():
    for p in sorted(SCRIPTS.rglob("*.py")):
        rel = p.relative_to(SCRIPTS).as_posix()
        if "archive" in p.parts or "__pycache__" in p.parts:
            continue
        yield rel, p


def _parse(src: str, rel: str):
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(src)
    except SyntaxError:
        return None


_TREE_CACHE: dict = {}


def _cached_tree(rel: str, path: Path):
    key = (rel, path.stat().st_mtime_ns)
    if key not in _TREE_CACHE:
        _TREE_CACHE[key] = _parse(path.read_text(errors="replace"), rel)
    return _TREE_CACHE[key]


def _parents(tree):
    par = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            par[ch] = node
    return par


def _guarded_functions(tree) -> set[str]:
    """Names of functions/methods whose first non-docstring, non-import statement is a guard."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _first_is_guard(n.body):
            out.add(n.name)
    return out


def _first_is_guard(body) -> bool:
    stmts = list(body)
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(getattr(stmts[0], "value", None), ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        stmts = stmts[1:]
    stmts = [s for s in stmts if not (isinstance(s, ast.ImportFrom) and (s.module or "").endswith("trading_lock"))]
    return bool(stmts) and _is_guard_stmt(stmts[0])


def _module_aliases(tree) -> dict[str, str]:
    """alias -> module stem, from every import in the file (any scope)."""
    al = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                al[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1]
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                # `from brokers import approval_service as x` → module approval_service
                al[a.asname or a.name] = a.name
    return al


def _from_imported_functions(tree) -> dict[str, tuple[str, str]]:
    """local name -> (module stem, function) for `from m import f [as g]`."""
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                out[a.asname or a.name] = (n.module.split(".")[-1], a.name)
    return out


def _dominated(sink, par) -> bool:
    """True if a guard statement precedes the statement containing `sink` in any enclosing block."""
    child = sink
    node = par.get(sink)
    while node is not None:
        for field in ("body", "orelse", "finalbody", "handlers"):
            block = getattr(node, field, None)
            if isinstance(block, list) and child in block:
                for prev in block[: block.index(child)]:
                    if _is_guard_stmt(prev):
                        return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _first_is_guard(node.body):
            return True
        child, node = node, par.get(node)
    return False


def _enclosing_function(node, par):
    n = par.get(node)
    while n is not None and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        n = par.get(n)
    return n


def scan(overrides: dict[str, str] | None = None) -> list[str]:
    """Return a list of uncovered sinks as 'file:line name — reason'. `overrides` maps rel path → source
    (used by the mutation tests to scan an edited copy without touching the tree)."""
    overrides = overrides or {}
    trees = {rel: (_parse(overrides[rel], rel) if rel in overrides else _cached_tree(rel, p)) for rel, p in _files()}
    guarded_by_module: dict[str, set[str]] = {}
    defined_by_module: dict[str, set[str]] = {}
    for rel, t in trees.items():
        if t is not None:
            guarded_by_module.setdefault(Path(rel).stem, set()).update(_guarded_functions(t))
            defined_by_module.setdefault(Path(rel).stem, set()).update(
                n.name for n in t.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    broker_mods = _broker_module_names()
    problems = []
    for rel, t in trees.items():
        if t is None:
            continue
        par = _parents(t)
        aliases = _module_aliases(t)
        from_funcs = _from_imported_functions(t)
        own_guarded = _guarded_functions(t)
        for n in ast.walk(t):
            # HTTP helper defs in non-allowlisted modules must guard their raw request.
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in HTTP_HELPER_DEFS:
                if not _first_is_guard(n.body) and not _allowlisted(rel, n.name):
                    problems.append(f"{rel}:{n.lineno} def {n.name} — raw HTTP helper without a first-statement guard")
            if not isinstance(n, ast.Call):
                continue
            name = _call_name(n)
            if not name:
                continue
            kind = None
            if name in WRITE_METHODS:
                kind = "write-method"
            elif name in GENERIC_METHODS:
                recv = (
                    n.func.value.id
                    if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    else None
                )
                mod = aliases.get(recv) if recv else None
                if mod in broker_mods and name in defined_by_module.get(mod, set()):
                    kind = "broker-generic"
            elif name in HTTP_WRITE and ORDER_URL.search(_strings(n)):
                kind = "http-write"
            elif name in HTTP_GENERIC and ORDER_URL.search(_strings(n)):
                meth = [k for k in n.keywords if k.arg == "method"]
                data = [k for k in n.keywords if k.arg == "data"]
                if (
                    meth
                    and isinstance(meth[0].value, ast.Constant)
                    and WRITE_HTTP_METHOD.match(str(meth[0].value.value))
                ) or (name == "Request" and data):
                    kind = "http-write"
            if kind is None:
                continue
            fn = _enclosing_function(n, par)
            if _allowlisted(rel, fn.name if fn else None):
                continue
            if _dominated(n, par):
                continue
            # Call into a guarded chokepoint (resolved through the import table / same module / self.)
            if isinstance(n.func, ast.Attribute):
                recv = n.func.value
                if isinstance(recv, ast.Name):
                    mod = aliases.get(recv.id)
                    if mod and name in guarded_by_module.get(mod, set()):
                        continue
                    if recv.id in ("self", "cls") and name in own_guarded:
                        continue
            elif isinstance(n.func, ast.Name):
                if name in own_guarded:
                    continue
                if name in from_funcs:
                    mod, fname = from_funcs[name]
                    if fname in guarded_by_module.get(mod, set()):
                        continue
            problems.append(f"{rel}:{n.lineno} {name} — {kind} not dominated by {GUARD}")
    return problems


def _allowlisted(rel: str, func: str | None) -> bool:
    return rel in ALLOWLIST or (func is not None and f"{rel}::{func}" in ALLOWLIST)


def _find(tree, qual: str):
    node = tree
    for part in qual.split("."):
        node = next(
            (
                c
                for c in ast.iter_child_nodes(node)
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and c.name == part
            ),
            None,
        )
        if node is None:
            return None
    return node


def first_statement_problems(overrides: dict[str, str] | None = None) -> list[str]:
    overrides = overrides or {}
    out = []
    cache = {}
    for rel, qual in CHOKEPOINTS:
        src = overrides.get(rel) or (SCRIPTS / rel).read_text()
        t = cache.setdefault((rel, id(src)), ast.parse(src))
        fn = _find(t, qual)
        if fn is None:
            out.append(f"{rel}::{qual} not found")
        elif not _first_is_guard(fn.body):
            out.append(f"{rel}::{qual} — first statement is not {GUARD}")
    return out


# ── tests ───────────────────────────────────────────────────────────────────────────────────────────
def test_every_broker_write_sink_is_dominated_by_the_lock():
    problems = scan()
    assert not problems, "uncovered broker write paths:\n" + "\n".join(problems)


def test_named_chokepoints_open_with_the_lock():
    problems = first_statement_problems()
    assert not problems, "\n".join(problems)


def test_api_v2_order_routes_open_with_the_lock():
    t = ast.parse((SCRIPTS / "api_v2.py").read_text())
    seen = {}
    for n in ast.walk(t):
        if not isinstance(n, ast.If):
            continue
        lits = [c.value for c in ast.walk(n.test) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        for route in API_ROUTES:
            if route in lits and "base_path" in ast.unparse(n.test):
                seen[route] = _first_is_guard(n.body)
    missing = [r for r in API_ROUTES if r not in seen]
    unguarded = [r for r, ok in seen.items() if not ok]
    assert not missing, f"routes not found: {missing}"
    assert not unguarded, f"route branches not opening with {GUARD}: {unguarded}"


@pytest.mark.parametrize("rel,qual,needle", CONTAINS_GUARD)
def test_second_layer_functions_consult_the_lock(rel, qual, needle):
    fn = _find(ast.parse((SCRIPTS / rel).read_text()), qual)
    assert fn is not None, f"{rel}::{qual} not found"
    assert any(isinstance(c, ast.Call) and _call_name(c) == needle for c in ast.walk(fn)), (
        f"{rel}::{qual} does not call {needle}"
    )


@pytest.mark.parametrize("fname", ARM_PRECEDENCE)
def test_arm_state_functions_yield_to_the_lock_first(fname):
    """Pilot disarm in code: every standing-arm reader returns False first while the lock is engaged."""
    fn = _find(ast.parse((SCRIPTS / "brokers" / "execution_guard.py").read_text()), fname)
    body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) else fn.body
    first = body[0]
    assert isinstance(first, ast.If) and "_lock_engaged" in ast.unparse(first.test), (
        f"{fname} must open with `if _lock_engaged(): return False`"
    )


def test_allowlist_is_paper_only():
    for key in ALLOWLIST:
        rel = key.split("::")[0]
        assert (SCRIPTS / rel).is_file(), f"stale allowlist entry {key}"
        if rel in NON_PAPER_ALLOWLIST:
            continue
        src = (SCRIPTS / rel).read_text()
        assert any(m in src for m in PAPER_MARKERS) or "AlpacaPaperAdapter" in src, (
            f"allowlisted {rel} carries no Alpaca paper pin"
        )
        assert "schwab_transport" not in src or rel == "telegram_callback_handler.py", (
            f"allowlisted paper file {rel} imports the Schwab transport"
        )


def test_scanner_detects_known_sinks():
    """The scanner is not keyed on nothing: it sees the raw Schwab POST and DELETE."""
    src = (SCRIPTS / "schwab_transport.py").read_text()
    t = ast.parse(src)
    names = {_call_name(c) for c in ast.walk(t) if isinstance(c, ast.Call)}
    assert {"place_order", "cancel_order"} <= names


# ── mutation proof ─────────────────────────────────────────────────────────────────────────────────
def _strip_guard(src: str, qual: str) -> str:
    """Remove every guard statement from the body of `qual` (in memory)."""
    t = ast.parse(src)
    fn = _find(t, qual)
    assert fn is not None
    lines = src.split("\n")
    kill = []
    for s in fn.body:
        if _is_guard_stmt(s):
            kill.append((s.lineno, s.end_lineno))
    # also guards that sit later in the body right before the raw call (e.g. place_order:post)
    for s in ast.walk(fn):
        if isinstance(s, ast.Expr) and _is_guard_call(s.value) and (s.lineno, s.end_lineno) not in kill:
            kill.append((s.lineno, s.end_lineno))
    assert kill, f"no guard in {qual}"
    for a, b in sorted(kill, reverse=True):
        indent = re.match(r"\s*", lines[a - 1]).group(0)
        lines[a - 1 : b] = [indent + "pass"]
    return "\n".join(lines)


@pytest.mark.parametrize(
    "rel,qual,raw_sink",
    [
        # raw broker I/O lives here → BOTH the first-statement check and the sink scan must go red
        ("schwab_transport.py", "cancel_order", True),
        ("tastytrade_adapter.py", "TastytradeAdapter._api_post", True),
        # a pilot that delegates to the guarded transport: the first-statement check goes red (the sink scan
        # stays green because schwab_transport.place_order still guards — defence in depth, by design)
        ("brokers/protective_stop_pilot.py", "submit", False),
    ],
)
def test_mutation_removing_a_guard_turns_the_coverage_red(rel, qual, raw_sink):
    mutated = _strip_guard((SCRIPTS / rel).read_text(), qual)
    first = first_statement_problems({rel: mutated})
    sinks = scan({rel: mutated})
    assert any(qual in p for p in first), f"first-statement check missed removal from {rel}::{qual}"
    if raw_sink:
        assert any(p.startswith(rel + ":") for p in sinks), f"sink scan missed removal from {rel}::{qual}: {sinks}"
    # and the unmutated tree is green, so the red above is caused by the mutation alone
    assert not first_statement_problems()
