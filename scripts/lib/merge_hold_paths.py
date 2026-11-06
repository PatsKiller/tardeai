"""merge_hold_paths.py — the one list of paths Mergify must never merge.

Reads ``config/merge_hold_paths.json`` and gives:

* ``held_classes(paths)`` — which hold classes a changed-file list hits (the digest uses it);
* ``mergify_regexes()`` — the anchored ``files~=`` regexes ``.mergify.yml``'s hold rule must carry;
* ``order_scan_violations(root)`` — modules that place/submit orders but are outside the hold.

Pure functions, no network, no writes. ``MBI_BEHAVIOR = 0``.

  python scripts/lib/merge_hold_paths.py --print-mergify
  python scripts/lib/merge_hold_paths.py --check-order-scan
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "merge_hold_paths.json"


@lru_cache(maxsize=4)
def _load_cached(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(path: Path | None = None) -> dict[str, Any]:
    return _load_cached(str(path or CONFIG_PATH))


def glob_to_regex(glob: str) -> str:
    """Segment-aware glob → anchored regex (``*`` stays inside one path segment)."""
    out = ["^"]
    i = 0
    n = len(glob)
    while i < n:
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(.*/)?")
            i += 3
        elif glob.startswith("/**", i) and i + 3 == n:
            out.append("/.*")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return "".join(out)


def hold_labels(cfg: dict[str, Any] | None = None) -> frozenset[str]:
    cfg = cfg or load()
    return frozenset(str(x) for x in cfg.get("hold_labels") or [])


def mergify_regexes(cfg: dict[str, Any] | None = None) -> list[str]:
    """Ordered, de-duplicated regexes for the ``.mergify.yml`` hold rule."""
    cfg = cfg or load()
    seen: list[str] = []
    for cls in cfg.get("classes") or []:
        for g in cls.get("globs") or []:
            rx = glob_to_regex(str(g))
            if rx not in seen:
                seen.append(rx)
    return seen


def _compiled(cfg: dict[str, Any]) -> list[tuple[str, str, re.Pattern]]:
    rows = []
    for cls in cfg.get("classes") or []:
        for g in cls.get("globs") or []:
            rows.append((str(cls.get("id")), str(g), re.compile(glob_to_regex(str(g)))))
    return rows


def held_classes(paths: Iterable[str], cfg: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """``{class_id: [path, ...]}`` for every changed path inside the hold."""
    cfg = cfg or load()
    rows = _compiled(cfg)
    hits: dict[str, list[str]] = {}
    for p in paths:
        p = str(p)
        if p.startswith("./"):
            p = p[2:]
        for cid, _g, rx in rows:
            if rx.search(p):
                hits.setdefault(cid, [])
                if p not in hits[cid]:
                    hits[cid].append(p)
    return hits


def is_held_path(path: str, cfg: dict[str, Any] | None = None) -> bool:
    return bool(held_classes([path], cfg))


def risk_flags(paths: Iterable[str], cfg: dict[str, Any] | None = None) -> list[str]:
    cfg = cfg or load()
    flags = []
    plist = list(paths)
    for name, globs in (cfg.get("risk_flags") or {}).items():
        rxs = [re.compile(glob_to_regex(g)) for g in globs]
        if any(rx.search(p) for p in plist for rx in rxs):
            flags.append(str(name))
    return flags


def order_scan_violations(root: Path = ROOT, cfg: dict[str, Any] | None = None) -> list[str]:
    """Order-placing modules that are neither held nor exempt (repo-relative paths)."""
    cfg = cfg or load()
    scan = cfg.get("order_scan") or {}
    pattern = re.compile(str(scan.get("pattern") or r"def place_order\b"))
    exempt = [re.compile(glob_to_regex(str(e.get("glob")))) for e in scan.get("exempt") or []]
    bad: list[str] = []
    for sub in scan.get("roots") or ["scripts"]:
        base = root / sub
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            if "/node_modules/" in rel:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not pattern.search(text):
                continue
            if any(rx.search(rel) for rx in exempt):
                continue
            if not is_held_path(rel, cfg):
                bad.append(rel)
    return bad


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print-mergify", action="store_true")
    ap.add_argument("--check-order-scan", action="store_true")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args(argv)
    if a.print_mergify:
        for rx in mergify_regexes():
            print(f"          - files~={rx}")
    if a.check_order_scan:
        bad = order_scan_violations()
        for b in bad:
            print(f"NOT HELD: {b}")
        return 1 if bad else 0
    if a.paths:
        print(json.dumps(held_classes(a.paths), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
