"""broker_read_sync_policy — the closed step list, the exclusions and the capability audit for the read-only
broker sync (scripts/ops/broker_read_sync.sh; AGENTS.md 14.0.0 §24.11, PROPOSED).

Operator, 2026-10-16: "make that bash so agents can run, make amendment, not trading just reading". The
operator-run ``~/n8n-maturity-verification/sync_all_readonly.sh`` becomes a repo entrypoint an agent may invoke
under a ``broker-read`` guard grant. This module is the single place that says WHAT it may run and proves,
statically, what those steps can reach. The orchestrator (``scripts/ops/broker_read_sync.py``), the child
runner (``scripts/ops/broker_read_sync_child.py``) and the CI pin (``tests/test_broker_read_sync_20261016.py``)
all read it.

Why a static audit alone is not enough (measured 2026-10-16 on origin/main 766914db2 with
``scripts/audit_lane_transitive_capabilities.py``'s resolver): the FULL static import closure of every step,
lazy function-level imports included, is ~1,145 modules — the whole repo — and reaches 10 order-capable modules,
all through ``schwab_transport.py`` (which defines ``place_order``/``cancel_order`` and lazily imports the order
pilots) or ``holdings_guard -> schwab_position_sync``. Claiming that closure is order-free would be false. So the
effective closure is made smaller by construction and the audit proves the smaller one:

  1. ``EXCLUDED`` modules (stop managers, stop sync, options lifecycle, defense execution, order pilots, the
     approval/2FA services, the API server, active trader) are REFUSED AT IMPORT in every step process by the
     child runner's import hook. The audit prunes traversal at exactly the same set, so the closure it audits is
     the closure that can load.
  2. Inside that effective closure, every module that defines an order-write or re-auth/refresh function must be
     in ``RUNTIME_STUBS`` with every such name covered; the child replaces those attributes with a refusal right
     after the module executes (``schwab_transport``, ``moomoo.client``, ``schwab_token_manager``).
  3. No direct sender, no excluded entrypoint, no excluded module on an EAGER (module-level) import chain, and
     an excluded-family module that is reachable only as a read must be a reasoned ``READ_EXEMPT`` with no broker,
     network or order capability.
  4. Underneath all of it the trading lock (``scripts/lib/trading_lock.py``) must be LOCKED: every order write in
     the repo is dominated by ``assert_trading_unlocked`` (tests/test_trading_lock_coverage_20261014.py).

Static limits (stated, not hidden): dynamic imports with computed names and third-party SDK code are not
walked. The child's HTTP guard covers the SDK side (no non-GET request to a broker host) and its subprocess
guard refuses spawning another Python process (which would escape the hooks).

Pure: reads repository files only; never imports a step, a broker module or a credential.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_RECEIPT = "BrokerReadSyncReceipt@v1"
SCHEMA_AUDIT = "BrokerReadCapabilityAudit@v1"
GRANT_TIER = "broker-read"
GRANT_MAX_SECONDS = 4 * 3600
POLICY_VERSION = "14.0.0"
POLICY_TOKEN = "APPROVE_AGENTS_POLICY_14_0_0"
GUARD_MARK = "BROKER_READ_SYNC_GUARD"
SCHWAB_MODE = "read_only"
LOCK_BROKERS = ("schwab", "alpaca", "moomoo", "snaptrade")


@dataclass(frozen=True)
class Step:
    id: str
    label: str
    script: str
    dry_argv: Optional[tuple[str, ...]]  # None = the step does not run in a dry run
    apply_argv: tuple[str, ...]
    broker: str  # which broker the step reads ("none" = our own stores only)

    def argv(self, mode: str) -> Optional[tuple[str, ...]]:
        if mode == "apply":
            return self.apply_argv
        if mode == "dry_run":
            return self.dry_argv
        raise ValueError(f"unknown mode {mode!r}")


# THE CLOSED ALLOWLIST. Order, scripts and argv are exactly the operator's sync_all_readonly.sh (2026-10-16).
# Nothing reaches a step's argv from the command line; adding, removing or changing a step changes this tuple,
# which tests/test_broker_read_sync_20261016.py pins byte for byte.
STEPS: tuple[Step, ...] = (
    Step("schwab_positions", "Schwab positions (3 accounts)", "scripts/schwab_position_sync.py",
         (), ("--apply",), "schwab"),
    Step("schwab_transactions", "Schwab transactions (7 days)", "scripts/schwab_transaction_ingest.py",
         ("--days", "7"), ("--days", "7", "--apply"), "schwab"),
    Step("alpaca_live_read", "Alpaca live read", "scripts/alpaca_live_read_sync.py",
         ("--dry-run",), (), "alpaca"),
    Step("moomoo_live_read", "moomoo live read", "scripts/moomoo_live_read_sync.py",
         ("--dry-run",), (), "moomoo"),
    Step("snaptrade", "SnapTrade", "scripts/snaptrade_sync.py",
         (), ("--apply",), "snaptrade"),
    Step("positions_store", "Positions store (all brokers)", "scripts/positions_sync.py",
         (), ("--apply",), "all"),
    Step("positions_fresh", "Positions freshness check", "scripts/positions_sync.py",
         None, ("--check-fresh",), "none"),
    Step("stop_health", "Stop health (read-only report)", "scripts/stop_health_check.py",
         ("--quiet",), ("--quiet",), "none"),
)
STEP_IDS = tuple(s.id for s in STEPS)

# Families that are never a step and never load in a step process. Matched against the repo-relative path.
EXCLUDED: dict[str, str] = {
    "stop_manager": r"^scripts/(?:.+/)?\w*stop_manager\w*\.py$",
    "stop_sync": r"^scripts/(?:.+/)?\w*stop_sync\w*\.py$|^scripts/(?:.+/)?broker_stop_reconcile\w*\.py$",
    "stop_writer": r"^scripts/(?:.+/)?(?:\w*stop_pilot|\w*stop_writer\w*|schwab_oco_bracket|stop_lifecycle_actions?)\.py$",
    "options_lifecycle": r"^scripts/(?:.+/)?options_lifecycle\w*\.py$",
    "defense_execution": r"^scripts/(?:.+/)?defense_execution\w*\.py$",
    "order_pilot": r"^scripts/brokers/\w*_pilot\.py$|^scripts/\w*_pilot_arm\.py$|^scripts/proposal_live_submit\w*\.py$",
    "approval_2fa": r"^scripts/brokers/(?:approval_service|execution_guard|evidence_approval)\.py$"
                    r"|^scripts/lib/trading_session_grant\.py$",
    "order_transport": r"^scripts/brokers/snaptrade_(?:trade\w*|transport)\.py$"
                       r"|^scripts/(?:broker_adapter|alpaca_paper_adapter)\.py$",
    "api_server": r"^scripts/(?:api_v2|portfolio_server|reports_portal)\.py$",
    "active_trader": r"^scripts/active_trader/",
}
_EXCLUDED_RE = {fam: re.compile(rx) for fam, rx in EXCLUDED.items()}

# An excluded-family module that a READ path needs. Each must carry no broker, network or order capability
# (asserted by the audit), and stays importable.
READ_EXEMPT: dict[str, str] = {
    "scripts/lib/fidelity_stop_sync.py": (
        "manual (Fidelity) stop store: open_trades_intelligence.load_broker_stops reads "
        "load_manual_protective_stops(); Fidelity has no API, the module only reads/writes our DB"),
}

# Order-write and re-auth names. A module in the effective closure that defines any of these (top level or in a
# class) must list it in RUNTIME_STUBS. Names follow tests/test_trading_lock_coverage_20261014.py WRITE_METHODS.
ORDER_NAME_RE = re.compile(
    r"^(?:place|submit|cancel|replace|modify)_\w*order\w*$|^unlock_trade$|^submit_(?:entry|oco|fully_approved)$"
    r"|^(?:create|replace|delete)_saved_order$|^confirm_and_submit$|^request_2fa$|^route_after_2fa$")
REAUTH_NAME_RE = re.compile(
    r"^(?:seed_token|exchange_code|reauth_url|approve_http_refresh|_refresh_access_token|init_key"
    r"|client_from_login_flow|client_from_manual_flow|easy_client)$")

# Attributes replaced with a refusal in every step process, right after the module executes.
RUNTIME_STUBS: dict[str, tuple[str, ...]] = {
    "scripts/schwab_transport.py": ("place_order", "replace_order", "cancel_order", "cancel_order_for_replace"),
    "scripts/moomoo/client.py": ("MoomooClient.place_order", "MoomooClient.unlock_trade"),
    "scripts/schwab_token_manager.py": ("seed_token", "exchange_code", "reauth_url", "approve_http_refresh",
                                        "_refresh_access_token", "init_key"),
}
# Third-party SDK classes patched the same way (moomoo/futu trade context). Never imported by this module.
SDK_STUBS: dict[str, tuple[str, ...]] = {
    "futu": ("OpenSecTradeContext.place_order", "OpenSecTradeContext.modify_order",
             "OpenSecTradeContext.cancel_all_order", "OpenSecTradeContext.unlock_trade"),
    "moomoo": ("OpenSecTradeContext.place_order", "OpenSecTradeContext.modify_order",
               "OpenSecTradeContext.cancel_all_order", "OpenSecTradeContext.unlock_trade"),
}

# Broker hosts: the child refuses every non-GET/HEAD request to these (order routes, OAuth token refresh).
BROKER_HOST_RE = re.compile(
    r"(?:^|\.)(?:schwabapi\.com|schwab\.com|alpaca\.markets|snaptrade\.com|tdameritrade\.com|moomoo\.com|futunn\.com)$",
    re.I)
READ_METHODS = frozenset({"GET", "HEAD"})
ORDER_ROUTE_RE = re.compile(r"/(?:v\d+/)?(?:accounts/[^/\s]+/)?orders\b")


def excluded_family(rel: str) -> Optional[str]:
    """The excluded family a repo-relative path belongs to, or None."""
    rel = rel.replace("\\", "/")
    for fam, rx in _EXCLUDED_RE.items():
        if rx.search(rel):
            return fam
    return None


def runtime_denied(rel: str) -> Optional[str]:
    """Family name when the child must refuse importing this module (excluded and not a read exemption)."""
    if rel in READ_EXEMPT:
        return None
    return excluded_family(rel)


def _defined_names(path: Path) -> set[str]:
    """Top-level function names and Class.method names defined in a module (AST; never imported)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.add(f"{node.name}.{sub.name}")
    return out


