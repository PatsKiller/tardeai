#!/usr/bin/env python3
"""Static API contract census for the CIO-related Command Center surfaces.

Schema: CIOApiContractCensus@v2 (source census; no runtime claim)

Frontend side
    Starts from the five routed pages (CIO, Advisory, Agents, Hermes, Research
    Intelligence) and follows local imports transitively (pages + components +
    hooks + lib).  Every string/template literal containing ``/api/v2/`` or
    ``/api/v3/`` that is a direct argument of a call (useApi, fetch, getRows,
    post, ...) is a *fetch*; ``const X = '/api/...'`` constants referenced
    elsewhere are *route constants*.  Literals in drill contexts / labels are
    ignored.  For each fetch: consumer ``file:line``, call kind, polling
    interval (useApi/useJson second argument) and whether the result is bound
    and used.

Backend side
    Parses ``scripts/api_v2.py`` dispatch (``ROUTES`` dict, ``base_path ==``,
    ``base_path in (...)``, ``base_path.startswith`` blocks and their
    sub-dispatch ``p == / p in / p.startswith``), the agent-runtime
    ``READ_ROUTES`` table and the portfolio-server prefix handlers.  Each route
    maps to a producer function; the function body is scanned (ast) for clock
    fields, ``Name@vN`` schema literals, error envelopes and silent
    ``except: pass``.

Detections (all computed, none hard-coded)
    unused_fetches, dead_calls (no backend handler), unconsumed_routes
    (backend routes in these families with no Command Center v3 consumer),
    duplicate endpoint families, v2/v3 mixing per family, polling intervals,
    silent except-pass in handlers.
"""
from __future__ import annotations

import argparse
import ast
import functools
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "CIOApiContractCensus@v2"
NO_CONSUMER_REASON = "Source-side CLI/report artifact; runtime API consumption is intentionally not claimed."

