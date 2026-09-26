"""Test-impact selection: which registered tests can a change affect?

2026-09-25 (operator: "faster feedback with appropriate governance"). The full
hardening suite is ~1,050 CPU-seconds of CPU-bound tests (measured: wall ~= user
+ sys for every slow file), so no amount of parallelism fits it in a 5-minute
check on a 4-vCPU runner. PRs therefore run the tests a change can reach, plus an
always-run smoke set; the full suite runs after merge (push to main), nightly and
on demand, and a failure there opens an issue.

How "can reach" is computed -- static, conservative, no execution:

* Every Python file under ``scripts/`` and ``tests/`` is parsed (``ast``) for
  imports, and every file (any type) is scanned for string references to repo
  paths (``scripts/foo.py``, ``config/lane_registry.json``, ``"foo.py"`` when
  ``scripts/foo.py`` exists). Tests here load scripts all three ways: ``import``,
  ``importlib`` on a path string, and ``subprocess`` on a path string.
* Import names resolve the way the repo's tests resolve them: ``scripts.lib.x``,
  ``lib.x`` (tests put ``scripts/`` on ``sys.path``), bare ``x`` for
  ``scripts/x.py`` and sub-packages (``brokers.x``).
* The selection is the REVERSE TRANSITIVE closure: a change to ``scripts/lib/b.py``
  selects every test that imports ``b`` directly, or imports ``a`` which imports
  ``b``, and so on.
* A changed test file selects itself. A changed path nothing references and that
  the risk tiers do not classify selects nothing beyond the smoke set -- which is
  the honest answer, and the post-merge full run still covers it.

The map is cached under the worktree's git dir (``git rev-parse --git-path``); the cache key is a hash over every scanned file's
path + size + mtime, so a stale map is detected and rebuilt (~seconds).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _default_cache_path(root: Path = ROOT) -> Path:
    """Inside the per-worktree git dir: never tracked, never rsynced into a release."""
    r = subprocess.run(
        ["git", "rev-parse", "--git-path", "tradeai/test_impact_map.json"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if r.returncode == 0 and r.stdout.strip():
        p = Path(r.stdout.strip())
        return p if p.is_absolute() else root / p
    return root / ".git" / "tradeai-test_impact_map.json"


SCHEMA = "TestImpactMap@v1"
TIERS_PATH = ROOT / "config" / "ci_risk_tiers.json"

_PATH_REF_RE = re.compile(r"""["'/]((?:scripts|config|sql|tests)/[A-Za-z0-9_./-]+\.(?:py|json|yaml|yml|sql|sh))""")
_BARE_PY_RE = re.compile(r"""["']([A-Za-z0-9_]+\.py)["']""")