_HTTP_WRITE_ATTRS = frozenset({"post", "put", "delete", "patch"})


def _order_route_write(path: Path) -> Optional[str]:
    """Evidence when a module both names an order route and makes an HTTP write call (.post/.put/.delete/.patch,
    or method="POST"/"PUT"/"DELETE"/"PATCH"). A GET of /orders (reading open orders) is not a write."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    route = None
    write = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and ORDER_ROUTE_RE.search(node.value):
            if len(node.value) < 200:  # a docstring mentioning /orders is not a route
                route = route or node.value[:80]
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in _HTTP_WRITE_ATTRS:
                write = write or f"{fn.attr}() line {node.lineno}"
            for kw in node.keywords:
                if kw.arg == "method" and isinstance(kw.value, ast.Constant) and \
                        str(kw.value.value).upper() in ("POST", "PUT", "DELETE", "PATCH"):
                    write = write or f"method={kw.value.value!r} line {node.lineno}"
    if route and write:
        return f"route {route!r} + {write}"
    return None


def _stub_gaps(rel: str, path: Path) -> tuple[list[str], list[str]]:
    names = _defined_names(path)
    stubbed = set(RUNTIME_STUBS.get(rel, ()))
    order = sorted(n for n in names if ORDER_NAME_RE.match(n.rsplit(".", 1)[-1]) and n not in stubbed)
    reauth = sorted(n for n in names if REAUTH_NAME_RE.match(n.rsplit(".", 1)[-1]) and n not in stubbed)
    return order, reauth


def audit(root: Path = ROOT, steps: tuple[Step, ...] = STEPS) -> dict[str, Any]:
    """Static capability audit of every step's effective import closure. ``findings`` empty = clean.

    Reuses scripts/audit_lane_transitive_capabilities.py (Resolver, ModuleInfo flags, chains)."""
    import sys

    scripts_dir = str(Path(root) / "scripts")
    added = scripts_dir not in sys.path
    if added:
        sys.path.insert(0, scripts_dir)
    try:
        import audit_lane_transitive_capabilities as lane_audit  # noqa: PLC0415
    finally:
        if added:
            sys.path.remove(scripts_dir)

    saved_root = lane_audit.ROOT
    lane_audit.ROOT = Path(root)  # its _rel()/_chain() resolve against the module ROOT
    try:
        return _audit(lane_audit, Path(root), steps)
    finally:
        lane_audit.ROOT = saved_root


def _audit(lane_audit: Any, root: Path, steps: tuple[Step, ...]) -> dict[str, Any]:
    resolver = lane_audit.Resolver(root)
    root_r = Path(root).resolve()

    def rel_of(p: Path) -> str:
        return p.resolve().relative_to(root_r).as_posix()

    findings: list[dict[str, Any]] = []
    per_step: dict[str, Any] = {}
    seen_scripts: dict[str, dict[str, Any]] = {}
    for step in steps:
        fam = excluded_family(step.script)
        if fam:
            findings.append({"step": step.id, "kind": "excluded_entrypoint", "module": step.script, "family": fam})
            continue  # never a step, whatever it imports
        entry = Path(root) / step.script
        if not entry.is_file():
            findings.append({"step": step.id, "kind": "step_script_missing", "module": step.script})
            continue
        if step.script in seen_scripts:
            per_step[step.id] = seen_scripts[step.script]
            continue
        parent: dict[Path, Optional[Path]] = {entry: None}
        eager_parent: dict[Path, bool] = {entry: True}  # reached through module-level imports only
        order: list[Path] = []
        denied_edges: list[dict[str, Any]] = []
        queue = [entry]
        while queue:
            cur = queue.pop(0)
            order.append(cur)
            info = resolver.info(cur)
            if lane_audit.is_chokepoint(info.path):
                continue
            for name, level, from_name, eager in info.imports:
                for nxt in resolver.resolve(cur, name, level, from_name):
                    nrel = rel_of(nxt)
                    is_eager = eager_parent.get(cur, False) and eager
                    dfam = runtime_denied(nrel)
                    if dfam:
                        denied_edges.append({"from": info.path, "to": nrel, "family": dfam, "eager": is_eager})
                        if is_eager:
                            findings.append({"step": step.id, "kind": "excluded_module_eager", "module": nrel,
                                             "family": dfam, "chain": lane_audit._chain(cur, parent) + [nrel]})
                        continue
                    if nxt not in parent:
                        parent[nxt] = cur
                        eager_parent[nxt] = is_eager
                        queue.append(nxt)
                    elif is_eager and not eager_parent.get(nxt, False):
                        eager_parent[nxt] = True
        for p in order:
            info = resolver.info(p)
            rel = info.path
            chain = lane_audit._chain(p, parent)
            if "direct_sender" in info.caps:
                findings.append({"step": step.id, "kind": "direct_sender", "module": rel, "chain": chain,
                                 "evidence": info.evidence.get("direct_sender")})
            if rel in READ_EXEMPT:
                bad = sorted(info.caps & {"broker_module", "network_http", "order_placement", "direct_sender"})
                if bad:
                    findings.append({"step": step.id, "kind": "exempt_module_capability", "module": rel,
                                     "capabilities": bad})
            if rel not in RUNTIME_STUBS:
                route_write = _order_route_write(p)
                if route_write:
                    findings.append({"step": step.id, "kind": "order_route_write", "module": rel, "chain": chain,
                                     "evidence": route_write})
            order_gaps, reauth_gaps = _stub_gaps(rel, p)
            if "order_placement" in info.caps and rel not in RUNTIME_STUBS:
                findings.append({"step": step.id, "kind": "order_capability_unstubbed", "module": rel,
                                 "chain": chain, "evidence": info.evidence.get("order_placement")})
            if order_gaps:
                findings.append({"step": step.id, "kind": "order_capability_unstubbed", "module": rel,
                                 "chain": chain, "names": order_gaps})
            if reauth_gaps:
                findings.append({"step": step.id, "kind": "reauth_capability_unstubbed", "module": rel,
                                 "chain": chain, "names": reauth_gaps})
        summary = {
            "script": step.script,
            "effective_closure": len(order),
            "runtime_denied_edges": len(denied_edges),
            "runtime_denied_modules": sorted({e["to"] for e in denied_edges}),
            "stubbed_modules": sorted(m for m in RUNTIME_STUBS if (Path(root) / m) in set(order)),
        }
        seen_scripts[step.script] = summary
        per_step[step.id] = summary
    # Every stub target must still exist, or the runtime patch silently patches nothing.
    for rel, names in RUNTIME_STUBS.items():
        path = Path(root) / rel
        if not path.is_file():
            continue
        defined = _defined_names(path)
        for n in names:
            if n not in defined:
                findings.append({"kind": "stub_target_missing", "module": rel, "names": [n]})
    return {"schema": SCHEMA_AUDIT, "ok": not findings, "findings": findings, "steps": per_step}
