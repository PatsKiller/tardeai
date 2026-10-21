"""Release Train v2 risk classifier: may this change ride a train? (Phase 1, 2026-10-21)

    python3 scripts/lib/release_train_classify.py --base origin/main --head HEAD    # classify a local diff, print
    python3 scripts/lib/release_train_classify.py --paths a.py docs/x.md --json     # classify explicit paths

Deterministic and read-only: it reads git (diff/show) and repo files, and writes nothing.

Classes, least to most restrictive (``release_train_contracts.RISK_CLASSES``):

    eligible        may ride once ready
    needs_operator  never rides automatically; an operator ride approval bound to the full head SHA may admit it
    held            does not ride: unknown risk, and Broker / Active Trader code (always held)
    blocked         cannot be a train candidate: it changes the train's own controller/classifier/policy, or the
                    input is invalid

When rules disagree, the MORE RESTRICTIVE class wins (enhanced design section 4: "resolve the conflict between
'broker/Active Trader held' and 'hot paths eligible' by applying the more restrictive rule").

Inputs (``config/release_train_policy.json``, seeded from ``config/ci_risk_tiers.json``):

1. **Changed paths.** Policy rules, then the ci_risk_tiers HIGH categories (mapped through
   ``seed.high_category_class``; a new, unmapped category is held), then the eligible globs and the tiers' LOW globs.
   A path nothing classifies is **unknown, so held**.
2. **Deletions.** Any deleted path is needs_operator (never delete; archive).
3. **Semantic config changes.** For JSON config, the changed key paths (``semantic_config_diff``). A key segment
   matching a protected pattern (live/armed/enabled/mode/stage/grant/secret/...) is needs_operator. A config path
   listed in ``semantic_config.eligible_paths`` is eligible only when its keys are known and none is protected.
4. **Generated files.** A generated file inherits the most restrictive class of its generator and its consumers
   (the generator -> consumer rule). A harmless-looking output cannot launder a protected generator.
5. **Import closure.** The reverse closure from ``scripts/lib/test_impact.py`` (imports and path references): a
   change reachable from a protected file inherits that file's class. If the closure cannot be computed, code paths
   are held.
6. **Size.** More than ``size.max_files`` files or ``size.max_changed_lines`` lines (generated files excluded) is
   needs_operator.

Consumers: ``scripts/lib/release_train_view.py`` (policy version, windows and census settings for the Command Center
view). The Phase 3 controller records each result as a ``TrainEvent@v1`` ``classified`` event.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from lib import release_train_contracts as C
    from lib import test_impact as TI
except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
    from scripts.lib import release_train_contracts as C  # type: ignore[no-redef]
    from scripts.lib import test_impact as TI  # type: ignore[no-redef]

CLASSIFIER_VERSION = "release_train_classify/1"
POLICY_PATH = ROOT / "config" / "release_train_policy.json"
POLICY_SCHEMA = "ReleaseTrainPolicy@v1"
CLASSES = C.RISK_CLASSES
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CODE_SUFFIXES = (".py", ".sh", ".json", ".yaml", ".yml", ".sql")


def rank(cls: str) -> int:
    return CLASSES.index(cls)


def worst(classes: Iterable[str]) -> str:
    out = "eligible"
    for c in classes:
        out = C.more_restrictive(out, c)
    return out


# ── policy ────────────────────────────────────────────────────────────────────────────────────────────────────


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_policy(p: Any) -> list[str]:
    """Defects in a ReleaseTrainPolicy@v1 document; [] when valid. Pure."""
    if not isinstance(p, Mapping):
        return ["policy is not an object"]
    errs: list[str] = []
    if p.get("schema") != POLICY_SCHEMA:
        errs.append(f"schema must be {POLICY_SCHEMA}")
    for k in ("policy_version", "timezone", "windows", "rules", "eligible_globs", "deletions", "size",
              "semantic_config", "generated", "import_closure", "seed", "census"):
        if k not in p:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if p.get("armed") is not False:
        errs.append("armed must be false in Phase 1 (arming is an operator act)")
    times = [w.get("local_time") for w in p["windows"]]
    if sorted(times) != ["00:00", "06:00", "08:00", "18:00"]:
        errs.append("windows must be exactly 00:00, 06:00, 08:00, 18:00")
    if any(w.get("enabled") is not False for w in p["windows"]):
        errs.append("every window must be enabled=false in Phase 1")
    ids = [r.get("id") for r in p["rules"]]
    if len(set(ids)) != len(ids):
        errs.append("duplicate rule id")
    for r in p["rules"]:
        if r.get("class") not in CLASSES:
            errs.append(f"rule {r.get('id')}: bad class {r.get('class')!r}")
        if not r.get("globs"):
            errs.append(f"rule {r.get('id')}: no globs")
    by_id = {r.get("id"): r for r in p["rules"]}
    if (by_id.get("broker_active_trader") or {}).get("class") not in ("held", "blocked"):
        errs.append("broker_active_trader must be held or more restrictive")
    if (by_id.get("train_self") or {}).get("class") != "blocked":
        errs.append("train_self must be blocked")
    seed = p["seed"]
    for cat, cls in (seed.get("high_category_class") or {}).items():
        if cls not in CLASSES:
            errs.append(f"seed.high_category_class.{cat}: bad class {cls!r}")
    if seed.get("unmapped_high_category_class") not in ("held", "blocked"):
        errs.append("seed.unmapped_high_category_class must be held or blocked (unknown risk is held)")
    for k in ("deletions", "size"):
        if p[k].get("class") not in ("needs_operator", "held", "blocked"):
            errs.append(f"{k}.class must be needs_operator or more restrictive")
    sc = p["semantic_config"]
    if sc.get("unknown_keys_class") not in ("held", "blocked"):
        errs.append("semantic_config.unknown_keys_class must be held or blocked")
    if p["import_closure"].get("unavailable_class") not in ("held", "blocked"):
        errs.append("import_closure.unavailable_class must be held or blocked")
    for g in p["generated"]:
        if not g.get("globs") or not g.get("generator"):
            errs.append("generated entry needs globs and generator")
    return errs


@lru_cache(maxsize=4096)
def _glob_re(glob: str) -> "re.Pattern":
    return TI.glob_to_re(glob)


def _match(path: str, globs: Iterable[str]) -> bool:
    return any(_glob_re(g).match(path) for g in globs)


# ── path classification ───────────────────────────────────────────────────────────────────────────────────────


def _reason(rule: str, cls: str, path: str, detail: str) -> dict[str, str]:
    return {"rule": rule, "class": cls, "path": path, "detail": detail}


def rule_matches(path: str, policy: Mapping[str, Any], tiers: Optional[Mapping[str, Any]]) -> list[dict]:
    """Explicit protections only (policy rules + ci_risk_tiers HIGH). No default, no eligible."""
    out = []
    for r in policy["rules"]:
        if _match(path, r["globs"]):
            out.append(_reason(r["id"], r["class"], path, r.get("reason", "")))
    seed = policy["seed"]
    mapping = seed.get("high_category_class") or {}
    for cat, spec in ((tiers or {}).get("high") or {}).items():
        if _match(path, spec.get("globs") or ()):
            cls = mapping.get(cat, seed["unmapped_high_category_class"])
            note = "" if cat in mapping else " (category not mapped by the train policy: unknown risk)"
            out.append(_reason(f"ci_risk_tiers:{cat}", cls, path, f"config/ci_risk_tiers.json HIGH {cat}{note}"))
    return out


def base_class(path: str, policy: Mapping[str, Any], tiers: Optional[Mapping[str, Any]]) -> tuple[str, list[dict]]:
    """Class of one path from its name alone: protections, else eligible globs, else UNKNOWN (held)."""
    hits = rule_matches(path, policy, tiers)
    if hits:
        return worst(h["class"] for h in hits), hits
    low = list(policy.get("eligible_globs") or []) + list(((tiers or {}).get("low") or {}).get("globs") or [])
    if _match(path, low):
        return policy["seed"].get("low_class", "eligible"), []
    return "unknown", []


def _generated_entry(path: str, policy: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    for g in policy.get("generated") or ():
        if _match(path, g["globs"]):
            return g
    return None


def semantic_config_diff(before: Any, after: Any, prefix: str = "") -> list[str]:
    """Dotted key paths whose value differs between two JSON documents. Pure. Lists compare whole."""
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        out: list[str] = []
        for k in sorted(set(before) | set(after), key=str):
            key = f"{prefix}.{k}" if prefix else str(k)
            if k not in before or k not in after:
                out.append(key)
            else:
                out.extend(semantic_config_diff(before[k], after[k], key))
        return out
    return [] if before == after else [prefix or "$"]


def _protected_keys(keys: Iterable[str], patterns: Sequence[str]) -> list[str]:
    hit = []
    for key in keys:
        segs = [s.lower() for s in str(key).split(".")]
        if any(fnmatch.fnmatchcase(s, pat.lower()) for s in segs for pat in patterns):
            hit.append(key)
    return hit


def _closure(path: str, impact_map: Mapping[str, Any], policy: Mapping[str, Any],
             tiers: Optional[Mapping[str, Any]]) -> list[dict]:
    """Protected files that can reach ``path`` (reverse closure). One reason per propagating class, shortest chain."""
    cfg = policy["import_closure"]
    rdeps = impact_map.get("rdeps") or {}
    excl = tuple(cfg.get("exclude_prefixes") or ())
    prop = set(cfg.get("propagate_classes") or ())
    max_depth = cfg.get("max_depth")
    memo: dict[str, list] = {}
    parent: dict[str, Optional[str]] = {path: None}
    frontier, depth = [path], 0
    found: dict[str, tuple[str, str]] = {}  # class -> (file, rule)
    while frontier and (max_depth is None or depth < max_depth):
        depth += 1
        nxt = []
        for node in frontier:
            for dep in rdeps.get(node, ()):
                if dep in parent or dep.startswith(excl):
                    continue
                parent[dep] = node
                nxt.append(dep)
                hits = memo.get(dep)
                if hits is None:
                    hits = memo[dep] = rule_matches(dep, policy, tiers)
                if hits:
                    cls = worst(h["class"] for h in hits)
                    if cls in prop and cls not in found:
                        found[cls] = (dep, hits[0]["rule"])
        frontier = nxt
    out = []
    for cls, (dep, rule) in sorted(found.items(), key=lambda kv: -rank(kv[0])):
        chain, n = [], dep
        while n is not None:
            chain.append(n)
            n = parent[n]
        out.append(_reason("import_closure", cls, path,
                           f"reachable from {dep} ({rule}): " + " -> ".join(reversed(chain))))
    return out


def build_import_rdeps(root: Path = ROOT) -> dict[str, Any]:
    """Reverse Python-IMPORT graph over ``scripts/`` (and ``tests/``), built with test_impact's own resolver
    (``_iter_files`` / ``_module_names`` / ``_imports``), so a name resolves exactly as the test selector resolves it.
    Unlike test_impact's map it leaves out string path references: a shell script or a docstring that merely names
    ``scripts/api_v2.py`` does not load it, and counting those edges made every library change reach the deploy
    script (measured 2026-10-21: ``scripts/lib/needs_action.py`` -> ``scripts/api_v2.py`` ->
    ``scripts/cio_phase2_exact_main_deploy.sh``, a string reference)."""
    import ast
    import warnings

    files = list(TI._iter_files(root))
    name_to_file: dict[str, str] = {}
    for p in files:
        rel = TI._rel(root, p)
        for n in TI._module_names(rel):
            name_to_file.setdefault(n, rel)
    rdeps: dict[str, set] = {}
    for p in files:
        rel = TI._rel(root, p)
        if not rel.endswith(".py"):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for imp in TI._imports(tree):
            target = name_to_file.get(imp)
            if target and target != rel:
                rdeps.setdefault(target, set()).add(rel)
    return {"edges": "imports", "rdeps": {k: sorted(v) for k, v in sorted(rdeps.items())}}


def load_impact_map(root: Path = ROOT, *, edges: str = "imports") -> Optional[dict]:
    """The reverse-dependency map for the closure, or None when it cannot be built (then code paths are held).
    ``edges="imports"`` (policy default): Python imports only. ``"imports_and_refs"``: test_impact's full map."""
    try:
        if edges == "imports_and_refs":
            m, _status = TI.load_map(root)
            return m
        return build_import_rdeps(root)
    except Exception:  # noqa: BLE001 - an unavailable closure is a held change, never an eligible one
        return None