SRC = Path("apps/command-center-v3/src")
SURFACES = {
    "CIO": "pages/CioHub.tsx",
    "Advisory": "pages/AdvisoryDeskHub.tsx",
    "Agents": "pages/AgentRuntimeHub.tsx",
    "Hermes": "pages/HermesHub.tsx",
    "Research Intelligence": "pages/ResearchIntelligenceHub.tsx",
}
FAMILIES: dict[str, tuple[str, ...]] = {
    "CIO": ("/api/v3/cio", "/api/v2/cio"),
    "Advisory": ("/api/v3/advisory", "/api/v2/advisory"),
    "Agents": ("/api/v3/agent-runtime", "/api/v3/agent-maturity", "/api/v3/agents", "/api/v2/agents", "/api/v2/agent-"),
    "Hermes": ("/api/v3/hermes", "/api/v2/hermes"),
    "Research Intelligence": ("/api/v2/research-intelligence", "/api/v3/intelligence", "/api/v2/research/"),
}
BACKEND_FILES = {
    "api_v2": Path("scripts/api_v2.py"),
    "portfolio_server": Path("scripts/portfolio_server.py"),
    "agent_runtime_read": Path("scripts/agent_runtime/read_api.py"),
}
FETCH_CALLEES = frozenset({
    "useApi", "useJson", "fetch", "doFetch", "getRows", "post", "postJson", "fire", "getJson", "fetchJson",
    "apiGet", "apiPost", "request", "useCachedApi", "usePolledApi",
})
CLOCK_FIELDS = ("source_as_of", "composition_as_of", "as_of", "generated_at", "updated_at")
ROUTE_LITERAL_RE = re.compile(r"(?P<q>[`'\"])(?P<body>(?:\$\{[^}`]*\})?/api/v[23]/[^`'\"\s]*)(?P=q)")
SCHEMA_RE = re.compile(r"[\"']([A-Z][A-Za-z0-9]+@v\d+)[\"']")
CLOCK_RE = re.compile(r"[\"'](" + "|".join(CLOCK_FIELDS) + r")[\"']")


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _serving_sha(root: Path) -> Optional[str]:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _strip_interpolations(route: str) -> str:
    """Replace each top-level ``${...}`` (with nesting) by a marker: ``/{param}`` when it is a
    whole path segment, otherwise dropped (a query/suffix builder such as ``${q ? `?x=1` : ''}``)."""
    out: list[str] = []
    i = 0
    while i < len(route):
        if route.startswith("${", i):
            depth = 0
            j = i
            while j < len(route):
                if route.startswith("${", j):
                    depth += 1
                    j += 2
                    continue
                if route[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            prev = out[-1] if out else ""
            if prev.endswith("/") or not out:
                out.append("{param}")
            i = j + 1
            continue
        out.append(route[i])
        i += 1
    return "".join(out)


def normalize_route(route: str) -> str:
    route = re.sub(r"^\$\{[^}]*\}(?=/api/)", "", route)
    route = _strip_interpolations(route)
    route = route.split("?", 1)[0].split("#", 1)[0]
    route = re.sub(r"\{param\}(\{param\})+", "{param}", route)
    if route.startswith("{param}/api/"):
        route = route[len("{param}"):]
    return route.rstrip("/") or "/"


def iter_route_literals(text: str):
    """Yield (start, raw) for every string/template literal containing /api/v2/ or /api/v3/.

    Handles nested ``${ `...` }`` inside template literals, which a flat regex cannot.
    """
    for m in re.finditer(r"/api/v[23]/", text):
        pos = m.start()
        # walk back to the opening quote on the same logical literal
        i = pos - 1
        depth = 0
        quote_at = -1
        while i >= 0 and pos - i < 400:
            ch = text[i]
            if ch == "}":
                depth += 1
            elif ch == "{" and i > 0 and text[i - 1] == "$":
                depth -= 1
            elif depth <= 0 and ch in "'\"`":
                quote_at = i
                break
            elif depth <= 0 and ch == "\n" and text[i - 1:i] != "\\":
                break
            i -= 1
        if quote_at < 0:
            continue
        q = text[quote_at]
        if q != "`" and "${" in text[quote_at:pos]:
            continue
        # forward to the matching closing quote
        j = quote_at + 1
        depth = 0
        while j < len(text) and j - quote_at < 800:
            if q == "`" and text.startswith("${", j):
                depth += 1
                j += 2
                continue
            ch = text[j]
            if depth > 0:
                if ch == "}":
                    depth -= 1
                elif ch == "`":
                    # nested template inside ${...}: skip it
                    k = text.find("`", j + 1)
                    j = k if k != -1 else j
            elif ch == q:
                break
            elif ch == "\n" and q != "`":
                break
            j += 1
        raw = text[quote_at + 1:j]
        if "/api/v" not in raw or text.find("/api/v", quote_at + 1) != pos:
            continue
        yield quote_at, raw


def family_of(route: str) -> Optional[str]:
    for fam, prefixes in FAMILIES.items():
        if any(route == p or route.startswith(p if p.endswith(("-", "/")) else p + "/") or route == p for p in prefixes):
            return fam
        if any(p.endswith(("-", "/")) and route.startswith(p) for p in prefixes):
            return fam
    return None


# ── frontend ──────────────────────────────────────────────────────────────────
IMPORT_RE = re.compile(r"""(?:import|export)\s[^'"]*?from\s+['"](\.{1,2}/[^'"]+)['"]|import\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""")


def _resolve_import(base: Path, spec: str) -> Optional[Path]:
    target = (base.parent / spec).resolve()
    candidates = [target] if target.suffix in (".ts", ".tsx") else []
    candidates += [target.with_name(target.name + ext) for ext in (".tsx", ".ts")]
    candidates += [target / "index.tsx", target / "index.ts"]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def import_closure(entries: Iterable[Path]) -> dict[Path, set[str]]:
    """file -> set of surfaces whose page transitively imports it."""
    owners: dict[Path, set[str]] = {}
    for surface, entry in entries:
        stack = [entry]
        seen: set[Path] = set()
        while stack:
            cur = stack.pop()
            if cur in seen or not cur.is_file():
                continue
            seen.add(cur)
            owners.setdefault(cur, set()).add(surface)
            if cur.name.endswith((".test.ts", ".test.tsx")):
                continue
            text = cur.read_text(encoding="utf-8", errors="replace")
            for match in IMPORT_RE.finditer(text):
                spec = match.group(1) or match.group(2)
                if spec.endswith(".css"):
                    continue
                nxt = _resolve_import(cur, spec)
                if nxt and not nxt.name.endswith((".test.ts", ".test.tsx")):
                    stack.append(nxt)
    return owners


def _enclosing_callee(text: str, pos: int) -> tuple[Optional[str], int]:
    """Identifier of the call whose argument list directly contains ``pos`` (or None)."""
    depth_paren = depth_brace = depth_brack = 0
    i = pos - 1
    limit = max(0, pos - 600)
    while i >= limit:
        ch = text[i]
        if ch == ")":
            depth_paren += 1
        elif ch == "(":
            if depth_paren == 0:
                if depth_brace or depth_brack:
                    return None, -1
                j = i - 1
                # skip generic type args: useApi<any>(
                if j >= 0 and text[j] == ">":
                    k = text.rfind("<", max(0, j - 80), j)
                    if k != -1:
                        j = k - 1
                end = j + 1
                while j >= 0 and (text[j].isalnum() or text[j] in "_$."):
                    j -= 1
                name = text[j + 1:end].split(".")[-1]
                return (name or None), i
            depth_paren -= 1
        elif ch == "}":
            depth_brace += 1
        elif ch == "{":
            if depth_brace == 0:
                # Inside ${...} of a template literal is still an argument; otherwise an object/JSX.
                if i > 0 and text[i - 1] == "$":
                    pass
                else:
                    return None, -1
            else:
                depth_brace -= 1
        elif ch == "]":
            depth_brack += 1
        elif ch == "[":
            if depth_brack == 0:
                return None, -1
            depth_brack -= 1
        elif ch in ";":
            return None, -1
        i -= 1
    return None, -1


def _statement_start(text: str, pos: int) -> int:
    i = text.rfind("\n", 0, pos)
    return i + 1


def _parse_interval(arg: str) -> Optional[int]:
    arg = arg.strip().replace("_", "")
    m = re.match(r"^(\d+)(?:\s*\*\s*(\d+))?(?:\s*\*\s*(\d+))?$", arg)
    if not m:
        return None
    out = 1
    for g in m.groups():
        if g:
            out *= int(g)
    return out


@dataclass
class Fetch:
    route: str
    raw: str
    file: str
    line: int
    callee: str
    surfaces: list[str]
    poll_ms: Optional[int] = None
    bound_names: list[str] = field(default_factory=list)
    used: Optional[bool] = None
    method: str = "GET"


def _call_args_text(text: str, open_paren: int) -> str:
    depth = 0
    i = open_paren
    while i < len(text) and i < open_paren + 4000:
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:i]
        i += 1
    return text[open_paren + 1:open_paren + 400]


