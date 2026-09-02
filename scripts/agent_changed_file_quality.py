#!/usr/bin/env python3
"""Deterministic changed-file quality floor (SOP Stage 6).

Exit 0 only when all applicable gates pass.
When changed Python files exist, Ruff is **required** (check + format --check).
Missing Ruff with Python changes → BLOCKED (nonzero). Does not mass-format
legacy files.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.sop_toolchain import (  # noqa: E402
    PINNED_RUFF_VERSION,
    resolve_ruff_bin as _resolve_ruff_bin,
    ruff_version_string,
)


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def resolve_ruff_bin() -> Path | None:
    """Canonical Ruff discovery (shared with runtime attestation)."""
    return _resolve_ruff_bin(root=ROOT)


def ruff_version(bin_path: Path) -> str:
    return ruff_version_string(bin_path, cwd=ROOT)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", nargs="*", default=[], help="explicit changed paths")
    ap.add_argument(
        "--ruff-bin",
        default=None,
        help="optional explicit ruff binary (tests / pinned env)",
    )
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.paths]
    if not paths:
        try:
            base = subprocess.check_output(["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, text=True).strip()
            out = subprocess.check_output(["git", "diff", "--name-only", base], cwd=ROOT, text=True)
            paths = [Path(p) for p in out.splitlines() if p.strip()]
        except Exception:  # noqa: BLE001
            print("NOT_APPLICABLE: no paths and merge-base unavailable")
            return 0

    rc = 0
    existing = [p for p in paths if p.exists()]
    if existing:
        if _run(["git", "diff", "--check", *[str(p) for p in existing]]) != 0:
            rc = 1

    py = [p for p in paths if p.suffix == ".py" and p.exists()]
    if py:
        ruff_bin = Path(args.ruff_bin) if args.ruff_bin else resolve_ruff_bin()
        if ruff_bin is None or not Path(ruff_bin).is_file():
            print("BLOCKED: ruff not installed but changed Python files exist")
            print("required_pinned_ruff=", PINNED_RUFF_VERSION)
            print("python_paths=", " ".join(str(p) for p in py))
            return 2
        ver = ruff_version(Path(ruff_bin))
        print(f"ruff_bin={ruff_bin} version={ver} pinned={PINNED_RUFF_VERSION}")
        if _run([str(ruff_bin), "check", *[str(p) for p in py]]) != 0:
            rc = 1
        if _run([str(ruff_bin), "format", "--check", *[str(p) for p in py]]) != 0:
            print("BLOCKED: ruff format --check failed on changed Python paths")
            rc = 1
    else:
        print("NOT_APPLICABLE: no python paths")

    if any("agent_clients" in str(p) for p in paths):
        from scripts.lib.agent_clients_registry import load_registry, validate_registry

        errs = validate_registry(load_registry())
        if errs:
            print("FAIL registry", errs)
            rc = 1
        else:
            print("PASS agent_clients registry")

    if (ROOT / "scripts" / "check_no_secrets.py").is_file():
        if _run([sys.executable, "scripts/check_no_secrets.py"]) != 0:
            rc = 1
    else:
        print("NOT_APPLICABLE: check_no_secrets.py missing")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
