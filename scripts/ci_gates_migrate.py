#!/usr/bin/env python3
"""Move inline ``GATES = [...]`` entries out of scripts/run_cio_hardening_ci.py into
``config/ci_gates/<name>.json`` (one file per gate; scripts/lib/ci_gates.py).

Re-runnable by design (operator process plan 2026-10-21). Many PRs still add inline gates
until this change lands; right before merge, take main's runner and run this again:

    git checkout origin/main -- scripts/run_cio_hardening_ci.py
    python3 scripts/ci_gates_migrate.py            # dry run: what it would write
    python3 scripts/ci_gates_migrate.py --apply    # write gate files + rewrite GATES
    python3 scripts/ci_gates_migrate.py --verify-against origin/main --allow-extra

* Dry run by default: prints the plan, writes nothing.
* ``--apply`` writes one canonical file per inline entry, then replaces the ``GATES = [...]``
  literal with the loader. A gate file that already exists with identical bytes is left alone;
  one that exists with DIFFERENT content is a conflict and nothing is written (two sources of
  one gate -- a human decides), unless ``--overwrite``: then the inline entry wins (use it on the
  pre-merge re-run, where main's inline list is the newest truth). A gate file whose name is NOT
  in the inline list is reported (renamed/removed on main?) and never deleted by this script.
* The comment lines attached to an entry (the lines above it, and any inside the tuple) are kept
  verbatim in the ``comment`` field; an ``ANCHOR: X`` id is also copied to ``anchor``.
* Runner already migrated (``GATES`` is not a list literal): nothing to move, exit 0.
* ``--verify-against REF``: load the gates from ``config/ci_gates/`` and prove they equal the
  inline list at ``REF`` (same names, same files per gate; order = sorted by name). Exit 1 on
  any difference.

Stdlib only. Touches only the repo working tree. AUTHORITY: READ_ONLY_ADVISORY (CI tooling).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lib import ci_gates  # noqa: E402

RUNNER_REL = "scripts/run_cio_hardening_ci.py"
OLD_HEADER = "# Ordered, explicit suite list (Phase 10.2)"

LOADER_BLOCK = '''\
# Gate registry (2026-10-21, operator-approved process plan): ONE JSON FILE PER GATE under
# config/ci_gates/<name>.json (schema CiGate@v1, scripts/lib/ci_gates.py), loaded sorted by name.
# To add a gate, ADD A FILE there -- never an inline list here: parallel PRs that each appended to
# one list collided on every merge. How-to: docs/ops/CI_FAST_CORE_20260925.md "Adding a gate".
# scripts/ci_gates_migrate.py moves any inline entries back out (re-runnable).
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from scripts.lib import ci_gates as _ci_gates  # noqa: E402

GATES = _ci_gates.load_gates(REPO)'''


def _gates_assign(tree: ast.Module) -> ast.Assign | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "GATES" for t in node.targets):
            return node
    return None


def parse_inline(text: str) -> tuple[ast.Assign | None, list[dict]]:
    """Return (GATES assignment node, [{name, files, comment}]) for an inline list; [] if none."""
    tree = ast.parse(text)
    node = _gates_assign(tree)
    if node is None or not isinstance(node.value, ast.List):
        return node, []
    comments: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            body = tok.string[1:]
            comments[tok.start[0]] = body[1:] if body.startswith(" ") else body
    entries: list[dict] = []
    prev_end = node.lineno
    for elt in node.value.elts:
        try:
            name, files = ast.literal_eval(elt)
        except (ValueError, TypeError) as exc:
            raise SystemExit(f"GATES entry at line {elt.lineno} is not a literal (name, [files]): {exc}")
        if not isinstance(name, str) or not isinstance(files, list):
            raise SystemExit(f"GATES entry at line {elt.lineno} is not (str, list)")
        lines = [ln for ln in sorted(comments) if prev_end < ln <= elt.end_lineno]
        entries.append({"name": name, "files": files, "comment": [comments[ln] for ln in lines]})
        prev_end = elt.end_lineno
    orphan = [ln for ln in comments if prev_end < ln <= node.end_lineno]
    if orphan:
        raise SystemExit(f"comment lines {orphan} after the last GATES entry belong to no gate; move them first")
    names = [e["name"] for e in entries]
    dups = sorted({n for n in names if names.count(n) > 1})
    if dups:
        raise SystemExit(f"duplicate inline gate names: {dups}")
    return node, entries


def rewrite_runner(text: str, node: ast.Assign) -> str:
    lines = text.splitlines(keepends=True)
    start, end = node.lineno - 1, node.end_lineno  # 0-based [start, end)
    if start > 0 and lines[start - 1].strip() == OLD_HEADER:
        start -= 1
    return "".join(lines[:start]) + LOADER_BLOCK + "\n" + "".join(lines[end:])


def digest(gates: list[tuple[str, list[str]]]) -> str:
    return hashlib.sha256(json.dumps(gates, separators=(",", ":")).encode()).hexdigest()[:16]


def migrate(root: Path, *, apply: bool, overwrite: bool = False) -> int:
    runner = root / RUNNER_REL
    text = runner.read_text(encoding="utf-8")
    node, entries = parse_inline(text)
    if node is None:
        print(f"{RUNNER_REL}: no GATES assignment found", file=sys.stderr)
        return 1
    if not entries:
        n = len(ci_gates.load_records(root))
        print(f"{RUNNER_REL}: GATES is already the loader; nothing to migrate ({n} gate files).")
        return 0
    new, same, conflicts = [], [], []
    for e in entries:
        rec = ci_gates.make_record(e["name"], e["files"], e["comment"])
        body = ci_gates.render(rec)
        p = ci_gates.gate_path(root, e["name"])
        if not p.exists():
            new.append((p, body))
        elif p.read_text(encoding="utf-8") == body:
            same.append(p)
        else:
            conflicts.append(p)
    print(f"inline GATES entries: {len(entries)}  new files: {len(new)}  identical existing: {len(same)}  "
          f"conflicting existing: {len(conflicts)}")
    inline_names = {e["name"] for e in entries}
    gdir = ci_gates.gates_dir(root)
    on_disk = sorted(p.stem for p in gdir.glob("*.json")) if gdir.is_dir() else []
    for n in (n for n in on_disk if n not in inline_names):
        print(f"  NOTE {ci_gates.GATES_DIR_REL}/{n}.json is not in the inline list (kept; check it was not "
              "renamed or removed upstream)")
    for p in conflicts:
        tag = "OVERWRITE" if overwrite else "CONFLICT"
        print(f"  {tag} {p.relative_to(root)}: exists with different content", file=sys.stderr)
    if conflicts and not overwrite:
        print("resolve by hand, or re-run with --overwrite to let the inline entries win", file=sys.stderr)
        return 1
    by_name = {e["name"]: e for e in entries}
    for p in conflicts:
        e = by_name[p.stem]
        new.append((p, ci_gates.render(ci_gates.make_record(e["name"], e["files"], e["comment"]))))
    pre_existing = dict(ci_gates.load_gates(root)) if on_disk else {}
    if not apply:
        for p, _b in new[:10]:
            print(f"  would write {p.relative_to(root)}")
        if len(new) > 10:
            print(f"  ... and {len(new) - 10} more")
        print(f"DRY RUN: nothing written. Re-run with --apply to write {len(new)} files and rewrite {RUNNER_REL}.")
        return 0
    ci_gates.gates_dir(root).mkdir(parents=True, exist_ok=True)
    for p, body in new:
        p.write_text(body, encoding="utf-8")
    runner.write_text(rewrite_runner(text, node), encoding="utf-8")
    # Prove it: loaded == pre-existing files + the inline list, sorted by name.
    want = dict(pre_existing)
    want.update({e["name"]: e["files"] for e in entries})
    expected = sorted(want.items())
    loaded = ci_gates.load_gates(root)
    if [(n, list(f)) for n, f in expected] != loaded:
        print("FAIL: loaded gates differ from the migrated list", file=sys.stderr)
        return 1
    print(f"APPLIED: wrote {len(new)} gate files; {RUNNER_REL} GATES now loads {len(loaded)} gates "
          f"(digest {digest(loaded)}).")
    return 0


def verify_against(root: Path, ref: str, *, allow_extra: bool = False) -> int:
    r = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{RUNNER_REL}"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"cannot read {ref}:{RUNNER_REL}: {r.stderr.strip()}", file=sys.stderr)
        return 1
    _node, old = parse_inline(r.stdout)
    if not old:
        print(f"{ref}:{RUNNER_REL} has no inline GATES list; nothing to compare", file=sys.stderr)
        return 1
    old_pairs = [(e["name"], e["files"]) for e in old]
    loaded = ci_gates.load_gates(root)
    old_sorted = sorted(old_pairs)
    missing = sorted({n for n, _ in old_pairs} - {n for n, _ in loaded})
    extra = sorted({n for n, _ in loaded} - {n for n, _ in old_pairs})
    changed = sorted(n for n, f in old_pairs if n in dict(loaded) and dict(loaded)[n] != f)
    print(f"{ref} inline: {len(old_pairs)} gates, {sum(len(f) for _, f in old_pairs)} file slots, "
          f"sorted digest {digest(old_sorted)}")
    print(f"config/ci_gates: {len(loaded)} gates, {sum(len(f) for _, f in loaded)} file slots, "
          f"digest {digest(loaded)}")
    print(f"missing={missing} extra={extra} files_changed={changed}")
    restricted = [(n, f) for n, f in loaded if n not in set(extra)]
    if old_sorted != restricted:
        print("NOT EQUIVALENT")
        return 1
    if extra and not allow_extra:
        print(f"NOT EQUIVALENT: {len(extra)} gate(s) not in {ref} (pass --allow-extra if this branch added them)")
        return 1
    print(f"EQUIVALENT on all {len(old_pairs)} gates of {ref}: same names, same files per gate (in file order), "
          f"order = sorted by name" + (f"; plus {len(extra)} gate(s) added here: {extra}" if extra else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="write gate files and rewrite the runner (default: dry run)")
    ap.add_argument("--overwrite", action="store_true", help="--apply: inline entries win over differing gate files")
    ap.add_argument("--verify-against", metavar="REF", help="prove config/ci_gates equals REF's inline GATES")
    ap.add_argument("--allow-extra", action="store_true", help="--verify-against: gates added on this branch are OK")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.verify_against:
        return verify_against(args.root, args.verify_against, allow_extra=args.allow_extra)
    return migrate(args.root, apply=args.apply, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