def _split_top_args(args: str) -> list[str]:
    out, depth, cur, quote = [], 0, [], None
    for ch in args:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def _binding(text: str, stmt_start: int, open_paren: int) -> tuple[list[str], str]:
    """Names bound by ``const ... = [await] callee(`` and the binding kind."""
    head = text[stmt_start:open_paren]
    m = re.search(r"(?:const|let|var)\s+\{([^}]*)\}\s*=\s*(?:await\s+)?[\w$.<>, ]*$", head)
    if m:
        names = []
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                part = part.split(":", 1)[1]
            part = part.split("=", 1)[0].strip()
            if part and part.isidentifier():
                names.append(part)
        return names, "destructure"
    m = re.search(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:await\s+)?[\w$.<>, ]*$", head)
    if m:
        return [m.group(1)], "assign"
    stripped = head.strip()
    if stripped in ("", "await", "void", "void await") :
        return [], "discarded"
    return [], "expression"


_STRING_RE = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")
_HOOK_RE = re.compile(r"\b(?:useMemo|useEffect|useCallback|useLayoutEffect)\s*(?:<[^>()]*>)?\(")


@functools.lru_cache(maxsize=128)
def _code_only(text: str) -> str:
    """Blank out plain string literals and hook dependency arrays (``}, [a, b])``).

    A name that appears only in a deps array or inside a string is not a use.
    Template literals are kept: ``${name}`` inside them is a real use.
    """
    text = _STRING_RE.sub(lambda m: " " * len(m.group(0)), text)
    text = _blank_template_text(text)
    out = list(text)
    for m in _HOOK_RE.finditer(text):
        open_paren = m.end() - 1
        depth, i, last_top_comma = 0, open_paren, -1
        while i < len(text):
            ch = text[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                last_top_comma = i
            i += 1
        if last_top_comma != -1:
            tail = text[last_top_comma + 1:i]
            if tail.strip().startswith("["):
                for k in range(last_top_comma + 1, i):
                    if out[k] != "\n":
                        out[k] = " "
    return "".join(out)


def _blank_template_text(text: str) -> str:
    """Blank the static text of template literals, keeping ``${...}`` expressions."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text[i] != "`":
            i += 1
            continue
        out[i] = " "
        i += 1
        while i < n and text[i] != "`":
            if text.startswith("${", i):
                depth = 1
                i += 2
                while i < n and depth:
                    if text.startswith("${", i):
                        depth += 1
                        i += 2
                        continue
                    if text[i] == "}":
                        depth -= 1
                    elif text[i] == "`":
                        # nested template: skip to its end, blanking text
                        j = text.find("`", i + 1)
                        for k in range(i, (j if j != -1 else i) + 1):
                            out[k] = " "
                        i = (j if j != -1 else i) + 1
                        continue
                    i += 1
                continue
            if text[i] != "\n":
                out[i] = " "
            i += 1
        if i < n:
            out[i] = " "
        i += 1
    return "".join(out)


def _name_used(text: str, name: str, *, decl_pos: int, _depth: int = 0) -> bool:
    code = _code_only(text)
    pattern = re.compile(rf"(?<![\w$.]){re.escape(name)}\b(?!\s*:)")
    hits = [m for m in pattern.finditer(code)]
    # drop the binding occurrence itself (the one in the declaring statement)
    stmt = code.rfind("\n", 0, decl_pos)
    hits = [m for m in hits if not (stmt <= m.start() <= decl_pos)]
    if not hits:
        return False
    if _depth >= 2:
        return True
    # one-hop aliases: const alias = name ?? {}  -> the alias must itself be used
    for m in hits:
        line_start = code.rfind("\n", 0, m.start()) + 1
        line = code[line_start:code.find("\n", m.start())]
        am = re.match(rf"\s*(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*{re.escape(name)}\b[^;]*$", line)
        if am and am.group(1) != name:
            if _name_used(text, am.group(1), decl_pos=m.start(), _depth=_depth + 1):
                return True
            continue
        return True
    return False


def scan_frontend(root: Path) -> tuple[list[Fetch], list[dict[str, Any]], dict[Path, set[str]]]:
    src = root / SRC
    entries = [(surface, src / rel) for surface, rel in SURFACES.items()]
    owners = import_closure(entries)
    fetches: list[Fetch] = []
    constants: list[dict[str, Any]] = []
    for path, surfaces in sorted(owners.items()):
        text = path.read_text(encoding="utf-8", errors="replace")
        for start, raw in iter_route_literals(text):
            line = text.count("\n", 0, start) + 1
            # const NAME = '/api/...'
            decl = re.search(r"(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*$", text[_statement_start(text, start):start])
            if decl:
                name = decl.group(1)
                refs = sum(len(re.findall(rf"\b{re.escape(name)}\b", p.read_text(encoding="utf-8", errors="replace"))) for p in owners)
                constants.append({
                    "route": normalize_route(raw), "name": name, "file": _rel(path, root), "line": line,
                    "referenced": refs > 1, "surfaces": sorted(surfaces),
                })
                continue
            callee, open_paren = _enclosing_callee(text, start)
            via = None
            if callee and callee not in FETCH_CALLEES:
                continue  # argument of a non-fetch call (startsWith, includes, onDrill, ...)
            if not callee:
                # Indirect: const endpoint = cond ? '/api/a' : '/api/b'; useApi(endpoint, ...)
                window = text[max(0, start - 300):start]
                decls = list(re.finditer(r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=", window))
                if not decls or ";" in window[decls[-1].end():]:
                    continue
                var_name = decls[-1].group(1)
                callee_re = "|".join(sorted(FETCH_CALLEES))
                call = re.compile(rf"\b({callee_re})(?:<[^>()]*>)?\(\s*{re.escape(var_name)}\b").search(text, start)
                if not call:
                    continue
                callee = call.group(1)
                open_paren = text.index("(", call.start())
                via = var_name
            args = _split_top_args(_call_args_text(text, open_paren))
            poll_ms = None
            if callee in ("useApi", "useJson") and len(args) >= 2:
                poll_ms = _parse_interval(args[1])
            method = "GET"
            if callee in ("post", "postJson", "fire") or re.search(r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)", ",".join(args[1:])):
                method = "POST"
            stmt_start = _statement_start(text, open_paren)
            names, kind = _binding(text, stmt_start, open_paren)
            used: Optional[bool]
            if names:
                used = any(_name_used(text, n, decl_pos=start) for n in names)
            elif kind == "discarded":
                # A discarded GET result is unused; a discarded mutation is fire-and-forget by design.
                used = False if method == "GET" and callee in ("useApi", "useJson") else None
            else:
                used = None  # chained (.then / return / argument) — usage not statically decidable
            fetches.append(Fetch(
                route=normalize_route(raw), raw=raw, file=_rel(path, root), line=line, callee=callee,
                surfaces=sorted(surfaces), poll_ms=poll_ms, bound_names=names, used=used, method=method,
            ))
    return fetches, constants, owners


# ── backend ───────────────────────────────────────────────────────────────────
@dataclass
class Route:
    route: str
    kind: str  # EXACT | TEMPLATE | PREFIX | SUBPREFIX
    file: str
    line: int
    producer: Optional[str]
    method: str = "ANY"
    block_prefix: Optional[str] = None


_SKIP_CALLS = frozenset({
    "dict", "str", "int", "float", "len", "isinstance", "list", "set", "tuple", "bool", "print", "range", "sorted",
    "getattr", "hasattr", "max", "min", "any", "all", "open", "json.dumps", "json.loads", "_json_clean", "query.get",
    "body.get", "base_path.startswith", "base_path.endswith", "p.startswith", "p.endswith", "strip", "split",
})


def _producer_after(lines: list[str], idx: int, aliases: dict[str, str], span: int = 16) -> Optional[str]:
    """First producer call in the branch that starts at ``lines[idx]``.

    Stops at the next line indented at or above the guard (a sibling branch),
    so a guard's 400 early-return does not end the scan and a sibling's
    producer is never borrowed.
    """
    aliases = dict(aliases)
    base_indent = len(lines[idx]) - len(lines[idx].lstrip()) if idx < len(lines) else 0
    for j in range(idx, min(len(lines), idx + span)):
        line = lines[j]
        if j > idx and line.strip() and (len(line) - len(line.lstrip())) <= base_indent:
            break
        am = re.search(r"import\s+(\w+)\s+as\s+(\w+)", line)
        if am:
            aliases[am.group(2)] = f"{am.group(1)}.py"
            continue
        for m in re.finditer(r"(?:return\s+(?:\d+|\(\s*\d+[^,]*\))\s*,\s*|return\s+|=\s*|\(\s*)(?:_?\w+\s*\(\s*)?([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)?)\s*\(", line):
            name = m.group(1)
            if name in _SKIP_CALLS or name.split(".")[-1] in _SKIP_CALLS or name.startswith(("self.", "_os", "os.", "re.", "json.")):
                continue
            if name in ("lambda", "str", "len"):
                continue
            head = name.split(".")[0]
            if "." in name and head in aliases:
                return f"{aliases[head]}::{name.split('.', 1)[1]}"
            if "." not in name:
                return f"api_v2.py::{name}"
    return None


def _string_list(expr: str) -> list[str]:
    return re.findall(r"\"([^\"]*)\"", expr)


def scan_api_v2(root: Path) -> list[Route]:
    path = root / BACKEND_FILES["api_v2"]
    if not path.is_file():
        return []
    rel = _rel(path, root)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    routes: list[Route] = []
    in_routes = False
    for i, line in enumerate(lines):
        if re.match(r"^ROUTES\s*=\s*\{", line):
            in_routes = True
            continue
        if in_routes:
            if re.match(r"^\}", line):
                in_routes = False
                continue
            m = re.match(r"^\s+\"(/api/v[23]/[^\"]+)\"\s*:\s*(.*)$", line)
            if m:
                value = m.group(2)
                call = re.search(r"(?:lambda[^:]*:\s*)?([A-Za-z_][\w.]*)\s*\(", value)
                if call and call.group(1) != "lambda":
                    prod = call.group(1)
                elif re.match(r"^[A-Za-z_]\w*\s*,?\s*$", value.strip()):
                    prod = value.strip().rstrip(",")
                else:
                    prod = None
                routes.append(Route(m.group(1), "EXACT", rel, i + 1, f"api_v2.py::{prod}" if prod else None, "GET"))
            continue

    # Module-level / local route-prefix constants: _X_PREFIX = "/api/v2/..."
    consts: dict[str, str] = {}
    for line in lines:
        cm = re.match(r"^\s*(_?[A-Z][A-Z0-9_]*)\s*=\s*\"(/api/v[23]/[^\"]*)\"\s*$", line)
        if cm:
            consts[cm.group(1)] = cm.group(2)
    for i, line in enumerate(lines):
        for cm in re.finditer(r"base_path\.startswith\(\s*(_?[A-Z][A-Z0-9_]*)\s*\)", line):
            if cm.group(1) in consts:
                routes.append(Route(consts[cm.group(1)].rstrip("/"), "PREFIX", rel, i + 1, _producer_after(lines, i, {}), "ANY"))

    # base_path ==, base_path in (...), base_path.startswith blocks.
    i = 0
    while i < len(lines):
        line = lines[i]
        method = "POST" if re.search(r"method\s*==\s*\"POST\"", line) else ("GET" if re.search(r"method\s*==\s*\"GET\"", line) else "ANY")
        for m in re.finditer(r"base_path\s*==\s*\"(/api/v[23]/[^\"]*)\"", line):
            routes.append(Route(m.group(1).rstrip("/"), "EXACT", rel, i + 1, _producer_after(lines, i, {}) or f"api_v2.py::handle[inline:{i + 1}]", method))
        for m in re.finditer(r"base_path\s+in\s+\(([^)]*)\)", line):
            for r in _string_list(m.group(1)):
                if r.startswith("/api/v"):
                    routes.append(Route(r.rstrip("/"), "EXACT", rel, i + 1, _producer_after(lines, i, {}) or f"api_v2.py::handle[inline:{i + 1}]", method))
        sm = re.match(r"^(\s*)if\s+(?:method\s*==\s*\"\w+\"\s+and\s+)?\(?base_path\.startswith\(\"(/api/v[23]/[^\"]*)\"\)", line)
        if sm:
            indent = len(sm.group(1))
            prefix = sm.group(2)
            # block extent
            end = i + 1
            while end < len(lines):
                nxt = lines[end]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                end += 1
            block = lines[i:end]
            aliases: dict[str, str] = {}
            for bl in block:
                am = re.search(r"import\s+(\w+)\s+as\s+(\w+)", bl)
                if am:
                    aliases[am.group(2)] = f"{am.group(1)}.py"
            var = None
            for bl in block[:12]:
                vm = re.search(r"(\w+)\s*=\s*base_path\[\s*len\(\s*\"" + re.escape(prefix) + r"\"\s*\)\s*:\s*\]", bl)
                if vm:
                    var = vm.group(1)
                    break
            subs = 0
            if var:
                base = prefix.rstrip("/")
                method_ctx: list[tuple[int, str]] = []
                for k, bl in enumerate(block):
                    ind = len(bl) - len(bl.lstrip())
                    if bl.strip():
                        method_ctx = [(d, mth) for d, mth in method_ctx if ind > d]
                    mm = re.match(r"\s*if\s+method\s*==\s*\"(GET|POST)\"\s*:", bl)
                    if mm:
                        method_ctx.append((ind, mm.group(1)))
                        continue
                    bm = "POST" if 'method == "POST"' in bl else (method_ctx[-1][1] if method_ctx else None)
                    if not (re.match(r"\s*(?:if|elif)\b", bl) and bl.rstrip().endswith(":")):
                        continue  # only dispatch guards declare routes (not `x = a if p.startswith(...) else b`)
                    for em in re.finditer(rf"\b{var}\s*==\s*\"([^\"]*)\"", bl):
                        sub = em.group(1).strip("/")
                        routes.append(Route(f"{base}/{sub}" if sub else base, "EXACT", rel, i + k + 1,
                                            _producer_after(block, k, aliases), bm or "ANY", block_prefix=base))
                        subs += 1
                    for em in re.finditer(rf"\b{var}\s+in\s+\(([^)]*)\)", bl):
                        for sub in _string_list(em.group(1)):
                            sub = sub.strip("/")
                            routes.append(Route(f"{base}/{sub}" if sub else base, "EXACT", rel, i + k + 1,
                                                _producer_after(block, k, aliases), bm or "ANY", block_prefix=base))
                            subs += 1
                    for em in re.finditer(rf"\b{var}\.startswith\(\"([^\"]+)\"\)", bl):
                        sub = em.group(1)
                        routes.append(Route(f"{base}/{sub}", "SUBPREFIX", rel, i + k + 1,
                                            _producer_after(block, k, aliases), bm or "ANY", block_prefix=base))
                        subs += 1
            routes.append(Route(prefix, "PREFIX", rel, i + 1, _producer_after(lines, i + 1, aliases), method,
                                block_prefix=prefix.rstrip("/") if subs else None))
        i += 1
    return routes


def scan_agent_runtime(root: Path) -> list[Route]:
    out: list[Route] = []
    path = root / BACKEND_FILES["agent_runtime_read"]
    if path.is_file():
        rel = _rel(path, root)
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            m = re.search(r"ReadRoute\(\"(\w+)\",\s*\"(/api/v3/[^\"]+)\",\s*\"(\w+)\"\)", line)
            if m:
                kind = "TEMPLATE" if "{" in m.group(2) else "EXACT"
                out.append(Route(m.group(2), kind, rel, i + 1, f"agent_runtime/read_api.py::ReadOnlyAgentRuntimeAPI.{m.group(3)}", m.group(1)))
    http = root / "scripts/agent_runtime/read_http.py"
    if http.is_file():
        rel = _rel(http, root)
        for i, line in enumerate(http.read_text(encoding="utf-8", errors="replace").splitlines()):
            m = re.match(r"AGENT_MATURITY_READ_PREFIX\s*=\s*\"(/api/v3/[^\"]+)\"", line)
            if m:
                out.append(Route(m.group(1), "PREFIX", rel, i + 1, "agent_runtime/read_http.py::_dispatch_maturity", "GET"))
    return out


def _function_index(path: Path) -> dict[str, ast.AST]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return {}
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.setdefault(f"{node.name}.{sub.name}", sub)
    return out


class HandlerIndex:
    def __init__(self, root: Path):
        self.root = root
        self._files: dict[str, tuple[list[str], dict[str, ast.AST]]] = {}

    def _consts(self, module_file: str) -> dict[str, str]:
        lines, _ = self._load(module_file)
        out: dict[str, str] = {}
        for line in lines:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=\s*[\"']([A-Z][A-Za-z0-9]+@v\d+)[\"']", line)
            if m:
                out[m.group(1)] = m.group(2)
        return out

    def _facts(self, module_file: str, body: str) -> tuple[set[str], set[str]]:
        consts = self._consts(module_file)
        schemas = set(SCHEMA_RE.findall(body)) | {consts[n] for n in re.findall(r"\b([A-Z_][A-Z0-9_]*)\b", body) if n in consts}
        return schemas, set(CLOCK_RE.findall(body))

    def _delegated(self, body: str) -> tuple[set[str], set[str], list[str]]:
        """One level: functions imported from scripts/lib inside the handler body."""
        schemas: set[str] = set()
        clocks: set[str] = set()
        refs: list[str] = []
        for m in re.finditer(r"from\s+(?:scripts\.)?lib\.([\w.]+)\s+import\s+(?:\(([\w,\s]+)\)|([\w, \t]+))", body):
            module_file = "lib/" + m.group(1).replace(".", "/") + ".py"
            lines, index = self._load(module_file)
            if not lines:
                continue
            names = (m.group(2) or m.group(3) or "").split(",")
            for name in [n.strip().split(" as ")[0].strip() for n in names if n.strip()]:
                node = index.get(name)
                if node is None or not re.search(rf"\b{re.escape(name)}\s*\(", body):
                    continue
                sub = "\n".join(lines[node.lineno - 1:node.end_lineno])
                # follow calls to same-module functions one more level (e.g. cached_x -> build_x)
                for callee in set(re.findall(r"\b([a-z_][\w]*)\s*\(", sub)) - {name}:
                    inner = index.get(callee)
                    if inner is not None:
                        sub += "\n" + "\n".join(lines[inner.lineno - 1:inner.end_lineno])
                sch, clk = self._facts(module_file, sub)
                schemas |= sch
                clocks |= clk
                refs.append(f"scripts/{module_file}:{node.lineno}")
        return schemas, clocks, refs

    def _load(self, module_file: str) -> tuple[list[str], dict[str, ast.AST]]:
        if module_file not in self._files:
            path = self.root / "scripts" / module_file
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                self._files[module_file] = (text.splitlines(), _function_index(path))
            else:
                self._files[module_file] = ([], {})
        return self._files[module_file]

    def describe(self, producer: Optional[str]) -> dict[str, Any]:
        if not producer or "::" not in producer:
            return {"resolved": False}
        module_file, func = producer.split("::", 1)
        lines, index = self._load(module_file)
        inline = re.match(r"handle\[inline:(\d+)\]$", func)
        if inline:
            start = int(inline.group(1)) - 1
            if start >= len(lines):
                return {"resolved": False, "file": f"scripts/{module_file}"}
            indent = len(lines[start]) - len(lines[start].lstrip())
            end = start + 1
            while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
                end += 1
            snippet = "\n".join(line[indent:] for line in lines[start:end])
            try:
                node = ast.parse(snippet + ("\n    pass" if snippet.rstrip().endswith(":") else "")).body[0]
                offset = start
            except SyntaxError:
                return {"resolved": False, "file": f"scripts/{module_file}", "line": start + 1}
            body = snippet
            line_no = start + 1
        else:
            node = index.get(func)
            if node is None:
                return {"resolved": False, "file": f"scripts/{module_file}"}
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            offset = 0
            line_no = node.lineno
        silent = []
        returns_error = False
        for sub in ast.walk(node):
            if isinstance(sub, ast.ExceptHandler) and len(sub.body) == 1 and isinstance(sub.body[0], ast.Pass):
                silent.append(sub.lineno + offset)
            if isinstance(sub, ast.ExceptHandler):
                for stmt in ast.walk(sub):
                    if isinstance(stmt, ast.Return):
                        returns_error = True
        if silent:
            error_behavior = "SILENT_EXCEPT_PASS"
        elif returns_error or re.search(r"[\"'](error|ok)[\"']\s*:\s*(False|[\"'])", body):
            error_behavior = "ERROR_ENVELOPE"
        else:
            error_behavior = "RAISES_TO_DISPATCH_500"
        schemas, clocks = self._facts(module_file, body)
        d_schemas, d_clocks, d_refs = self._delegated(body)
        return {
            "resolved": True,
            "file": f"scripts/{module_file}",
            "line": line_no,
            "clock_fields": sorted(clocks | d_clocks),
            "schemas": sorted(schemas) + sorted(d_schemas - schemas),
            "delegated_refs": d_refs,
            "silent_except_lines": silent,
            "error_behavior": error_behavior,
        }


def _template_match(template: str, route: str) -> bool:
    pattern = "^" + re.sub(r"\\\{[^}]*\\\}", r"[^/]+", re.escape(template)) + "$"
    candidate = route.replace("{param}", "X")
    return re.match(pattern, candidate) is not None


def match_route(route: str, backend: list[Route], method: str = "GET") -> tuple[Optional[Route], str]:
    want = "POST" if method == "POST" else "GET"
    backend = [r for r in backend if r.method in ("ANY", want)]
    exact = [r for r in backend if r.kind == "EXACT" and r.route == route]
    if exact:
        return exact[0], "EXACT"
    tmpl = [r for r in backend if r.kind == "TEMPLATE" and _template_match(r.route, route)]
    if tmpl:
        return tmpl[0], "TEMPLATE"
    if "{param}" in route:
        wild = re.compile("^" + re.escape(route).replace(re.escape("{param}"), "[^/]+") + "$")
        hits = [r for r in backend if r.kind == "EXACT" and wild.match(r.route)]
        if hits:
            return hits[0], "PARAM_WILDCARD"
    subs = sorted((r for r in backend if r.kind == "SUBPREFIX" and route.startswith(r.route)), key=lambda r: -len(r.route))
    if subs:
        return subs[0], "SUBPREFIX"
    prefixes = sorted((r for r in backend if r.kind == "PREFIX" and route.startswith(r.route)), key=lambda r: -len(r.route))
    for pref in prefixes:
        if pref.block_prefix:
            # Prefix block with a parsed sub-dispatch table: anything else hits its 404 branch.
            continue
        return pref, "PREFIX_UNVERIFIED"
    return None, "NO_HANDLER"


def _endpoint_row(f: "Fetch", handler: Optional[Route], how: str, desc: dict[str, Any]) -> dict[str, Any]:
    return {
        "route": f.route,
        "api_version": f.route.split("/")[2] if f.route.startswith("/api/") else None,
        "family": family_of(f.route),
        "consumer": f.surfaces,
        "consumer_ref": f"{f.file}:{f.line}",
        "call": f.callee,
        "method": f.method,
        "poll_ms": f.poll_ms,
        "result_used": f.used,
        "bound_names": list(f.bound_names),
        "producer": handler.producer if handler else None,
        "dispatch_ref": f"{handler.file}:{handler.line}" if handler else None,
        "match": how,
        "handler_ref": f"{desc['file']}:{desc['line']}" if desc.get("resolved") else None,
        "response_schema": (desc.get("schemas") or ["UNDECLARED_IN_HANDLER"])[0] if desc.get("resolved") else "HANDLER_UNRESOLVED",
        "response_schemas": desc.get("schemas", []),
        "clock_fields": desc.get("clock_fields", []),
        "source_clock": "source_as_of" if "source_as_of" in desc.get("clock_fields", []) else ("as_of" if "as_of" in desc.get("clock_fields", []) else "NOT_IN_HANDLER"),
        "composition_clock": "composition_as_of" if "composition_as_of" in desc.get("clock_fields", []) else ("generated_at" if "generated_at" in desc.get("clock_fields", []) else "NOT_IN_HANDLER"),
        "error_behavior": desc.get("error_behavior", "HANDLER_UNRESOLVED"),
        "evidence_class": "SOURCE_ONLY",
    }


# ── census ────────────────────────────────────────────────────────────────────
def build_census(root: Path | str | None = None) -> dict[str, Any]:
    root = Path(root) if root else ROOT
    fetches, constants, owners = scan_frontend(root)
    backend = scan_api_v2(root) + scan_agent_runtime(root)
    handlers = HandlerIndex(root)

    endpoints: list[dict[str, Any]] = []
    dead_calls: list[dict[str, Any]] = []
    unused: list[dict[str, Any]] = []
    for f in fetches:
        handler, how = match_route(f.route, backend, f.method)
        desc = handlers.describe(handler.producer if handler else None)
        row = _endpoint_row(f, handler, how, desc)
        endpoints.append(row)
        if how == "NO_HANDLER":
            dead_calls.append({"route": f.route, "consumer_ref": row["consumer_ref"], "call": f.callee, "family": row["family"]})
        if f.used is False:
            unused.append({"route": f.route, "consumer_ref": row["consumer_ref"], "bound_names": f.bound_names, "call": f.callee})

    for c in constants:
        handler, how = match_route(c["route"], backend)
        if how == "NO_HANDLER" and c["referenced"]:
            dead_calls.append({"route": c["route"], "consumer_ref": f"{c['file']}:{c['line']}", "call": f"const {c['name']}", "family": family_of(c["route"])})
        if c["referenced"]:
            desc = handlers.describe(handler.producer if handler else None)
            endpoints.append(_endpoint_row(
                Fetch(route=c["route"], raw=c["route"], file=c["file"], line=c["line"], callee=f"const {c['name']}",
                      surfaces=c["surfaces"], used=None),
                handler, how, desc,
            ))

    consumed_routes = {e["route"] for e in endpoints} | {c["route"] for c in constants if c["referenced"]}
    # Whole-app consumer text (not only the five surfaces) so a route used elsewhere is not "unconsumed".
    app_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (root / SRC).rglob("*") if p.suffix in (".ts", ".tsx") and not p.name.endswith((".test.ts", ".test.tsx")))
    app_routes = {normalize_route(raw) for _, raw in iter_route_literals(app_text)}

    wild_app = [re.compile("^" + re.escape(a).replace(re.escape("{param}"), "[^/]+") + "$") for a in app_routes if "{param}" in a]

    def consumed_anywhere(r: Route) -> bool:
        if r.kind == "EXACT":
            return r.route in app_routes or any(w.match(r.route) for w in wild_app)
        if r.kind == "TEMPLATE":
            return any(_template_match(r.route, a) for a in app_routes)
        return any(a.startswith(r.route) for a in app_routes)

    # Alias spellings dispatched by one branch (p in ("a", "b")) count as one route.
    alias_groups: dict[tuple[str, int], list[Route]] = {}
    for r in backend:
        alias_groups.setdefault((r.file, r.line), []).append(r)

    unconsumed: list[dict[str, Any]] = []
    seen_unconsumed: set[str] = set()
    for r in backend:
        fam = family_of(r.route)
        if not fam or r.kind == "PREFIX" or r.method == "POST":
            continue
        if r.route in seen_unconsumed:
            continue
        group = [g for g in alias_groups.get((r.file, r.line), [r]) if g.kind != "PREFIX"]
        if any(consumed_anywhere(g) for g in group):
            continue
        if not consumed_anywhere(r):
            seen_unconsumed.update(g.route for g in group)
            r = Route(r.route, r.kind, r.file, r.line, r.producer, r.method, r.block_prefix)
            if len(group) > 1:
                r.route = r.route  # canonical = first spelling

            unconsumed.append({"route": r.route, "aliases": sorted(g.route for g in group if g.route != r.route),
                               "family": fam, "kind": r.kind, "producer": r.producer,
                               "dispatch_ref": f"{r.file}:{r.line}", "scope": "NO_COMMAND_CENTER_V3_CONSUMER"})

    # Duplicate endpoint families: one producer behind several consumed routes; one route fetched from several files.
    by_producer: dict[str, set[str]] = {}
    for e in endpoints:
        if e["producer"] and e["match"] in ("EXACT", "TEMPLATE"):
            by_producer.setdefault(e["producer"], set()).add(e["route"])
    duplicate_families = {p: sorted(rs) for p, rs in by_producer.items() if len(rs) > 1}
    by_route: dict[str, set[str]] = {}
    for e in endpoints:
        by_route.setdefault(e["route"], set()).add(e["consumer_ref"].split(":")[0])
    duplicate_route_consumers = {r: sorted(fs) for r, fs in by_route.items() if len(fs) > 1}

    mixing: dict[str, dict[str, list[str]]] = {}
    for fam in FAMILIES:
        versions: dict[str, set[str]] = {}
        for e in endpoints:
            if e["family"] == fam:
                versions.setdefault(e["api_version"], set()).add(e["route"])
        if len(versions) > 1:
            mixing[fam] = {v: sorted(rs) for v, rs in sorted(versions.items())}
    same_resource = sorted({
        rest for rest in {e["route"].split("/", 3)[3] for e in endpoints if e["route"].count("/") >= 3}
        if f"/api/v2/{rest}" in consumed_routes and f"/api/v3/{rest}" in consumed_routes
    })

    polling = sorted(({"route": e["route"], "consumer_ref": e["consumer_ref"], "poll_ms": e["poll_ms"]} for e in endpoints if e["poll_ms"]),
                     key=lambda r: (r["poll_ms"], r["route"]))
    silent: dict[str, dict[str, Any]] = {}
    for e in endpoints:
        if e["error_behavior"] == "SILENT_EXCEPT_PASS" and e["handler_ref"]:
            silent.setdefault(e["handler_ref"], {"handler_ref": e["handler_ref"], "producer": e["producer"], "routes": set()})["routes"].add(e["route"])
    silent_rows = [{**v, "routes": sorted(v["routes"])} for v in silent.values()]

    family_endpoints = [e for e in endpoints if e["family"]]
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "scope": list(SURFACES),
        "families": {k: list(v) for k, v in FAMILIES.items()},
        "serving_sha": _serving_sha(root),
        "method": "static source parse: TS import closure from routed pages + api_v2 dispatch/ROUTES + agent-runtime READ_ROUTES; handler bodies via ast",
        "consumer_files_scanned": len(owners),
        "backend_routes_parsed": len(backend),
        "endpoints": endpoints,
        "endpoint_count": len(endpoints),
        "family_endpoint_count": len(family_endpoints),
        "distinct_routes": len({e["route"] for e in endpoints}),
        "route_constants": constants,
        "backend_routes": [
            {"route": r.route, "kind": r.kind, "method": r.method, "producer": r.producer,
             "dispatch_ref": f"{r.file}:{r.line}", "family": family_of(r.route)}
            for r in backend if family_of(r.route)
        ],
        "unused_fetches": unused,
        "dead_calls": dead_calls,
        "dead_endpoints": dead_calls,  # back-compat alias: client calls with no backend handler
        "unconsumed_routes": unconsumed,
        "duplicate_endpoint_families": duplicate_families,
        "duplicate_route_consumers": duplicate_route_consumers,
        "v2_v3_mixing": mixing,
        "v2_v3_same_resource": same_resource,
        "v2_v3_accidental_mixing": same_resource,
        "polling_intervals": polling,
        "silent_exception_paths": silent_rows,
        "counts": {
            "endpoints": len(endpoints),
            "family_endpoints": len(family_endpoints),
            "unused_fetches": len(unused),
            "dead_calls": len(dead_calls),
            "unconsumed_routes": len(unconsumed),
            "duplicate_endpoint_families": len(duplicate_families),
            "duplicate_route_consumers": len(duplicate_route_consumers),
            "v2_v3_mixing_families": len(mixing),
            "polling_endpoints": len(polling),
            "silent_exception_handlers": len(silent_rows),
            "handlers_unresolved": sum(1 for e in endpoints if e["error_behavior"] == "HANDLER_UNRESOLVED"),
            "prefix_unverified": sum(1 for e in endpoints if e["match"] == "PREFIX_UNVERIFIED"),
        },
        "unverified_findings": [
            "Static parse only: runtime response shape, clocks and serving release need an API capture against the exact release.",
            "Clock/schema/error fields are read from the producer function body only (one level); delegated helpers are not followed.",
            "unconsumed_routes means no Command Center v3 consumer; Telegram, v2 dashboard or scripts may still call them.",
            "result_used=null means the fetch result is chained/returned and usage is not statically decidable.",
        ],
        "machine_claims": {
            "source_complete": bool(endpoints),
            "runtime_complete": False,
            "dead_calls_proven": True,
            "dead_calls_scope": "no matching dispatch branch in api_v2.handle / agent-runtime READ_ROUTES",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit only machine-readable JSON")
    parser.add_argument("--summary", action="store_true", help="emit only counts and findings (no endpoint rows)")
    args = parser.parse_args()
    report = build_census()
    if args.summary:
        slim = {k: v for k, v in report.items() if k not in ("endpoints", "route_constants", "backend_routes")}
        print(json.dumps(slim, indent=2, sort_keys=True, default=list))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, default=list))
    if not args.json:
        for key, value in report["counts"].items():
            print(f"API_CENSUS_{key.upper()}={value}")
        print("API_CENSUS_RUNTIME_VERIFIED=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