# ── the classifier ────────────────────────────────────────────────────────────────────────────────────────────


def classify_change(change: Mapping[str, Any], policy: Mapping[str, Any], *,
                    tiers: Optional[Mapping[str, Any]] = None,
                    impact_map: Optional[Mapping[str, Any]] = None,
                    root: Path = ROOT) -> dict[str, Any]:
    """Classify one change set. Pure given its inputs (``root`` is only used to check a generator exists).

    ``change`` = {"paths": [{"path", "status": "A"|"M"|"D"|"R", "lines_added", "lines_deleted", "old_path"?}],
                  "semantic_config": {path: [changed key paths]} (optional), "head_sha" (optional)}
    Returns {"class", "reasons": [...], "paths": {path: class}, "size", "closure", "next_action", versions}.
    """
    reasons: list[dict] = []
    per_path: dict[str, str] = {}
    out = {"classifier_version": CLASSIFIER_VERSION, "policy_version": policy.get("policy_version")}
    perrs = validate_policy(policy)
    paths = list(change.get("paths") or [])
    head = change.get("head_sha")
    if perrs:
        reasons.append(_reason("invalid_policy", "blocked", "", "; ".join(perrs)[:400]))
    if not paths:
        reasons.append(_reason("invalid_input", "blocked", "", "no changed paths"))
    if head is not None and not _SHA_RE.match(str(head)):
        reasons.append(_reason("invalid_input", "blocked", "", "head_sha is not a full 40-hex SHA"))
    if any(r["class"] == "blocked" for r in reasons):
        return {**out, "class": "blocked", "reasons": reasons, "paths": {}, "size": None,
                "closure": {"status": "NOT_RUN"}, "next_action": _next_action("blocked")}

    semantic = change.get("semantic_config") or {}
    sc = policy["semantic_config"]
    cfg = policy["import_closure"]
    closure_status = "OK" if cfg.get("enabled") and impact_map is not None else (
        "DISABLED" if not cfg.get("enabled") else "UNAVAILABLE")
    files = lines = 0
    for item in paths:
        path = str(item.get("path") or "")
        status = str(item.get("status") or "M")[:1].upper()
        names = [path] + ([str(item["old_path"])] if status == "R" and item.get("old_path") else [])
        gen = _generated_entry(path, policy)
        cls_list: list[str] = []
        for name in names:
            cls, hits = base_class(name, policy, tiers)
            reasons.extend(hits)
            if cls == "unknown" and gen is None:
                if name in semantic and name in (sc.get("eligible_paths") or []):
                    cls = "eligible"
                else:
                    detail = ("config path without known semantic keys" if name in (sc.get("eligible_paths") or [])
                              else "no rule classifies this path")
                    cls = "held"
                    reasons.append(_reason("unknown_risk", "held", name, detail))
            if cls != "unknown":
                cls_list.append(cls)
        if status == "D":
            d = policy["deletions"]
            cls_list.append(d["class"])
            reasons.append(_reason("deletion", d["class"], path, d.get("reason", "")))
        if path in semantic:
            keys = list(semantic[path] or [])
            prot = _protected_keys(keys, sc.get("protected_key_segment_patterns") or [])
            if prot:
                cls_list.append(sc["protected_class"])
                reasons.append(_reason("semantic_config", sc["protected_class"], path,
                                       f"{sc.get('protected_reason', '')} keys: {', '.join(prot[:8])}"))
        if gen is not None:
            gcls = []
            for src in [gen["generator"], *(gen.get("consumers") or [])]:
                c2, hits = base_class(src, policy, tiers)
                if c2 == "unknown" or not (root / src).exists():
                    c2 = "held"
                    reasons.append(_reason("generated_unknown", "held", path,
                                           f"generator/consumer {src} is unclassified or missing"))
                gcls.append(c2)
                for h in hits:
                    reasons.append(_reason("generated:" + h["rule"], h["class"], path,
                                           f"generated by/for {src}: {h['detail']}"))
            cls_list.append(worst(gcls))
        else:
            files += 1
            lines += int(item.get("lines_added") or 0) + int(item.get("lines_deleted") or 0)
        if not path.startswith(tuple(cfg.get("exclude_prefixes") or ())):
            if closure_status == "OK":
                cr = _closure(path, impact_map or {}, policy, tiers)
                reasons.extend(cr)
                cls_list.extend(r["class"] for r in cr)
            elif closure_status == "UNAVAILABLE" and path.endswith(_CODE_SUFFIXES):
                cls_list.append(cfg["unavailable_class"])
                reasons.append(_reason("import_closure_unavailable", cfg["unavailable_class"], path,
                                       "the reverse-dependency map could not be built, so reach is unknown"))
        per_path[path] = worst(cls_list) if cls_list else "held"
    sz = policy["size"]
    if files > sz["max_files"] or lines > sz["max_changed_lines"]:
        reasons.append(_reason("oversized", sz["class"], "",
                               f"{files} files / {lines} changed lines (max {sz['max_files']} / "
                               f"{sz['max_changed_lines']})"))
    final = worst(list(per_path.values()) + [r["class"] for r in reasons])
    uniq, seen = [], set()
    for r in sorted(reasons, key=lambda r: (-rank(r["class"]), r["rule"], r["path"])):
        key = (r["rule"], r["class"], r["path"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return {**out, "class": final, "reasons": uniq, "paths": per_path,
            "size": {"files": files, "changed_lines": lines, "max_files": sz["max_files"],
                     "max_changed_lines": sz["max_changed_lines"]},
            "closure": {"status": closure_status}, "next_action": _next_action(final, uniq)}


def _next_action(cls: str, reasons: Sequence[Mapping[str, Any]] = ()) -> str:
    if cls == "eligible":
        return "May ride a train once its checks are green and a window is enabled."
    top = reasons[0]["rule"] if reasons else ""
    return {
        "needs_operator": f"Never rides automatically ({top}). An operator ride approval bound to the full head "
                          "SHA may admit it.",
        "held": f"Does not ride ({top}). The owner resolves the risk; broker code needs an execution-engineering "
                "grant and a manual release.",
        "blocked": f"Cannot be a train candidate ({top}). Release through the manual process.",
    }[cls]


# ── git helpers (read-only) ───────────────────────────────────────────────────────────────────────────────────


def _git(args: Sequence[str], root: Path) -> Optional[str]:
    r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else None


def changeset_from_git(base: str, head: str = "HEAD", *, root: Path = ROOT) -> Optional[dict[str, Any]]:
    """Read-only: the change set of ``base...head`` (name-status + numstat + semantic JSON keys)."""
    ns = _git(["diff", "--name-status", "-M", f"{base}...{head}"], root)
    num = _git(["diff", "--numstat", "-M", f"{base}...{head}"], root)
    mb = _git(["merge-base", base, head], root)
    sha = _git(["rev-parse", head], root)
    if ns is None or num is None or mb is None:
        return None
    counts: dict[str, tuple[int, int]] = {}
    for line in num.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            a = int(parts[0]) if parts[0].isdigit() else 0
            d = int(parts[1]) if parts[1].isdigit() else 0
            name = parts[-1]
            if " => " in name:  # rename notation: dir/{old => new}.py or old => new
                m = re.match(r"^(.*)\{(.*) => (.*)\}(.*)$", name)
                name = (m.group(1) + m.group(3) + m.group(4)).replace("//", "/") if m else name.split(" => ")[-1]
            counts[name] = (a, d)
    paths, semantic = [], {}
    for line in ns.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        st = parts[0][:1]
        item: dict[str, Any] = {"path": parts[-1], "status": st}
        if st == "R" and len(parts) >= 3:
            item["old_path"] = parts[1]
        a, d = counts.get(item["path"], (0, 0))
        item.update(lines_added=a, lines_deleted=d)
        paths.append(item)
        p = item["path"]
        if p.endswith(".json") and st in ("M", "A"):
            old = _git(["show", f"{mb.strip()}:{item.get('old_path', p)}"], root) if st == "M" else "{}"
            new = _git(["show", f"{head}:{p}"], root)
            try:
                semantic[p] = semantic_config_diff(json.loads(old or "null"), json.loads(new or "null"))
            except ValueError:
                pass  # unparseable JSON: keys unknown, so the path is classified without them
    return {"paths": paths, "semantic_config": semantic, "head_sha": (sha or "").strip() or None,
            "base": base, "merge_base": mb.strip()}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Classify a change for the release train (read-only).")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--paths", nargs="*", help="classify these paths as modified (no git diff)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-closure", action="store_true", help="skip the import closure (reports it UNAVAILABLE)")
    a = ap.parse_args(argv)
    policy = load_policy()
    tiers = TI.load_tiers()
    if a.paths:
        change = {"paths": [{"path": p, "status": "M"} for p in a.paths]}
    else:
        change = changeset_from_git(a.base, a.head)
        if change is None:
            print(f"[release-train-classify] cannot diff {a.base}...{a.head}", file=sys.stderr)
            return 2
    imap = None if a.no_closure else load_impact_map(edges=policy["import_closure"].get("edges", "imports"))
    res = classify_change(change, policy, tiers=tiers, impact_map=imap)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"class={res['class']} files={res['size'] and res['size']['files']} "
              f"closure={res['closure']['status']} policy={res['policy_version']}")
        for r in res["reasons"][:20]:
            print(f"  [{r['class']}] {r['rule']} {r['path']}: {r['detail'][:160]}")
        print(f"next: {res['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
