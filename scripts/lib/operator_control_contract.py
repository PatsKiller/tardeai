#!/usr/bin/env python3
"""operator_control_contract.py — every operator control, and what can be proven about it.

An operator control is any place the Command Center leaves read-only: a fetch with
POST, PUT, PATCH or DELETE. Three questions have to be answerable for each one
before the surface can be called honest:

  1. Does the method the UI sends match the method the server routes?
     A UI that POSTs to a GET-only path fails silently as a 404/405 the operator
     reads as "nothing happened".
  2. What is the request schema, and what does the server do when it is wrong?
  3. Who is allowed, and what happens on conflict or replay?

Questions 1 and 2 are answerable statically and hermetically: both sides are in
this repository, and a no-write harness can observe exactly what the page sends.
Question 3 is answerable only by executing the control. This module therefore
publishes a PROVABILITY class per control instead of pretending otherwise, and
names the exact obstruction where one exists.

AUTHORITY: READ_ONLY_ADVISORY. Static analysis only — it parses source. It never
issues a request, never imports a handler, never touches a broker, order, provider,
scheduler, credential or production path.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "OperatorControlContract@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "1.0.0"

FRONTEND_SRC = ROOT / "apps" / "command-center-v3" / "src"
API_V2 = ROOT / "scripts" / "api_v2.py"

MUTATING = ("POST", "PUT", "PATCH", "DELETE")

# ── provability classes ──────────────────────────────────────────────────────
PROVABLE_HERMETIC = "PROVABLE_HERMETIC"
"""Method + schema + UI result observable in a no-write harness."""

UNPROVABLE_WITHOUT_PRODUCTION_WRITE = "UNPROVABLE_WITHOUT_PRODUCTION_WRITE"
"""Authorization / validation / conflict / replay require executing the control."""

OUT_OF_SCOPE_BROKER = "OUT_OF_SCOPE_BROKER"
"""AGENTS.md rule 2: the broker execution subsystem is not to be exercised at all."""

#: Paths whose execution is forbidden outright, not merely unproven.
BROKER_MARKERS = (
    "/broker-orders/",
    "/order",
    "/place",
    "/execute",
    "/atm/",
    "/promote-from-paper",
    "/manual-submit",
)

#: Controls that pass through the single guarded door.
GUARDED_MARKERS = ("/admin/", "/health/remediate", "/consumption/process-mode", "/config/")

#: The call head only. The options object is read with a brace scanner, because a
#: non-greedy regex stops at the first `}` — which is `headers: {...}` — and would
#: silently report every control as having no request body.
_FETCH_HEAD_RE = re.compile(r"fetch\(\s*(?P<q>[`'\"])(?P<path>[^`'\"]+)(?P=q)\s*,\s*\{")
_METHOD_RE = re.compile(r"method:\s*['\"](?P<m>[A-Z]+)['\"]")
_BODY_KEYS_RE = re.compile(r"JSON\.stringify\(\s*\{(?P<keys>.{0,600}?)\}\s*\)", re.S)
_KEY_RE = re.compile(r"(?:^|[,{\s])(?P<k>[A-Za-z_][A-Za-z0-9_]*)\s*:")

_SERVER_ROUTE_RE = re.compile(r'method\s*==\s*"(?P<m>POST|PUT|PATCH|DELETE)"\s*and\s*base_path\s*==\s*"(?P<p>[^"]+)"')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise(path: str) -> str:
    """Strip template interpolation and query so a call site can be matched."""
    p = path.split("?")[0]
    p = re.sub(r"\$\{[^}]*\}", "{param}", p)
    return p.rstrip("/") or "/"


def _method_from_test(node: ast.AST) -> set[str]:
    """Methods asserted by a comparison like ``method == "POST"``."""
    _ast = ast

    out: set[str] = set()
    for cmp_node in _ast.walk(node):
        if not isinstance(cmp_node, _ast.Compare):
            continue
        left = cmp_node.left
        if isinstance(left, _ast.Name) and left.id == "method":
            for op, comparator in zip(cmp_node.ops, cmp_node.comparators):
                if isinstance(op, _ast.Eq) and isinstance(comparator, _ast.Constant):
                    if isinstance(comparator.value, str):
                        out.add(comparator.value.upper())
                if isinstance(op, _ast.In) and isinstance(comparator, (_ast.Tuple, _ast.List, _ast.Set)):
                    out |= {
                        e.value.upper()
                        for e in comparator.elts
                        if isinstance(e, _ast.Constant) and isinstance(e.value, str)
                    }
    return out


def _prefix_suffix_from_test(node: ast.AST) -> set[tuple[str, str]]:
    """Paths matched as ``base_path.startswith(P) and base_path.endswith(S)``.

    Parameterised writes (``/api/v2/watchlist/<symbol>/plan``) are dispatched this
    way. Missing them would report a live control as unrouted.
    """
    pre: set[str] = set()
    suf: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        obj = call.func.value
        if not (isinstance(obj, ast.Name) and obj.id in ("base_path", "path")):
            continue
        if not call.args or not isinstance(call.args[0], ast.Constant):
            continue
        val = call.args[0].value
        if not isinstance(val, str):
            continue
        if call.func.attr == "startswith" and val.startswith("/api/"):
            pre.add(val)
        elif call.func.attr == "endswith":
            suf.add(val)
    if not pre:
        return set()
    return {(a, b) for a in pre for b in (suf or {""})}


def _paths_from_test(node: ast.AST) -> set[str]:
    """Paths asserted by ``base_path == "/api/..."`` or ``base_path in (...)``."""
    _ast = ast

    out: set[str] = set()
    for cmp_node in _ast.walk(node):
        if not isinstance(cmp_node, _ast.Compare):
            continue
        left = cmp_node.left
        if not (isinstance(left, _ast.Name) and left.id in ("base_path", "path")):
            continue
        for op, comparator in zip(cmp_node.ops, cmp_node.comparators):
            if isinstance(op, _ast.Eq) and isinstance(comparator, _ast.Constant):
                if isinstance(comparator.value, str) and comparator.value.startswith("/api/"):
                    out.add(comparator.value)
            if isinstance(op, _ast.In) and isinstance(comparator, (_ast.Tuple, _ast.List, _ast.Set)):
                out |= {
                    e.value
                    for e in comparator.elts
                    if isinstance(e, _ast.Constant) and isinstance(e.value, str) and e.value.startswith("/api/")
                }
    return out


def server_write_prefix_routes(api_path: Path | None = None) -> dict[tuple[str, str], set[str]]:
    """(prefix, suffix) -> methods, for parameterised write dispatch."""
    src = (api_path or API_V2).read_text(errors="replace")
    tree = ast.parse(src)
    handle = next(
        (n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "handle"),
        None,
    )
    out: dict[tuple[str, str], set[str]] = {}
    if handle is None:
        return out

    def walk(node: ast.AST, methods: set[str]) -> None:
        if isinstance(node, ast.If):
            here = _method_from_test(node.test) or set(methods)
            for pair in _prefix_suffix_from_test(node.test):
                for m in here & set(MUTATING):
                    out.setdefault(pair, set()).add(m)
            for child in node.body:
                walk(child, here)
            for child in node.orelse:
                walk(child, methods)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, methods)

    for stmt in handle.body:
        walk(stmt, set())
    return out


def other_module_write_paths() -> dict[str, str]:
    """Write paths served by sibling modules (control_plane_api, api_v3_*, ...).

    api_v2 is not the whole server. A path documented as a POST route in another
    module is routed; calling it unregistered would be a manufactured finding.
    """
    out: dict[str, str] = {}
    for f in sorted((ROOT / "scripts").glob("*.py")):
        if f.name == "api_v2.py":
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"(POST|PUT|PATCH|DELETE)\s+(/api/v[23]/[A-Za-z0-9_\-/{}<>:.]+)", text):
            out.setdefault(_normalise(m.group(2)), str(f.relative_to(ROOT)))
    return out


def server_write_routes(api_path: Path | None = None) -> dict[str, set[str]]:
    """Every (path -> methods) the served dispatcher actually routes for writes.

    api_v2.handle() mixes two shapes — a flat ``method == "POST" and base_path ==``
    test, and a ``if method == "POST":`` block wrapping bare ``base_path ==`` tests.
    A regex over the flat form alone misses ~90 real routes and would manufacture a
    fleet of false "unregistered control" findings, so the dispatcher is walked as
    an AST with the enclosing method guard carried down.
    """
    _ast = ast

    src = (api_path or API_V2).read_text(errors="replace")
    tree = _ast.parse(src)
    handle = next(
        (n for n in tree.body if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and n.name == "handle"),
        None,
    )
    out: dict[str, set[str]] = {}
    if handle is None:
        return out

    def walk(node: ast.AST, methods: set[str]) -> None:
        if isinstance(node, _ast.If):
            here = _method_from_test(node.test) or set(methods)
            for p in _paths_from_test(node.test):
                for m in here & set(MUTATING):
                    out.setdefault(_normalise(p), set()).add(m)
            for child in node.body:
                walk(child, here)
            for child in node.orelse:
                walk(child, methods)
            return
        for child in _ast.iter_child_nodes(node):
            walk(child, methods)

    for stmt in handle.body:
        walk(stmt, set())
    return out


def _balanced_object(text: str, open_idx: int, limit: int = 4000) -> str | None:
    """Return the contents of the ``{...}`` starting at ``open_idx``.

    Brace-aware and quote-aware, so a nested ``headers: {...}`` or a string
    containing a brace does not truncate the options object.
    """
    if open_idx >= len(text) or text[open_idx] != "{":
        return None
    depth = 0
    i = open_idx
    end = min(len(text), open_idx + limit)
    quote: str | None = None
    while i < end:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i]
        i += 1
    return None


def frontend_controls(src_root: Path | None = None) -> list[dict[str, Any]]:
    """Every non-GET fetch in the Command Center, with its declared body keys."""
    root = src_root or FRONTEND_SRC
    rows: list[dict[str, Any]] = []
    for f in sorted(root.rglob("*.ts")) + sorted(root.rglob("*.tsx")):
        if f.name.endswith(".test.ts") or f.name.endswith(".test.tsx"):
            continue
        text = f.read_text(errors="replace")
        for m in _FETCH_HEAD_RE.finditer(text):
            opts = _balanced_object(text, m.end() - 1)
            if opts is None:
                continue
            mm = _METHOD_RE.search(opts)
            method = mm.group("m") if mm else "GET"
            if method not in MUTATING:
                continue
            keys: list[str] = []
            bm = _BODY_KEYS_RE.search(opts)
            if bm:
                keys = sorted({k.group("k") for k in _KEY_RE.finditer(bm.group("keys"))})
            try:
                rel = str(f.relative_to(ROOT))
            except ValueError:
                # A caller may point the extractor at a tree outside the repo
                # (tests do). Report the path it was actually given.
                rel = str(f)
            rows.append(
                {
                    "file": rel,
                    "line": text.count("\n", 0, m.start()) + 1,
                    "method": method,
                    "path_literal": m.group("path"),
                    "path": _normalise(m.group("path")),
                    "body_keys": keys,
                    "sends_operator": "operator" in keys,
                    "sends_token": "token" in keys,
                    "two_step_confirm": "confirm" in keys,
                }
            )
    return rows


def _classify(path: str) -> tuple[str, str]:
    if any(k in path for k in BROKER_MARKERS):
        return (
            OUT_OF_SCOPE_BROKER,
            "AGENTS.md rule 2: the broker execution subsystem must not be modified, tested against "
            "or invoked. This control is never exercised, in any environment.",
        )
    if any(k in path for k in GUARDED_MARKERS):
        return (
            UNPROVABLE_WITHOUT_PRODUCTION_WRITE,
            "the control passes through admin_write_guard.admin_write(), whose AUDIT step appends to "
            "the append-only admin_audit_log on EVERY outcome including rejection; the only reachable "
            "PostgreSQL cluster is production, so authorization/validation/conflict/replay cannot be "
            "exercised without a production write",
        )
    return (
        PROVABLE_HERMETIC,
        "method and request schema are observable in the no-write harness; the server refuses the "
        "write, so the UI result under refusal is also observable",
    )


def contract(src_root: Path | None = None, api_path: Path | None = None) -> dict[str, Any]:
    """The full operator-control ledger."""
    controls = frontend_controls(src_root)
    routes = server_write_routes(api_path)
    prefix_routes = server_write_prefix_routes(api_path)
    elsewhere = other_module_write_paths()

    rows = []
    for c in controls:
        path = c["path"]
        served = routes.get(path)
        matched_on = "exact" if served else None
        if served is None:
            stem = path.split("/{param}")[0]
            served = routes.get(stem)
            matched_on = "stem" if served else None
        if served is None:
            for (pre, suf), ms in prefix_routes.items():
                if path.startswith(pre) and (not suf or path.endswith(suf)):
                    served, matched_on = ms, f"prefix:{pre}|suffix:{suf or '*'}"
                    break
        if served is None and path in elsewhere:
            served, matched_on = {c["method"]}, f"module:{elsewhere[path]}"
        method_ok = bool(served) and c["method"] in served
        provability, reason = _classify(c["path"])
        rows.append(
            {
                **c,
                "server_methods": sorted(served) if served else [],
                "route_matched_on": matched_on,
                "method_correct": method_ok,
                "route_registered": bool(served),
                "provability": provability,
                "provability_reason": reason,
                "must_never_be_invoked": provability == OUT_OF_SCOPE_BROKER,
            }
        )

    by_prov: dict[str, int] = {}
    for r in rows:
        by_prov[r["provability"]] = by_prov.get(r["provability"], 0) + 1
    unregistered = [r for r in rows if not r["route_registered"]]
    for r in unregistered:
        r["unregistered_note"] = (
            "no write route found in api_v2.handle() (exact, stem, or prefix/suffix dispatch) "
            "and no sibling module documents this path as a write route; this is an EXTRACTION "
            "RESULT, and a dynamic dispatch this analysis cannot see would also land here"
        )
    wrong_method = [r for r in rows if r["route_registered"] and not r["method_correct"]]

    return {
        "schema": SCHEMA,
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _now(),
        "control_count": len(rows),
        "distinct_paths": len({r["path"] for r in rows}),
        "server_write_route_count": len(routes),
        "provability_counts": dict(sorted(by_prov.items())),
        "unregistered_count": len(unregistered),
        "wrong_method_count": len(wrong_method),
        "controls": rows,
        "note": (
            "Provability is a property of the environment, not a verdict on the control. "
            "PROVABLE_HERMETIC means method, schema and refusal behaviour are observable without a "
            "write. The other two classes name exactly why execution is not available here."
        ),
    }


def to_csv_rows(rep: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "file": c["file"],
            "line": c["line"],
            "method": c["method"],
            "path": c["path"],
            "route_registered": c["route_registered"],
            "server_methods": "|".join(c["server_methods"]),
            "method_correct": c["method_correct"],
            "body_keys": "|".join(c["body_keys"]),
            "two_step_confirm": c["two_step_confirm"],
            "sends_token": c["sends_token"],
            "provability": c["provability"],
            "must_never_be_invoked": c["must_never_be_invoked"],
            "provability_reason": c["provability_reason"],
        }
        for c in rep["controls"]
    ]


if __name__ == "__main__":  # pragma: no cover - operator convenience
    rep = contract()
    print(json.dumps({k: v for k, v in rep.items() if k != "controls"}, indent=2))
