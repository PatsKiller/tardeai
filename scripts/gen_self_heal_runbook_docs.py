#!/usr/bin/env python3
"""Generate or check the self-heal runbook workbook (LQ-20261107-1259).

    python3 scripts/gen_self_heal_runbook_docs.py --write     # write the pages
    python3 scripts/gen_self_heal_runbook_docs.py --check     # the default: exit 1 if a page would change
    python3 scripts/gen_self_heal_runbook_docs.py --check --json

Inputs (all read-only): ``config/self_heal_runbook_catalog.json``, ``docs/runbooks/self_heal/COVERAGE.json`` (the
replay snapshot) and ``tests/fixtures/self_heal_runbooks/*.json`` (the corpus index the entry pages link).

Exit codes: 0 the pages are current (or were written); 1 the pages are stale or missing (``--check``); 2 usage; 3 an
unexpected file sits in the directory — a page for an entry that no longer exists. Nothing is ever deleted: an orphan
is reported for a human (or the entry's owner) to archive. ``README.md``, ``RULINGS.md`` and ``COVERAGE.json`` are
hand-written and are never written or judged here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import self_heal_runbook_docs as D  # noqa: E402
from scripts.lib.self_heal_runbooks import CATALOG_PATH, load_catalog  # noqa: E402


def fixture_index(directory: Path) -> dict[str, list[str]]:
    """``entry id -> [fixture stem]`` from the replay corpus, read as data (never imported)."""
    out: dict[str, list[str]] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entry = str(((doc or {}).get("expect") or {}).get("entry_id") or "")
        if entry:
            out.setdefault(entry, []).append(path.stem)
    return out


def _resolve(value: str) -> Path:
    """A CLI path: relative to the repository root, so the generator works from any working directory."""
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def dispatch(args: argparse.Namespace) -> int:
    catalog_path = _resolve(args.catalog)
    coverage_path = _resolve(args.coverage)
    out_dir = _resolve(args.out_dir)
    catalog_doc = json.loads(catalog_path.read_text(encoding="utf-8"))
    # load_catalog validates before anything is rendered: a broken catalog must not produce pages.
    load_catalog(catalog_path)
    coverage = None
    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    elif args.require_coverage:
        print(f"missing coverage snapshot: {coverage_path} (run scripts/ops/self_heal_runbook_replay.py)", file=sys.stderr)
        return 2
    else:
        print(f"note: no coverage snapshot at {coverage_path}; pages render without replay columns", file=sys.stderr)

    rendered = D.render_all(catalog_doc, coverage, fixtures_by_entry=fixture_index(_resolve(args.fixtures)))
    on_disk = {p.name: p for p in out_dir.glob("*") if p.is_file()} if out_dir.is_dir() else {}
    stale = [name for name, text in sorted(rendered.items())
             if name in on_disk and on_disk[name].read_text(encoding="utf-8") != text]
    missing = [name for name in sorted(rendered) if name not in on_disk]
    unexpected = sorted(name for name in on_disk if name not in rendered and name not in D.STATIC_FILES)

    if args.json:
        print(json.dumps({"stale": stale, "missing": missing, "unexpected": unexpected,
                          "written": args.write, "files": len(rendered)}, indent=2))
    else:
        verb = "wrote" if args.write else "stale"
        if args.write:
            written = 0
            for name in sorted(rendered):
                target = out_dir / name
                if name in on_disk and on_disk[name].read_text(encoding="utf-8") == rendered[name]:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(rendered[name], encoding="utf-8")
                written += 1
            print(f"wrote {written} of {len(rendered)} file(s) under {out_dir}")
        else:
            print(f"{len(rendered)} rendered file(s); {verb}: {len(stale)}; missing: {len(missing)}")
            for name in stale:
                print(f"  STALE  {name}")
            for name in missing:
                print(f"  MISSING {name}")
        for name in unexpected:
            print(f"  UNEXPECTED {name} — no entry renders this file; archive it, do not delete it")

    if unexpected:
        return 3
    if not args.write and (stale or missing):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write the pages (the only mode that writes)")
    group.add_argument("--check", action="store_true", help="the default: report a page that would change")
    parser.add_argument("--catalog", default=str(CATALOG_PATH))
    parser.add_argument("--coverage", default=str(Path(D.DOCS_DIR) / "COVERAGE.json"))
    parser.add_argument("--out-dir", default=D.DOCS_DIR)
    parser.add_argument("--fixtures", default="tests/fixtures/self_heal_runbooks")
    parser.add_argument("--require-coverage", action="store_true",
                        help="fail instead of rendering without the replay snapshot")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    return dispatch(args)


if __name__ == "__main__":
    raise SystemExit(main())
