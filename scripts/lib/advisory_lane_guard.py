"""Static guard for AGENTS.md 7.0.0 §23.20 advisory market-data lanes (and the dispatcher sender gate).

Pure source analysis: parses Python with ``ast``; never imports, executes or connects to anything it scans.

``scan_entry(script_rel)`` walks the code a lane can reach from its entry script:

* imports, followed at **definition** granularity: ``from mod import Name`` scans ``Name``'s definition (and the
  same-module definitions it references, and the imports inside them), not the whole module, so a quote-only class
  that shares a file with a trade-context reader (``scripts/moomoo/client.py``: ``FutuTransport`` vs
  ``MoomooReadOnlyAccount``) is judged on what the lane uses; ``import mod`` scans the whole module;
* child scripts a lane spawns: a string literal naming an existing ``scripts/**.py`` file is scanned as a whole
  entry script (over-inclusive on purpose: a subprocess hand-off is reach);
* terminal modules: the host send chokepoint (``telegram_alert``) is recorded as a send and not descended into;
  a broker module (Alpaca, Schwab, SnapTrade, IBKR, the broker package) is recorded as a violation and not descended.

What it reports (``GuardReport``):

* ``trade_context``  — a moomoo/futu trade context or order verb is used (OpenSecTradeContext, unlock_trade,
  place_order, modify_order, cancel_order, TrdEnv, …): never allowed for a §23.20 lane (condition a);
* ``account_reads``  — an account / position read (get_account, accinfo_query, position_list_query, …) (condition a);
* ``broker_modules`` — an import of a broker client module (condition a);
* ``sends``          — calls of the host chokepoint (send_telegram, telegram_send, send_advisory_alert, …): a sender;
* ``direct_sends``   — a send that bypasses the chokepoint (smtplib, a literal api.telegram.org URL) (condition c);
* ``bypass_router``  — call sites passing ``bypass_router=True`` (allowed only where the 5.1.0 shrink-only allowlist
  already lists the file; this module only reports them).

``submit_tokens(argv, env)`` finds sandbox/broker submit switches in a dispatcher argv or inline env (condition b).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

#: moomoo / futu trade-context classes and order / unlock verbs (condition a). Quote-side names (OpenQuoteContext,
#: SubType, KLType, get_order_book, get_rt_ticker …) are deliberately absent.
TRADE_CONTEXT_NAMES = frozenset({
    "OpenSecTradeContext", "OpenUSTradeContext", "OpenHKTradeContext", "OpenCNTradeContext",
    "OpenFutureTradeContext", "OpenTradeContext", "TrdEnv", "TrdSide", "OrderType",
    "unlock_trade", "lock_trade", "place_order", "modify_order", "cancel_order", "cancel_all_order",
    "submit_order", "replace_order", "place_oco", "place_bracket",
})
#: Account / position reads (condition a).
ACCOUNT_READ_NAMES = frozenset({
    "accinfo_query", "position_list_query", "order_list_query", "deal_list_query", "get_acc_list",
    "acctradinginfo_query", "get_account", "get_positions", "list_positions", "get_all_positions",
    "get_portfolio", "get_orders", "list_orders",
})
#: Broker client modules (last dotted segment or first segment), recorded and never descended (condition a).
BROKER_MODULE_RE = re.compile(
    r"(^|\.)(alpaca_paper_adapter|alpaca_trade_api|alpaca|schwab_transport|schwab_token_manager|schwab_order_adapter"
    r"|schwab_oco_bracket|schwab_client|schwab|snaptrade\w*|ib_insync|robin_stocks|brokers)(\.|$)")
#: The host send chokepoint (AGENTS §9.1 / §24.1): a call into it is a governed send; it is not descended.
CHOKEPOINT_MODULES = frozenset({"telegram_alert", "scripts.telegram_alert"})
SEND_NAMES = frozenset({"send_telegram", "send_telegram_document", "telegram_send", "send_advisory_alert",
                        "send_email", "send_operator_message"})
DIRECT_SEND_RE = re.compile(r"https?://(api\.telegram\.org|hooks\.slack\.com)/")
#: Sandbox / broker submit switches that a §23.20 dispatcher argv or inline env may never carry (condition b).
SUBMIT_ARGV = ("--submit-validation", "--submit-sandbox", "--submit", "--live-orders")
SUBMIT_ENV = ("MOMENTUM_SCALP_VALIDATION_SUBMIT", "MOMENTUM_SCALP_PAPER_FAST_PATH")
_PY_LITERAL = re.compile(r"^(?:scripts/)?[A-Za-z0-9_/]+\.py$")


@dataclass
class GuardReport:
    entry: str
    trade_context: list[str] = field(default_factory=list)
    account_reads: list[str] = field(default_factory=list)
    broker_modules: list[str] = field(default_factory=list)
    sends: list[str] = field(default_factory=list)
    direct_sends: list[str] = field(default_factory=list)
    bypass_router: list[str] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)

    @property
    def is_sender(self) -> bool:
        return bool(self.sends or self.direct_sends)

    def market_data_only(self) -> bool:
        """Condition (a): no trade context, no account read, no broker client module."""
        return not (self.trade_context or self.account_reads or self.broker_modules)

    def problems(self) -> list[str]:
        out = [f"trade_context:{x}" for x in self.trade_context]
        out += [f"account_read:{x}" for x in self.account_reads]
        out += [f"broker_module:{x}" for x in self.broker_modules]
        out += [f"direct_send:{x}" for x in self.direct_sends]
        return out


@lru_cache(maxsize=None)
def _parse(path: str) -> Optional[ast.Module]:
    try:
        return ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None


def _module_file(name: str, current: Path, level: int = 0) -> Optional[Path]:
    """Resolve an import to a repo file, or None (third-party / stdlib)."""
    parts = [p for p in name.split(".") if p]
    bases: list[Path] = []
    if level:
        base = current.parent
        for _ in range(level - 1):
            base = base.parent
        bases = [base]
    else:
        if parts and parts[0] == "scripts":
            bases, parts = [SCRIPTS], parts[1:]
        else:
            bases = [SCRIPTS, current.parent]
    for base in bases:
        cand = base.joinpath(*parts) if parts else base
        if cand.with_suffix(".py").is_file():
            return cand.with_suffix(".py")
        if (cand / "__init__.py").is_file():
            return cand / "__init__.py"
    return None


def _defs(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node
    return out


def _top_imports(tree: ast.Module) -> dict[str, tuple]:
    """name bound at module top level by an import -> (kind, module, attr, level)."""
    out: dict[str, tuple] = {}
    for node in tree.body:
        nodes = [node]
        if isinstance(node, ast.Try):
            nodes = [n for n in node.body + [h for hh in node.handlers for h in hh.body] if isinstance(n, (ast.Import, ast.ImportFrom))]
        for n in nodes:
            if isinstance(n, ast.Import):
                for a in n.names:
                    out[(a.asname or a.name).split(".")[0]] = ("module", a.name, None, 0)
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    out[a.asname or a.name] = ("from", n.module or "", a.name, n.level or 0)
    return out


class _Scanner:
    def __init__(self) -> None:
        self.report: Optional[GuardReport] = None
        self.seen: set[tuple[str, str]] = set()

    def scan_entry(self, rel: str) -> GuardReport:
        self.report = GuardReport(entry=rel)
        path = (ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        self._module(path, None)
        for key in ("trade_context", "account_reads", "broker_modules", "sends", "direct_sends", "bypass_router",
                    "scanned"):
            setattr(self.report, key, sorted(set(getattr(self.report, key))))
        return self.report

    # -- module / definition walk ---------------------------------------------------------------------------
    def _module(self, path: Path, name: Optional[str]) -> None:
        """Scan the whole module (name None) or one top-level definition and what it references."""
        key = (str(path), name or "*")
        if key in self.seen:
            return
        self.seen.add(key)
        tree = _parse(str(path))
        if tree is None:
            return
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        self.report.scanned.append(rel if name is None else f"{rel}:{name}")
        defs, imports = _defs(tree), _top_imports(tree)
        if name is None:
            nodes: list[ast.AST] = list(tree.body)
        else:
            node = defs.get(name)
            if node is None:
                if name in imports:  # re-export: follow it
                    self._follow(imports[name], path)
                return
            nodes = [node]
        for node in nodes:
            self._walk(node, path, rel, defs, imports, whole=name is None)

    def _follow(self, spec: tuple, current: Path) -> None:
        kind, mod, attr, level = spec
        full = mod if kind == "module" else mod
        if BROKER_MODULE_RE.search(full or "") or (attr and BROKER_MODULE_RE.search(attr) and kind == "from"
                                                   and _module_file(f"{mod}.{attr}" if mod else attr, current, level)):
            self.report.broker_modules.append(full if kind == "module" else f"{mod}.{attr}".strip("."))
            return
        if full in CHOKEPOINT_MODULES or (full or "").split(".")[-1] == "telegram_alert":
            return
        if kind == "module":
            f = _module_file(full, current, 0)
            if f:
                self._module(f, None)
            return
        f = _module_file(mod, current, level) if (mod or level) else None
        if f is not None:
            sub = _module_file(f"{mod}.{attr}" if mod else attr, current, level)
            if sub is not None and sub != f:  # `from pkg import submodule`
                self._module(sub, None)
            else:
                self._module(f, attr)

    def _walk(self, node: ast.AST, path: Path, rel: str, defs: dict, imports: dict, *, whole: bool) -> None:
        local_refs: set[str] = set()
        # A `.py` literal counts as a spawned child only where a command is built: a call argument, a list/tuple
        # element of one, or a path join (`SCRIPTS / "x.py"`) — never a docstring or a log message.
        spawn_literals: set[int] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                for arg in list(sub.args) + [k.value for k in sub.keywords]:
                    for el in ([arg] + (list(arg.elts) if isinstance(arg, (ast.List, ast.Tuple)) else [])):
                        spawn_literals.add(id(el))
                        if isinstance(el, ast.BinOp):
                            spawn_literals.update({id(el.left), id(el.right)})
            elif isinstance(sub, (ast.List, ast.Tuple)):
                for el in sub.elts:
                    if isinstance(el, ast.BinOp):
                        spawn_literals.update({id(el.left), id(el.right)})
            elif isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
                spawn_literals.update({id(sub.left), id(sub.right)})
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for a in sub.names:
                    if a.name.split(".")[0] == "smtplib":
                        self.report.direct_sends.append(f"{rel}:{sub.lineno}:smtplib")
                    self._follow(("module", a.name, None, 0), path)
            elif isinstance(sub, ast.ImportFrom):
                mod = sub.module or ""
                for a in sub.names:
                    if a.name in TRADE_CONTEXT_NAMES:
                        self.report.trade_context.append(f"{rel}:{sub.lineno}:{a.name}")
                    if a.name in SEND_NAMES and (mod.split(".")[-1] == "telegram_alert"):
                        self.report.sends.append(f"{rel}:{sub.lineno}:{a.name}")
                    if mod.split(".")[-1] == "smtplib" or a.name == "smtplib":
                        self.report.direct_sends.append(f"{rel}:{sub.lineno}:smtplib")
                    self._follow(("from", mod, a.name, sub.level or 0), path)
            elif isinstance(sub, ast.Name):
                if isinstance(sub.ctx, ast.Load):
                    if sub.id in TRADE_CONTEXT_NAMES:
                        self.report.trade_context.append(f"{rel}:{sub.lineno}:{sub.id}")
                    local_refs.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                if sub.attr in TRADE_CONTEXT_NAMES:
                    self.report.trade_context.append(f"{rel}:{sub.lineno}:{sub.attr}")
                if sub.attr in ACCOUNT_READ_NAMES:
                    self.report.account_reads.append(f"{rel}:{sub.lineno}:{sub.attr}")
            elif isinstance(sub, ast.Call):
                fn = sub.func
                fname = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
                if fname in SEND_NAMES:
                    self.report.sends.append(f"{rel}:{sub.lineno}:{fname}")
                if fname in ACCOUNT_READ_NAMES:
                    self.report.account_reads.append(f"{rel}:{sub.lineno}:{fname}")
                for kw in sub.keywords:
                    if kw.arg == "bypass_router" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                        self.report.bypass_router.append(f"{rel}:{sub.lineno}")
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if DIRECT_SEND_RE.search(sub.value):
                    self.report.direct_sends.append(f"{rel}:{sub.lineno}:{sub.value[:40]}")
                if id(sub) in spawn_literals and _PY_LITERAL.match(sub.value):
                    for child in (SCRIPTS / sub.value.removeprefix("scripts/"), path.parent / sub.value):
                        if child.is_file() and child.resolve() != path.resolve():
                            self._module(child, None)
                            break
        # same-module definitions and top-level imports this node references
        for ref in sorted(local_refs):
            if ref in defs and (not whole):
                self._module(path, ref)
            elif ref in imports and not whole:
                self._follow(imports[ref], path)


def scan_entry(script_rel: str) -> GuardReport:
    """GuardReport for one entry script (repo-relative, e.g. ``scripts/active_trader/premarket_watch.py``)."""
    return _Scanner().scan_entry(script_rel)


def entry_script(command: Iterable[str]) -> Optional[str]:
    """The repo script an allowlist argv runs (`$PY scripts/x.py ...`, optionally after `env NAME=V ...`)."""
    toks = list(command or [])
    for i, t in enumerate(toks):
        if t == "$PY" and i + 1 < len(toks) and toks[i + 1].endswith(".py"):
            return toks[i + 1]
    return None


def submit_tokens(argv: Iterable[str], env: Optional[dict] = None) -> list[str]:
    """Condition (b): sandbox / broker submit switches in an argv (incl. an `env NAME=V` prefix) or an env mapping."""
    hits: list[str] = []
    for t in argv or []:
        s = str(t)
        if s in SUBMIT_ARGV or any(s.startswith(a + "=") for a in SUBMIT_ARGV):
            hits.append(s)
        name, eq, value = s.partition("=")
        if eq and name in SUBMIT_ENV and value not in ("", "0", "false"):
            hits.append(s)
    for name, value in (env or {}).items():
        if name in SUBMIT_ENV and str(value) not in ("", "0", "false"):
            hits.append(f"{name}={value}")
    return hits
