#!/usr/bin/env python3
"""Static env-allowlist enforce readiness for every n8n run-allowlist lane (N8nEnvEnforceReadiness@v1).

Third-party audit 2026-10-15 ("report-mode caller authentication and environment filtering do not establish
confinement"): the executor runs under global ``TRADEAI_EXECUTOR_ENV_ALLOWLIST=enforce``, but a lane pinned
``env_allowlist_mode: "report"`` still receives the full pre-P7 environment. This tool measures, for every lane in
``config/n8n_run_allowlist.json``, what the lane's code would read that its declared ``env_names`` do not cover —
i.e. what would break or silently change under enforce — and which lanes could flip now.

Method (static, read-only, no import of lane code, no env values ever read):

* closure = the lane's ``*.py`` command tokens + every repo module they import, lazily or not (absolute imports
  resolved against the repo root, ``scripts/`` and ``scripts/lib/``; relative imports against the importing file).
  Repo scripts named by a ``"scripts/<x>.py"`` string literal are counted as ``spawn_refs`` but not descended into
  (most are data references, not spawns; a real spawn inherits the same enforced env and is re-checked when that
  script is itself a lane);
* reads = literal ``os.getenv`` / ``os.environ.get`` / ``os.environ[...]`` / ``env.get`` names (constants resolved
  within the module); ``required`` when read by subscript with no default, else ``defaulted``;
* dynamic = a read whose name is not a literal (cannot be inventoried statically);
* unbounded loader = ``load_dotenv``, ``os.environ.update`` or a non-literal ``os.environ.setdefault`` without a
  module ``_ENV_KEYS`` literal set (a whole-file copy that enforce cannot bound);
* checkout env file = a module that names a checkout ``.env`` path itself (a key-level fallback read from disk,
  e.g. ``DB_PASSWORD`` when the env lacks it). Not blocking — a whole-file copy from it is caught as an unbounded
  loader (including ``os.environ[<non-literal>] = ...``) — but a RESIDUAL: the lane runs as the same uid and reads
  the secret from disk whatever the allowlist says. ``narrowed`` when the module has a literal ``_ENV_KEYS`` set.
  ``lib/env_bootstrap.load_env`` is NOT counted: under enforce the executor sets ``TRADEAI_ENV_BOUND_NAMES`` and
  that loader copies only the lane's ``env_names`` (bound mode, 2026-10-11).

Verdict per lane: ``READY_NOW`` (nothing missing, nothing dynamic, no unbounded loader, no direct env file),
otherwise ``BLOCKED`` with the reasons. ``READY_NOW`` is necessary, not sufficient: a flip also needs the lane's
closure test (tests/test_n8n_executor_env_allowlist_20261009.py) and one enforced shadow run (§23.24 cutover).

Usage:
    python3 scripts/report_n8n_env_enforce_readiness.py --json OUT.json --markdown OUT.md [--diff OUT.diff]
Writes only the files named. Exit 0 always on a completed measurement (this is a report, not a gate).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "N8nEnvEnforceReadiness@v1"
ALLOWLIST_REL = Path("config") / "n8n_run_allowlist.json"
SAFE_FLOCK_NAMES = frozenset({"PROJECT_ROOT", "SAFE_FLOCK_LOG_DIR"})
#: Loaders bounded by the executor under enforce (TRADEAI_ENV_BOUND_NAMES): their internals are not env reads of
#: the lane, so the scan does not descend into them.
BOUNDED_LOADER_MODULES = frozenset({"env_bootstrap.py"})
SCRIPT_LITERAL_RE = re.compile(r"(?:^|/)(scripts/[A-Za-z0-9_/]+\.py)$")
ENV_FILE_LITERAL_RE = re.compile(r"(^|/)\.env(\.[A-Za-z0-9_.-]+)?$")
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
GET_FUNCS = frozenset({"os.getenv", "os.environ.get", "env.get", "environ.get", "getenv"})
SUBSCRIPT_BASES = frozenset({"os.environ", "environ"})


def _executor_base_names(root: Path) -> frozenset[str]:
    """CHILD_ENV_BASE_NAMES read from the executor source by AST (no import of the executor)."""
    tree = ast.parse((root / "scripts" / "n8n_run_executor.py").read_text(encoding="utf-8"))
    consts: dict[str, str] = {}
    base: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node.value.value
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        if isinstance(target, ast.Name) and target.id == "CHILD_ENV_BASE_NAMES":
            value = node.value
            if isinstance(value, ast.Call) and value.args:
                value = value.args[0]
            for elt in getattr(value, "elts", []):
                if isinstance(elt, ast.Constant):
                    base.add(elt.value)
                elif isinstance(elt, ast.Name) and elt.id in consts:
                    base.add(consts[elt.id])
    if not base:
        raise RuntimeError("CHILD_ENV_BASE_NAMES not found in scripts/n8n_run_executor.py")
    return frozenset(base)


@dataclass
class ModuleScan:
    path: Path
    required: set[str] = field(default_factory=set)
    defaulted: set[str] = field(default_factory=set)
    dynamic: list[int] = field(default_factory=list)
    unbounded_loaders: list[int] = field(default_factory=list)
    direct_env_file: list[int] = field(default_factory=list)
    narrowed_env_file: list[int] = field(default_factory=list)
    imports: set[Path] = field(default_factory=set)
    spawned: set[Path] = field(default_factory=set)
    parse_error: str | None = None


def _module_env_keys(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ENV_KEYS" for t in node.targets):
            val = node.value
            if isinstance(val, ast.Call) and val.args:
                val = val.args[0]
            if isinstance(val, (ast.Set, ast.Tuple, ast.List)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in val.elts
            ):
                return {e.value for e in val.elts}
    return set()


def _resolve_module(root: Path, here: Path, module: str, level: int) -> Path | None:
    if not module:
        return None
    rel = Path(*module.split("."))
    bases = (
        [here.parent.joinpath(*([".."] * (level - 1)))] if level else [root, root / "scripts", root / "scripts" / "lib"]
    )
    for base in bases:
        for cand in (base / rel.with_suffix(".py"), base / rel / "__init__.py"):
            if cand.is_file():
                try:
                    resolved = cand.resolve()
                    resolved.relative_to(root.resolve())
                except ValueError:
                    continue
                return resolved
    return None


def scan_module(path: Path, root: Path) -> ModuleScan:
    out = ModuleScan(path=path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        out.parse_error = type(exc).__name__
        return out
    consts = {
        t.id: n.value.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    env_keys = _module_env_keys(tree)

    def literal(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = ast.unparse(node.func)
            short = func.split(".")[-1]
            if short == "load_dotenv" or func == "os.environ.update":
                out.unbounded_loaders.append(node.lineno)
                continue
            if func == "os.environ.setdefault":
                name = literal(node.args[0]) if node.args else None
                if name is None:
                    if env_keys:
                        out.defaulted |= env_keys
                    else:
                        out.unbounded_loaders.append(node.lineno)
                continue
            if func in GET_FUNCS:
                name = literal(node.args[0]) if node.args else None
                if name is None:
                    out.dynamic.append(node.lineno)
                elif ENV_NAME_RE.fullmatch(name):
                    out.defaulted.add(name)
                continue
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            if ast.unparse(node.value) in SUBSCRIPT_BASES and literal(node.slice) is None:
                out.unbounded_loaders.append(node.lineno)  # os.environ[k] = v over a file: a whole-file copy
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            if ast.unparse(node.value) in SUBSCRIPT_BASES:
                name = literal(node.slice)
                if name is None:
                    out.dynamic.append(node.lineno)
                elif ENV_NAME_RE.fullmatch(name):
                    out.required.add(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                hit = _resolve_module(root, path, alias.name, 0)
                if hit:
                    out.imports.add(hit)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            candidates = [mod, *(f"{mod}.{a.name}" if mod else a.name for a in node.names)]
            for cand in candidates:
                hit = _resolve_module(root, path, cand, node.level)
                if hit:
                    out.imports.add(hit)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = SCRIPT_LITERAL_RE.search(node.value)
            if m and (root / m.group(1)).is_file():
                out.spawned.add((root / m.group(1)).resolve())
            if ENV_FILE_LITERAL_RE.search(node.value):
                (out.narrowed_env_file if env_keys else out.direct_env_file).append(node.lineno)
                if env_keys:
                    out.defaulted |= env_keys
    out.defaulted -= out.required
    out.imports.discard(path)
    return out


class Analyzer:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root.resolve()
        self._cache: dict[Path, ModuleScan] = {}

    def scan(self, path: Path) -> ModuleScan:
        path = path.resolve()
        if path not in self._cache:
            self._cache[path] = scan_module(path, self.root)
        return self._cache[path]

    def closure(self, entry_points: Iterable[Path]) -> list[ModuleScan]:
        seen: dict[Path, ModuleScan] = {}
        stack = [p.resolve() for p in entry_points]
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            if p.name in BOUNDED_LOADER_MODULES:
                seen[p] = ModuleScan(path=p)  # bounded under enforce; do not descend
                continue
            scan = self.scan(p)
            seen[p] = scan
            stack.extend(scan.imports)
        return [seen[k] for k in sorted(seen)]

    def lane_scripts(self, command: list[str]) -> list[Path]:
        out = []
        for tok in command:
            rel = tok.removeprefix("$CODE_ROOT/")
            if rel.endswith(".py") and rel.startswith("scripts/") and ".." not in Path(rel).parts:
                p = self.root / rel
                if p.is_file():
                    out.append(p)
        return out


def inline_env_names(command: list[str]) -> set[str]:
    """Names set by a leading ``env NAME=value`` in the argv (the child sees them whatever the allowlist)."""
    out: set[str] = set()
    if command and command[0] == "env":
        for tok in command[1:]:
            name, sep, _ = tok.partition("=")
            if not sep or not ENV_NAME_RE.fullmatch(name):
                break
            out.add(name)
    return out


def assess_lane(entry: Mapping[str, Any], analyzer: Analyzer, base: frozenset[str]) -> dict[str, Any]:
    command = list(entry.get("command") or [])
    scripts = analyzer.lane_scripts(command)
    mods = analyzer.closure(scripts)
    required: set[str] = set()
    defaulted: set[str] = set()
    dynamic: list[str] = []
    loaders: list[str] = []
    env_files: list[str] = []
    narrowed: list[str] = []
    spawn_refs: set[str] = set()
    parse_errors: list[str] = []
    root = analyzer.root

    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    for m in mods:
        required |= m.required
        defaulted |= m.defaulted
        dynamic += [f"{rel(m.path)}:{n}" for n in sorted(set(m.dynamic))]
        loaders += [f"{rel(m.path)}:{n}" for n in sorted(set(m.unbounded_loaders))]
        env_files += [f"{rel(m.path)}:{n}" for n in sorted(set(m.direct_env_file))]
        narrowed += [f"{rel(m.path)}:{n}" for n in sorted(set(m.narrowed_env_file))]
        spawn_refs |= {rel(p) for p in m.spawned}
        if m.parse_error:
            parse_errors.append(f"{rel(m.path)}:{m.parse_error}")
    defaulted -= required
    if entry.get("lock_kind", "safe_flock") == "safe_flock":
        required |= SAFE_FLOCK_NAMES
    declared = set(entry.get("env_names") or [])
    provided = set(base) | declared | inline_env_names(command)
    missing_required = sorted(required - provided)
    missing_defaulted = sorted(defaulted - provided)
    reasons = []
    if not isinstance(entry.get("env_names"), list):
        reasons.append("env_names_missing")
    if missing_required:
        reasons.append("missing_required_names")
    if missing_defaulted:
        reasons.append("missing_defaulted_names")
    if dynamic:
        reasons.append("dynamic_env_reads")
    if loaders:
        reasons.append("unbounded_env_loader")
    if parse_errors:
        reasons.append("unparsed_module")
    if command and not scripts and command[0] not in {"bash", "sh"}:
        reasons.append("no_python_entrypoint_resolved")
    mode = entry.get("env_allowlist_mode", "enforce")
    return {
        "lane_id": entry.get("lane_id"),
        "current_mode": mode,
        "verdict": "BLOCKED" if reasons else ("READY_WITH_RESIDUAL" if env_files or narrowed else "READY_NOW"),
        "residuals": (["checkout_env_file_fallback"] if env_files else [])
        + (["narrowed_checkout_env_loader"] if narrowed else []),
        "reasons": reasons,
        "closure_modules": len(mods),
        "declared_env_names": len(declared),
        "missing_required": missing_required,
        "missing_defaulted": missing_defaulted,
        "dynamic_reads": len(dynamic),
        "dynamic_read_sites": dynamic[:10],
        "unbounded_loader_sites": loaders[:10],
        "direct_env_file_sites": env_files[:10],
        "narrowed_env_file_sites": narrowed[:10],
        "spawn_refs": len(spawn_refs),
        "unparsed_modules": parse_errors[:10],
        "flip_candidate": mode == "report" and not reasons and not env_files and not narrowed,
        "flip_candidate_with_residual": mode == "report" and not reasons and bool(env_files or narrowed),
        "enforced_but_blocked": mode == "enforce" and bool(reasons),
    }


def build_report(root: Path = ROOT, allowlist: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = root.resolve()
    doc = allowlist if allowlist is not None else json.loads((root / ALLOWLIST_REL).read_text(encoding="utf-8"))
    base = _executor_base_names(root)
    analyzer = Analyzer(root)
    lanes = [assess_lane(e, analyzer, base) for e in doc.get("lanes") or [] if isinstance(e, Mapping)]
    lanes.sort(key=lambda r: str(r["lane_id"]))
    reason_counts: dict[str, int] = {}
    for r in lanes:
        for reason in r["reasons"]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "schema": SCHEMA,
        "allowlist_as_of": doc.get("as_of"),
        "method": "static AST closure; names only, never values; READY_NOW is necessary, not sufficient",
        "base_names": sorted(base),
        "summary": {
            "lanes": len(lanes),
            "enforce": sum(r["current_mode"] == "enforce" for r in lanes),
            "report": sum(r["current_mode"] == "report" for r in lanes),
            "ready_now": sum(r["verdict"] == "READY_NOW" for r in lanes),
            "ready_with_residual": sum(r["verdict"] == "READY_WITH_RESIDUAL" for r in lanes),
            "flip_candidates_with_residual": sorted(r["lane_id"] for r in lanes if r["flip_candidate_with_residual"]),
            "enforced_with_residual": sorted(
                r["lane_id"] for r in lanes if r["current_mode"] == "enforce" and r["residuals"]
            ),
            "flip_candidates": sorted(r["lane_id"] for r in lanes if r["flip_candidate"]),
            "enforced_but_blocked": sorted(r["lane_id"] for r in lanes if r["enforced_but_blocked"]),
            "blocked_by_reason": dict(sorted(reason_counts.items())),
        },
        "lanes": lanes,
    }


def proposed_diff(report: Mapping[str, Any]) -> str:
    """A reviewable, NOT applied, config diff: env_allowlist_mode report -> enforce for each flip candidate."""
    lines = [
        "# PROPOSED — not applied. config/n8n_run_allowlist.json env_allowlist_mode flips for READY_NOW lanes.",
        "# Each flip also needs: the lane added to the enforced closure test, one enforced dry_run shadow receipt",
        "# with env_allowlist.effective_mode=enforce and a non-empty output, then the §23.24 cutover standard.",
    ]
    for lane in report["summary"]["flip_candidates"]:
        lines += [
            f'@@ lane_id "{lane}" @@',
            '-  "env_allowlist_mode": "report",',
            '+  "env_allowlist_mode": "enforce",',
            '-  "env_report_reason": "...",',
        ]
    if not report["summary"]["flip_candidates"]:
        lines.append("# (no lane is READY_NOW in report mode: no flip is proposed)")
    return "\n".join(lines) + "\n"


def render_markdown(report: Mapping[str, Any]) -> str:
    s = report["summary"]
    out = [
        "# n8n executor env-allowlist enforce readiness (generated)",
        "",
        "```",
        f"Schema:   {report['schema']}",
        f"Source:   scripts/report_n8n_env_enforce_readiness.py over config/n8n_run_allowlist.json "
        f"(as_of {report['allowlist_as_of']})",
        f"Method:   {report['method']}",
        "```",
        "",
        f"**{s['lanes']} lanes**: {s['enforce']} enforce, {s['report']} report-pinned. "
        f"**{s['ready_now']} READY_NOW** by static analysis; flip candidates (report + READY_NOW): "
        f"{len(s['flip_candidates'])}; enforced lanes the analysis would block: {len(s['enforced_but_blocked'])}.",
        "",
        "| Blocking reason | Lanes |",
        "|---|---|",
        *[f"| `{k}` | {v} |" for k, v in s["blocked_by_reason"].items()],
        "",
        "| Lane | Mode | Verdict | Closure | Missing required | Missing defaulted | Dynamic | Loaders | .env | Reasons |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["lanes"]:
        out.append(
            f"| `{r['lane_id']}` | {r['current_mode']} | {r['verdict']} | {r['closure_modules']} | "
            f"{len(r['missing_required'])} | {len(r['missing_defaulted'])} | {r['dynamic_reads']} | "
            f"{len(r['unbounded_loader_sites'])} | {len(r['direct_env_file_sites'])} | {', '.join(r['reasons']) or '—'} |"
        )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--markdown")
    ap.add_argument("--diff")
    args = ap.parse_args(argv)
    report = build_report(Path(args.root))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(report), encoding="utf-8")
    if args.diff:
        Path(args.diff).write_text(proposed_diff(report), encoding="utf-8")
    if not (args.json_out or args.markdown or args.diff):
        sys.stdout.write(json.dumps(report["summary"], indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
