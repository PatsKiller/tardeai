#!/usr/bin/env python3
"""Static payload-flow analysis: which contract schemas (and which delegated
producer functions) reach WHICH key path of a route handler's response.

The API census reads a handler body plus one delegated lib function, so a
schema built two or three calls deep (handler -> api_v3_cio getter -> lib
builder) is invisible to it, and a schema built one call deep is credited to
the whole response even when it sits in a block the consumer never reads.

This module follows delegation transitively and keeps the key path:

    get_cio_brain_v1  --"market_context"-->  get_market_context_state_v1
                      --.get("market_context")-->  build_market_context_state
                      -> {"schema": "MarketContextState@v1", ...}

yields ``("MarketContextState@v1", ["market_context"])``.  A consumer then
only "surfaces" that schema when it reads every segment of the path
(``consumer_reads_path``).  Fetched-but-ignored blocks therefore do not count.

Static source only (ast).  Approximations, all named:
  * comprehensions and unknown calls pass every input flow through at the
    enclosing path (over-approximates placement, never invents a schema);
  * ``x.get("k")`` / ``x["k"]`` selects the ``k`` sub-block of ``x``;
  * a resolved call passes an argument through only when the callee returns
    that parameter;
  * calls through instances/classes are not followed.
"""
from __future__ import annotations

import ast
import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VALUE_RE = re.compile(r"^[A-Z][A-Za-z0-9]+@v\d+$")
SCHEMA_KEYS = frozenset({"schema", "schema_version", "contract"})
MAX_DEPTH = 8
PASSTHROUGH_CALLS = frozenset({
    "dict", "list", "tuple", "sorted", "reversed", "filter", "copy", "deepcopy", "items", "values",
    "_json_clean", "json_clean", "_jsonable", "jsonable", "_clean", "_safe", "_public", "MappingProxyType",
})

# A flow: origin placed at ``path`` of the current value, after selecting
# ``sel`` inside the origin's own output.
#   origin = ("schema", "Name@v1") | ("fn", "mod.py::func") | ("param", "name")


@dataclass(frozen=True)
class Flow:
    kind: str
    name: str
    path: tuple[str, ...] = ()
    sel: tuple[str, ...] = ()

    def at(self, prefix: tuple[str, ...]) -> "Flow":
        return Flow(self.kind, self.name, prefix + self.path, self.sel)


def _select(flows: set[Flow], key: str) -> set[Flow]:
    out: set[Flow] = set()
    for f in flows:
        if not f.path:
            out.add(Flow(f.kind, f.name, (), f.sel + (key,)))
        elif f.path[0] == key:
            out.add(Flow(f.kind, f.name, f.path[1:], f.sel))
    return out


def _module_file(root: Path, dotted: str, current: Optional[Path] = None, level: int = 0) -> Optional[Path]:
    if level and current is not None:
        base = current.parent
        for _ in range(level - 1):
            base = base.parent
        parts = dotted.split(".") if dotted else []
        cand = base.joinpath(*parts) if parts else base
    else:
        parts = dotted.split(".")
        if parts[0] == "scripts":
            parts = parts[1:]
        if not parts:
            return None
        cand = root.joinpath("scripts", *parts)
    for p in (cand.with_suffix(".py"), cand / "__init__.py"):
        if p.is_file():
            return p
    return None


class _Module:
    def __init__(self, root: Path, path: Path):
        self.path = path
        self.rel = str(path.relative_to(root / "scripts")) if path.is_relative_to(root / "scripts") else str(path)
        try:
            self.tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            self.tree = ast.Module(body=[], type_ignores=[])
        self.functions: dict[str, ast.AST] = {}
        self.consts: dict[str, str] = {}
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.functions[f"{node.name}.{sub.name}"] = sub
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                value = node.value
                schema = None
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and SCHEMA_VALUE_RE.match(value.value):
                    schema = value.value
                elif isinstance(value, ast.Dict):
                    # module-level payload template: X_DEFINITION = {"schema": "X@v1", ...}
                    for k, v in zip(value.keys, value.values):
                        if isinstance(k, ast.Constant) and k.value in SCHEMA_KEYS and isinstance(v, ast.Constant) \
                                and isinstance(v.value, str) and SCHEMA_VALUE_RE.match(v.value):
                            schema = v.value
                if schema:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Name):
                            self.consts[t.id] = schema
        self.imports = _imports(self.tree.body, skip_defs=True)


