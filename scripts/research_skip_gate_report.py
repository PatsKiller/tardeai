#!/usr/bin/env python3
"""Read-only counts from data/cio/research_skip_ledger.jsonl.

Code default RESEARCH_SKIP_GATE stays 0 (off). Live crontab should prefix
`env RESEARCH_SKIP_GATE=1` — parent applies crontab; this script does not.

If the ledger is missing or empty: print "ledger empty / gate off".
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMPTY_MSG = "ledger empty / gate off"


def ledger_file(*, root: Path | None = None) -> Path:
    env = (os.getenv("RESEARCH_SKIP_LEDGER_PATH") or "").strip()
    if env:
        return Path(env)
    return (root or ROOT) / "data" / "cio" / "research_skip_ledger.jsonl"


def counts_by_code(path: Path) -> dict[str, int]:
    by: Counter[str] = Counter()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        code = row.get("code")
        if code:
            by[str(code)] += 1
    return dict(by)


def render_report(path: Path) -> str:
    if not path.is_file():
        return EMPTY_MSG
    by = counts_by_code(path)
    if not by:
        return EMPTY_MSG
    total = sum(by.values())
    lines = [
        json.dumps(
            {"path": str(path), "total": total, "by_code": by},
            indent=2,
            sort_keys=True,
        )
    ]
    for code, n in sorted(by.items()):
        lines.append(f"{code}\t{n}")
    lines.append(f"total\t{total}")
    return "\n".join(lines)


def main() -> int:
    path = ledger_file()
    print(render_report(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