def _iter_files(root: Path):
    for top in ("scripts", "tests"):
        base = root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules", ".venv")]
            for fn in filenames:
                if fn.endswith((".py", ".sh")):
                    yield Path(dirpath) / fn


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _module_names(rel: str) -> list[str]:
    """Import names under which the repo's code/tests can reach ``rel``."""
    if not rel.endswith(".py") or not rel.startswith("scripts/"):
        return []
    parts = rel[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    dotted = ".".join(parts)  # scripts.lib.x
    names = {dotted, ".".join(parts[1:])}  # lib.x / x / brokers.x
    return sorted(n for n in names if n)


def _cache_key(root: Path, files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(files):
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{_rel(root, p)}\t{st.st_size}\t{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def _imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            for a in node.names:
                out.add(f"{node.module}.{a.name}")
    return out


def build_map(root: Path = ROOT) -> dict:
    files = list(_iter_files(root))
    name_to_file: dict[str, str] = {}
    by_basename: dict[str, str] = {}
    for p in files:
        rel = _rel(root, p)
        for n in _module_names(rel):
            name_to_file.setdefault(n, rel)
        if rel.startswith("scripts/") and rel.count("/") == 1:
            by_basename.setdefault(p.name, rel)

    deps: dict[str, set[str]] = {}
    for p in files:
        rel = _rel(root, p)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        d: set[str] = set()
        if rel.endswith(".py"):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    tree = ast.parse(text)
                for imp in _imports(tree):
                    target = name_to_file.get(imp)
                    if target and target != rel:
                        d.add(target)
            except SyntaxError:
                pass
        for m in _PATH_REF_RE.finditer(text):
            ref = m.group(1)
            if ref != rel and (root / ref).exists():
                d.add(ref)
        for m in _BARE_PY_RE.finditer(text):
            target = by_basename.get(m.group(1))
            if target and target != rel:
                d.add(target)
        deps[rel] = d

    # reverse graph: file -> files that depend on it
    rdeps: dict[str, list[str]] = {}
    for src, ds in deps.items():
        for t in ds:
            rdeps.setdefault(t, []).append(src)
    return {
        "schema": SCHEMA,
        "key": _cache_key(root, files),
        "rdeps": {k: sorted(v) for k, v in sorted(rdeps.items())},
    }


def load_map(root: Path = ROOT, cache: Path | None = None, *, use_cache: bool = True) -> tuple[dict, str]:
    """Return (map, status) where status is 'cache' or 'rebuilt'."""
    cache = cache or _default_cache_path(root)
    key = _cache_key(root, list(_iter_files(root)))
    if use_cache and cache.is_file():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("schema") == SCHEMA and data.get("key") == key:
                return data, "cache"
        except (OSError, ValueError):
            pass
    data = build_map(root)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data, "rebuilt"


def impacted_tests(changed: list[str], impact_map: dict) -> dict[str, int]:
    """Return {test_file: distance} for tests reachable from ``changed``.

    distance 0 = the changed file is itself a test; 1 = imports/references a
    changed file directly; n = through n-1 intermediate modules.
    """
    rdeps = impact_map.get("rdeps") or {}
    out: dict[str, int] = {}
    frontier = [(c, 0) for c in changed]
    seen: dict[str, int] = {}
    while frontier:
        path, dist = frontier.pop()
        if path in seen and seen[path] <= dist:
            continue
        seen[path] = dist
        if path.startswith("tests/") and path.endswith(".py"):
            if path not in out or out[path] > dist:
                out[path] = dist
        for dep in rdeps.get(path, ()):
            frontier.append((dep, dist + 1))
    return out


# ---------------------------------------------------------------------------
# Risk tiers (config/ci_risk_tiers.json)
# ---------------------------------------------------------------------------


def glob_to_re(glob: str) -> re.Pattern:
    """``**`` spans directories, ``*`` and ``?`` do not (gitignore-like)."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def load_tiers(path: Path = TIERS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def classify(path: str, tiers: dict) -> tuple[str, str | None]:
    """Return ("high", category) | ("low", None) | ("medium", None). HIGH wins."""
    for category, spec in (tiers.get("high") or {}).items():
        if any(glob_to_re(g).match(path) for g in spec.get("globs") or ()):
            return "high", category
    if any(glob_to_re(g).match(path) for g in (tiers.get("low") or {}).get("globs") or ()):
        return "low", None
    return "medium", None


def changed_paths(base: str, *, root: Path = ROOT, include_worktree: bool = False) -> list[str] | None:
    """Paths changed on HEAD relative to merge-base(base, HEAD); None if ``base`` is unusable.

    ``include_worktree`` adds staged, unstaged and untracked paths (local use).
    """
    r = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=str(root), capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = set(r.stdout.split())
    if include_worktree:
        for cmd in (
            ["git", "diff", "--name-only", "HEAD"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            rr = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
            if rr.returncode == 0:
                out.update(rr.stdout.split())
    return sorted(out)


def select(
    changed: list[str],
    gates: list[tuple[str, list[str]]],
    *,
    impact_map: dict,
    tiers: dict,
    hints: dict[str, float],
    default_seconds: float = 1.0,
    budget_seconds: float | None = None,
) -> dict:
    """Choose the PR fast-core tests for ``changed``.

    Returns {"gates": [(name, files)] in declared order, "deferred": [files],
    "tier": str, "high": {category: [paths]}, "estimate_seconds": float, ...}.

    Mandatory (never deferred): the smoke gates; for each HIGH category touched,
    its named gates in full; registered test files that changed; and for HIGH
    paths, every gate (up to ``expand_gate_max_seconds``) that holds such a direct
    test. Everything else the change can reach is added nearest-first (direct
    importers first) while the estimate fits the budget;
    the rest is DEFERRED to the post-merge full run and listed.
    """
    budget = float(tiers.get("budget_seconds", 540) if budget_seconds is None else budget_seconds)
    registered: dict[str, list[str]] = {}
    for name, paths in gates:
        for p in paths:
            registered.setdefault(p, []).append(name)
    gate_files = {name: list(paths) for name, paths in gates}

    high: dict[str, list[str]] = {}
    tier_of: dict[str, str] = {}
    for p in changed:
        t, cat = classify(p, tiers)
        tier_of[p] = t
        if t == "high":
            high.setdefault(cat, []).append(p)
    if high:
        tier = "high"
    elif changed and all(t == "low" for t in tier_of.values()):
        tier = "low"
    else:
        tier = "medium"

    mandatory_gates: list[str] = list(tiers.get("smoke_gates") or [])
    for cat in high:
        mandatory_gates += list((tiers["high"][cat].get("gates") or []))
    if any(t == "low" for t in tier_of.values()):
        mandatory_gates += list((tiers.get("low") or {}).get("gates") or [])
    unknown_gates = sorted({g for g in mandatory_gates if g not in gate_files})

    chosen: set[str] = set()
    for g in mandatory_gates:
        chosen.update(gate_files.get(g, ()))

    impacted: dict[str, int] = {}
    if tier != "low":
        non_low = [p for p in changed if tier_of[p] != "low"]
        impacted = {f: d for f, d in impacted_tests(non_low, impact_map).items() if f in registered}
    high_paths = {p for ps in high.values() for p in ps}
    for f, d in impacted.items():
        if d == 0:
            chosen.add(f)

    def w(p: str) -> float:
        return hints.get(p, default_seconds)

    expand_max = float(tiers.get("expand_gate_max_seconds", 60))
    if high_paths:
        direct_from_high = impacted_tests(sorted(high_paths), impact_map)
        for f, d in direct_from_high.items():
            if d <= 1 and f in registered:
                for g in registered[f]:
                    # a grab-bag gate (maturity_overnight_20260912: 130 files, ~460 s)
                    # is not "the relevant suite"; its direct files are already in
                    if sum(w(p) for p in gate_files[g]) <= expand_max:
                        chosen.update(gate_files[g])

    est = sum(w(p) for p in chosen)
    mandatory_estimate = est
    optional = sorted((f for f in impacted if f not in chosen), key=lambda f: (impacted[f], w(f), f))
    deferred: list[str] = []
    for f in optional:
        if est + w(f) <= budget:
            chosen.add(f)
            est += w(f)
        else:
            deferred.append(f)

    selected = []
    for name, paths in gates:
        keep = [p for p in paths if p in chosen]
        if keep:
            selected.append((name, keep))
            chosen.difference_update(keep)  # a file registered twice runs once
    return {
        "gates": selected,
        "deferred": deferred,
        "tier": tier,
        "high": high,
        "changed": list(changed),
        "impacted": len(impacted),
        "estimate_seconds": round(est, 1),
        "mandatory_estimate_seconds": round(mandatory_estimate, 1),
        "budget_seconds": budget,
        "unknown_gates": unknown_gates,
    }
