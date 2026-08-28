#!/usr/bin/env python3
"""Run a measurement against LIVE state, from the live release, correctly.

    python3 scripts/measure_live.py -c "from scripts.lib.x import f; print(f())"
    python3 scripts/measure_live.py --file probe.py
    python3 scripts/measure_live.py --with-worktree scripts/lib/a.py scripts/lib/b.py -c "..."

Running a measurement from a worktree is the trap this exists to close. The
worktree has no `data/` -- the release directory carries symlinks into
persistent-state -- so putting the worktree first on sys.path makes every
collector read nothing and report DATA_UNAVAILABLE. The numbers look clean and
mean nothing. That has happened twice; the second time it nearly produced a
finding that "every domain is unavailable".

So: cwd and sys.path are the LIVE release, always. To measure a change that is
not deployed yet, name the changed files with --with-worktree. They are copied
into the release, the measurement runs, and the originals are restored and
verified byte-identical -- which is the only honest way to see a patch's effect
on real data before it ships.

AUTHORITY: READ_ONLY_ADVISORY. Runs whatever it is given; it does not itself
write state.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")


def live_root() -> Path:
    root = CURRENT.resolve()
    if not (root / "scripts").is_dir():
        raise SystemExit(f"live release not found at {CURRENT}")
    return root


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--code", help="python source to run")
    ap.add_argument("--file", help="python file to run")
    ap.add_argument("--with-worktree", nargs="*", default=[], metavar="REL",
                    help="repo-relative files to swap in from this worktree first")
    args = ap.parse_args()
    if not args.code and not args.file:
        ap.error("one of -c/--code or --file is required")

    root = live_root()
    here = Path(__file__).resolve().parents[1]

    # sys.path is set INSIDE the child, in the live release's own terms.
    preamble = (
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        f"sys.path.insert(0, {str(root / 'scripts')!r})\n"
        f"sys.path.insert(0, {str(root / 'scripts' / 'lib')!r})\n"
    )
    body = args.code if args.code else Path(args.file).read_text(encoding="utf-8")

    swapped: list[tuple[Path, Path, str]] = []
    tmp = Path(tempfile.mkdtemp(prefix="measure_live_"))
    try:
        for rel in args.with_worktree:
            src, dest = here / rel, root / rel
            if not src.is_file():
                raise SystemExit(f"--with-worktree: {src} not found")
            if not dest.is_file():
                raise SystemExit(f"--with-worktree: {dest} not in the live release")
            backup = tmp / Path(rel).name
            shutil.copy2(dest, backup)
            swapped.append((dest, backup, _sha(dest)))
            shutil.copy2(src, dest)
            print(f"[measure-live] swapped in {rel}", file=sys.stderr)

        proc = subprocess.run([sys.executable, "-c", preamble + body], cwd=str(root))
        return proc.returncode
    finally:
        for dest, backup, before in swapped:
            shutil.copy2(backup, dest)
            after = _sha(dest)
            state = "restored" if after == before else "RESTORE MISMATCH"
            print(f"[measure-live] {state} {dest.name}", file=sys.stderr)
            if after != before:
                print("[measure-live] the live release may be modified — investigate",
                      file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