def _imports(body: list[ast.stmt] | ast.AST, *, skip_defs: bool) -> dict[str, tuple[str, Optional[str], int]]:
    """local name -> (dotted module, attribute or None for a module alias, relative level)."""
    out: dict[str, tuple[str, Optional[str], int]] = {}
    nodes = body if isinstance(body, list) else [body]
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                local = a.asname or a.name
                out.setdefault(local, (node.module or "", a.name, node.level))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out.setdefault(a.asname, (a.name, None, 0))
        if skip_defs and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


class PayloadFlow:
    """Resolve ``mod.py::func`` producers and compute their emitted (origin, path) set."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else ROOT
        self._mods: dict[Path, _Module] = {}
        self._memo: dict[str, frozenset[Flow]] = {}
        self._active: set[str] = set()

    # ── resolution ───────────────────────────────────────────────────────────
    def _mod(self, path: Path) -> _Module:
        if path not in self._mods:
            self._mods[path] = _Module(self.root, path)
        return self._mods[path]

    def _mod_by_rel(self, rel: str) -> Optional[_Module]:
        path = self.root / "scripts" / rel
        return self._mod(path) if path.is_file() else None

    def _resolve_target(self, mod: _Module, spec: tuple[str, Optional[str], int]) -> Optional[tuple[_Module, Optional[str]]]:
        dotted, attr, level = spec
        if attr is None:
            path = _module_file(self.root, dotted, mod.path, level)
            return (self._mod(path), None) if path else None
        path = _module_file(self.root, dotted, mod.path, level)
        if path:
            target = self._mod(path)
            if attr in target.functions:
                return target, attr
            # ``from scripts.lib import cio_x`` -> module alias
            sub = _module_file(self.root, f"{dotted}.{attr}" if dotted else attr, mod.path, level)
            if sub:
                return self._mod(sub), None
            return None
        sub = _module_file(self.root, f"{dotted}.{attr}" if dotted else attr, mod.path, level)
        return (self._mod(sub), None) if sub else None

    def _imported_const(self, mod: _Module, local_imports: dict, node: ast.AST) -> Optional[str]:
        """Schema constant behind ``NAME`` imported from another module, or ``alias.NAME``."""
        if isinstance(node, ast.Name):
            spec = local_imports.get(node.id) or mod.imports.get(node.id)
            if spec and spec[1]:
                path = _module_file(self.root, spec[0], mod.path, spec[2])
                if path:
                    return self._mod(path).consts.get(spec[1])
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            spec = local_imports.get(node.value.id) or mod.imports.get(node.value.id)
            if spec:
                hit = self._resolve_target(mod, spec)
                if hit and hit[1] is None:
                    return hit[0].consts.get(node.attr)
        return None

    def _resolve_call(self, mod: _Module, local_imports: dict, cls: Optional[str], func: ast.expr) -> Optional[str]:
        if isinstance(func, ast.Name):
            name = func.id
            spec = local_imports.get(name) or mod.imports.get(name)
            if spec:
                hit = self._resolve_target(mod, spec)
                if hit and hit[1]:
                    return f"{hit[0].rel}::{hit[1]}"
                return None
            if name in mod.functions:
                return f"{mod.rel}::{name}"
            return None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            head = func.value.id
            if head == "self" and cls and f"{cls}.{func.attr}" in mod.functions:
                return f"{mod.rel}::{cls}.{func.attr}"
            spec = local_imports.get(head) or mod.imports.get(head)
            if spec:
                hit = self._resolve_target(mod, spec)
                if hit and hit[1] is None and func.attr in hit[0].functions:
                    return f"{hit[0].rel}::{func.attr}"
        return None

    # ── analysis ─────────────────────────────────────────────────────────────
    def emitted(self, producer: str, _depth: int = 0) -> frozenset[Flow]:
        """Flows of the producer's return value (schema/fn origins with key paths)."""
        if producer in self._memo:
            return self._memo[producer]
        if producer in self._active or _depth > MAX_DEPTH or "::" not in producer:
            return frozenset()
        rel, func = producer.split("::", 1)
        mod = self._mod_by_rel(rel)
        node = mod.functions.get(func) if mod else None
        if node is None:
            return frozenset()
        self._active.add(producer)
        try:
            result = frozenset(self._analyse(mod, node, func.split(".")[0] if "." in func else None, _depth))
        finally:
            self._active.discard(producer)
        self._memo[producer] = result
        return result

    def _analyse(self, mod: _Module, fn: ast.AST, cls: Optional[str], depth: int) -> set[Flow]:
        local_imports = _imports(list(fn.body), skip_defs=True)
        env: dict[str, set[Flow]] = {}
        params = [a.arg for a in (fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs)]
        for p in params:
            env[p] = {Flow("param", p)}
        returns: set[Flow] = set()
        nested = {
            n.name: n for n in ast.walk(fn)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn
        }
        nested_memo: dict[str, set[Flow]] = {}

        def callable_flows(arg: ast.AST) -> set[Flow]:
            """A builder passed as an argument (``_cached(key, build)``, ``lambda: f()``) is
            invoked by the callee; its result is what comes back."""
            if isinstance(arg, ast.Lambda):
                return flows(arg.body)
            if isinstance(arg, ast.Name) and arg.id in nested:
                if arg.id not in nested_memo and depth < MAX_DEPTH:
                    nested_memo[arg.id] = set()
                    nested_memo[arg.id] = {
                        f for f in self._analyse(mod, nested[arg.id], cls, depth + 1) if f.kind != "param"
                    }
                return set(nested_memo.get(arg.id, set()))
            return set()

        def flows(expr: Optional[ast.AST]) -> set[Flow]:
            if expr is None:
                return set()
            if isinstance(expr, ast.Constant):
                if isinstance(expr.value, str) and SCHEMA_VALUE_RE.match(expr.value):
                    return {Flow("schema", expr.value)}
                return set()
            if isinstance(expr, ast.Name):
                if expr.id in env:
                    return set(env[expr.id])
                if expr.id in mod.consts:
                    return {Flow("schema", mod.consts[expr.id])}
                imported = self._imported_const(mod, local_imports, expr)
                return {Flow("schema", imported)} if imported else set()
            if isinstance(expr, ast.Dict):
                out: set[Flow] = set()
                for k, v in zip(expr.keys, expr.values):
                    vf = flows(v)
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        if k.value in SCHEMA_KEYS:
                            out |= {f for f in vf if f.kind == "schema"}
                            out |= {f.at((k.value,)) for f in vf if f.kind != "schema"}
                        else:
                            out |= {f.at((k.value,)) for f in vf}
                    else:
                        out |= vf
                return out
            if isinstance(expr, ast.Subscript):
                base = flows(expr.value)
                sl = expr.slice
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                    return _select(base, sl.value)
                return base
            if isinstance(expr, ast.Call):
                f = expr.func
                if isinstance(f, ast.Attribute) and f.attr == "get" and expr.args and isinstance(expr.args[0], ast.Constant) \
                        and isinstance(expr.args[0].value, str):
                    sel = _select(flows(f.value), expr.args[0].value)
                    return sel | (flows(expr.args[1]) if len(expr.args) > 1 else set())
                if isinstance(f, ast.Name) and f.id in nested and f.id not in env:
                    # local helper defined inside this function: its return is the call's value
                    return callable_flows(f)
                target = self._resolve_call(mod, local_imports, cls, f)
                if target:
                    sub = self.emitted(target, depth + 1)
                    # the callee's own parameter flows are local to it; arguments it returns are re-placed below
                    out = {Flow("fn", target)} | {x for x in sub if x.kind != "param"}
                    for a in list(expr.args) + [kw.value for kw in expr.keywords]:
                        out |= callable_flows(a)
                    callee_mod = self._mod_by_rel(target.split("::", 1)[0])
                    callee = callee_mod.functions.get(target.split("::", 1)[1]) if callee_mod else None
                    if callee is not None:
                        names = [a.arg for a in (callee.args.posonlyargs + callee.args.args)]
                        if names and names[0] == "self":
                            names = names[1:]
                        passthrough: dict[str, list[Flow]] = {}
                        for fl in sub:
                            if fl.kind == "param":
                                passthrough.setdefault(fl.name, []).append(fl)
                        for i, arg in enumerate(expr.args):
                            if i < len(names) and names[i] in passthrough:
                                arg_flows = flows(arg)
                                for pt in passthrough[names[i]]:
                                    for x in arg_flows:
                                        out |= self._place(x, pt)
                        for kw in expr.keywords:
                            if kw.arg in passthrough:
                                kw_flows = flows(kw.value)
                                for pt in passthrough[kw.arg]:
                                    for x in kw_flows:
                                        out |= self._place(x, pt)
                    return out
                # unknown call: only container-preserving calls pass their input through
                # (dict(x), sorted(x), x.copy(), _json_clean(x)); len/str/hash/bool/... carry no block.
                callee_name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                if callee_name not in PASSTHROUGH_CALLS:
                    return set()
                out = flows(f.value) if isinstance(f, ast.Attribute) else set()
                for a in expr.args:
                    out |= flows(a.value if isinstance(a, ast.Starred) else a)
                for kw in expr.keywords:
                    out |= {x.at((kw.arg,)) for x in flows(kw.value)} if kw.arg else flows(kw.value)
                return out
            if isinstance(expr, (ast.Lambda, ast.Compare, ast.UnaryOp, ast.JoinedStr, ast.FormattedValue)):
                return set()
            if isinstance(expr, ast.BinOp) and not isinstance(expr.op, (ast.Add, ast.BitOr)):
                return set()
            out = set()
            for child in ast.iter_child_nodes(expr):
                if isinstance(child, ast.comprehension):
                    out |= flows(child.iter)
                elif isinstance(child, ast.expr):
                    out |= flows(child)
            return out

        def bind(target: ast.AST, fl: set[Flow]) -> None:
            if isinstance(target, ast.Name):
                env.setdefault(target.id, set()).update(fl)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    bind(elt, fl)
            elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                sl = target.slice
                key = sl.value if isinstance(sl, ast.Constant) and isinstance(sl.value, str) else None
                env.setdefault(target.value.id, set()).update({x.at((key,)) for x in fl} if key else fl)
            elif isinstance(target, ast.Subscript):
                # out["a"]["b"] = x  -> place under the innermost named variable with the full path
                keys: list[str] = []
                cur: ast.AST = target
                while isinstance(cur, ast.Subscript):
                    sl = cur.slice
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        keys.insert(0, sl.value)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    env.setdefault(cur.id, set()).update({x.at(tuple(keys)) for x in fl})

        def visit(stmts: list[ast.stmt]) -> None:
            for st in stmts:
                if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(st, ast.Assign):
                    fl = flows(st.value)
                    for t in st.targets:
                        bind(t, fl)
                elif isinstance(st, (ast.AnnAssign, ast.AugAssign)) and st.value is not None:
                    bind(st.target, flows(st.value))
                elif isinstance(st, ast.Return):
                    returns.update(flows(st.value))
                elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
                    call = st.value
                    f = call.func
                    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.attr in (
                        "append", "extend", "update", "insert", "setdefault", "add", "appendleft",
                    ):
                        fl: set[Flow] = set()
                        args = call.args[1:] if f.attr in ("insert", "setdefault") else call.args
                        for a in args:
                            fl |= flows(a)
                        for kw in call.keywords:
                            fl |= {x.at((kw.arg,)) for x in flows(kw.value)} if kw.arg else flows(kw.value)
                        if f.attr == "setdefault" and call.args and isinstance(call.args[0], ast.Constant):
                            fl = {x.at((str(call.args[0].value),)) for x in fl}
                        env.setdefault(f.value.id, set()).update(fl)
                elif isinstance(st, (ast.For, ast.AsyncFor)):
                    bind(st.target, flows(st.iter))
                    visit(st.body)
                    visit(st.orelse)
                elif isinstance(st, (ast.With, ast.AsyncWith)):
                    for item in st.items:
                        if item.optional_vars is not None:
                            bind(item.optional_vars, flows(item.context_expr))
                    visit(st.body)
                elif isinstance(st, (ast.If, ast.While)):
                    visit(st.body)
                    visit(st.orelse)
                elif isinstance(st, ast.Try) or type(st).__name__ == "TryStar":
                    visit(st.body)
                    for h in st.handlers:
                        visit(h.body)
                    visit(st.orelse)
                    visit(st.finalbody)
                elif isinstance(st, ast.Match):
                    for case in st.cases:
                        visit(case.body)

        # A reader that filters stored rows by schema (``row.get("schema") != SCHEMA``)
        # returns rows of that schema: credit it at the return root.
        filtered: set[Flow] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare):
                for sub in [node.left, *node.comparators]:
                    for leaf in ast.walk(sub):
                        if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str) and SCHEMA_VALUE_RE.match(leaf.value):
                            filtered.add(Flow("schema", leaf.value))
                        elif isinstance(leaf, ast.Name) and leaf.id not in env:
                            const = mod.consts.get(leaf.id) or self._imported_const(mod, local_imports, leaf)
                            if const:
                                filtered.add(Flow("schema", const))
                        elif isinstance(leaf, ast.Attribute):
                            const = self._imported_const(mod, local_imports, leaf)
                            if const:
                                filtered.add(Flow("schema", const))

        # two passes so a variable filled after first use (loops, late updates) is seen at the return
        visit(list(fn.body))
        returns.clear()
        visit(list(fn.body))
        own_params = set(params)
        if returns and filtered:
            returns |= filtered

        return {f for f in returns if f.kind != "param" or f.name in own_params}

    @staticmethod
    def _place(x: Flow, passthrough: Flow) -> set[Flow]:
        """An argument flow re-emitted where the callee places (a selection of) its parameter."""
        cur = {x}
        for key in passthrough.sel:
            cur = _select(cur, key)
        return {f.at(passthrough.path) for f in cur}

    # ── resolved views ───────────────────────────────────────────────────────
    def placements(self, producer: str) -> dict[str, set[tuple[str, ...]]]:
        """origin key ('schema:X@v1' / 'fn:mod.py::f') -> key paths where the producer's
        response carries it.

        A schema counts only where its own block lands (a field selected out of the
        block, e.g. a timestamp, is not the block).  A delegated function counts where
        its envelope or one key under it lands (``getter().get("market_context")``)."""
        out: dict[str, set[tuple[str, ...]]] = {}
        for f in self.emitted(producer):
            if f.kind == "schema" and not f.sel:
                out.setdefault(f"schema:{f.name}", set()).add(f.path)
            elif f.kind == "fn" and len(f.sel) <= 1:
                out.setdefault(f"fn:{f.name}", set()).add(f.path)
        return out


_PROP_RE = re.compile(r"(?:\?\.|(?<![.\d])\.)\s*([A-Za-z_$][\w$]*)")
_INDEX_RE = re.compile(r"\[\s*['\"]([A-Za-z_$][\w$-]*)['\"]\s*\]")
_DESTRUCTURE_RE = re.compile(r"\{([^{}=]*)\}\s*=\s*[A-Za-z_$(]")


@functools.lru_cache(maxsize=256)
def read_keys(text: str) -> frozenset[str]:
    """Property names the source reads: ``x.k``, ``x?.k``, ``x['k']``, ``const { k } = x``."""
    keys = set(_PROP_RE.findall(text)) | set(_INDEX_RE.findall(text))
    for m in _DESTRUCTURE_RE.finditer(text):
        for part in m.group(1).split(","):
            name = part.split(":", 1)[0].split("=", 1)[0].strip().lstrip(".")
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                keys.add(name)
    return frozenset(keys)


def consumer_reads_key(text: str, key: str) -> bool:
    return key in read_keys(text)


def consumer_reads_path(text: str, path: tuple[str, ...] | list[str]) -> bool:
    """True when the consumer source reads every segment of ``path`` as a property."""
    keys = read_keys(text)
    return all(seg in keys for seg in path)
