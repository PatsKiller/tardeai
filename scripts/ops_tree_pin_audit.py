#!/usr/bin/env python3
"""Classify systemd user units + crontab by execution tree.

READ_ONLY_ADVISORY. Observability only — does not rewrite units.

Serve is CURRENT (or the exact SHA CURRENT points at). Automation that still
runs from trade-ai-v12-rebuild, a hybrid CURRENT-script + rebuild-venv, or a
leftover worktree is drift.

Exit 0: report written.
Exit 1: --strict and any TradeAI unit/cron is rebuild/hybrid/worktree.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
CURRENT_HOME = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
REBUILD_MARKERS = ("trade-ai-v12-rebuild",)
CURRENT_MARKERS = ("trade-ai-releases/portfolio-server", "/CURRENT")
WORKTREE_MARKERS = ("tradeai-wt-", "tardeai-wt-", "/tradeai-wt")
TRADEAI_NAME_PREFIXES = (
    "tradeai-",
    "trade-ai-",
    "hermes-",
    "cio-",
    "aegis-",
    "portfolio-",
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def classify_text(text: str) -> str:
    blob = text or ""
    has_reb = any(m in blob for m in REBUILD_MARKERS)
    has_cur = any(m in blob for m in CURRENT_MARKERS)
    has_wt = any(m in blob for m in WORKTREE_MARKERS)
    if has_reb and has_cur:
        return "hybrid"
    if has_wt and (has_reb or has_cur):
        return "hybrid"
    if has_wt:
        return "worktree"
    if has_reb:
        return "rebuild"
    if has_cur:
        return "current"
    return "other"


def _is_tradeai_unit(name: str) -> bool:
    n = name.lower()
    return any(n.startswith(p) for p in TRADEAI_NAME_PREFIXES)


def scan_units(unit_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not unit_dir.is_dir():
        return rows
    for path in sorted(unit_dir.glob("*.service")) + sorted(unit_dir.glob("*.timer")):
        text = _read(path)
        drop = path.parent / (path.name + ".d")
        extra = ""
        if drop.is_dir():
            for conf in sorted(drop.glob("*.conf")):
                extra += "\n" + _read(conf)
        blob = text + extra
        rows.append({
            "kind": "unit",
            "name": path.name,
            "path": str(path),
            "tradeai": _is_tradeai_unit(path.name),
            "class": classify_text(blob),
        })
    return rows


def scan_crontab(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(text.splitlines(), 1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        rows.append({
            "kind": "cron",
            "name": f"crontab:{i}",
            "path": f"crontab:{i}",
            "tradeai": True,
            "class": classify_text(line),
            "line": raw[:240],
        })
    return rows


def load_crontab(path: Path | None) -> str:
    if path is not None:
        return _read(path)
    try:
        proc = subprocess.run(
            ["crontab", "-l"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return f"# crontab -l failed: {exc}\n"
    if proc.returncode != 0:
        return f"# crontab -l rc={proc.returncode}\n{proc.stderr}"
    return proc.stdout


def current_stamp(current: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "current_path": str(current),
        "resolved": str(current.resolve()) if current.exists() else None,
    }
    sha = current / "SOURCE_COMMIT"
    if sha.exists():
        out["source_commit"] = sha.read_text(encoding="utf-8").strip()[:40]
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tradeai = [r for r in rows if r.get("tradeai")]
    counts = Counter(r["class"] for r in tradeai)
    drift = [r for r in tradeai if r["class"] in {"rebuild", "hybrid", "worktree"}]
    return {
        "tradeai_n": len(tradeai),
        "by_class": dict(counts),
        "drift_n": len(drift),
        "drift_samples": [
            {"name": r["name"], "class": r["class"], "path": r["path"]}
            for r in drift[:40]
        ],
    }


def build_report(*, unit_dir: Path, crontab_text: str, current: Path) -> dict[str, Any]:
    units = scan_units(unit_dir)
    crons = scan_crontab(crontab_text)
    rows = units + crons
    return {
        "schema": "OpsTreePinAudit@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "current": current_stamp(current),
        "unit_dir": str(unit_dir),
        "units": summarize(units),
        "crontab": summarize(crons),
        "combined": summarize(rows),
        "policy": (
            "Pin TradeAI units/cron to ~/trade-ai-releases/portfolio-server/CURRENT "
            "(or the exact SHA it resolves to). Hybrids (CURRENT script + rebuild venv) "
            "are drift. Do not treat a feature-branch rebuild tree as serve."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audit systemd/cron tree pinning (read-only)")
    p.add_argument("--unit-dir", type=Path, default=Path.home() / ".config/systemd/user")
    p.add_argument("--crontab", type=Path, default=None, help="crontab dump (default: crontab -l)")
    p.add_argument("--current", type=Path, default=CURRENT_HOME)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 if TradeAI rebuild/hybrid/worktree drift")
    args = p.parse_args(argv)
    report = build_report(
        unit_dir=args.unit_dir,
        crontab_text=load_crontab(args.crontab),
        current=args.current,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        comb = report["combined"]
        print(f"tree-pin audit  current={report['current'].get('source_commit')}")
        print(f"  tradeai={comb['tradeai_n']} by_class={comb['by_class']} drift={comb['drift_n']}")
        for s in comb["drift_samples"][:15]:
            print(f"  DRIFT {s['class']:8} {s['name']}")
        if comb["drift_n"] > 15:
            print(f"  … {comb['drift_n'] - 15} more")
    if args.strict and int(report["combined"]["drift_n"] or 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
