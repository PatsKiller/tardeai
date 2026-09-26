#!/usr/bin/env python3
"""Fail on NEW hardcoded live-host paths in tests.

A test that names ``/home/johnclaw/trade-ai-releases/...`` or the dev tree by
absolute path reads live host state: it passes or fails depending on what is
deployed, not on the code under test. On 2026-09-25 PR #1234's
``tests/test_worker_pin_and_alert_freshness_20260925.py`` went red on its own
head for exactly this reason when an unrelated release was promoted. CI runs on
a clean GitHub runner, where those paths do not exist at all.

Use ``tmp_path`` fixtures (fake release dirs, fake ``CURRENT`` symlinks) and
monkeypatch the module constant or env var the code reads instead.

The files that already do this are a named baseline (``config/test_host_path_baseline.json``,
file -> occurrence count). The baseline may only shrink: a new file, or more
occurrences in a listed file, fails ``--fail-on-new``.

    python3 scripts/check_test_host_paths.py --fail-on-new
    python3 scripts/check_test_host_paths.py --write-baseline   # after REMOVING occurrences only
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

NO_CONSUMER_REASON = (
    "this IS the guard; CI (cio-hardening) and ai_local_acceptance.sh invoke it, nothing imports it. "
    "TestHostPathBaseline@v1 is its own baseline file."
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config" / "test_host_path_baseline.json"
PATTERN = re.compile(r"/home/johnclaw/(?:trade-ai-releases|trade-ai-v12-rebuild)\b")


def scan(root: Path = ROOT) -> dict[str, int]:
    found: dict[str, int] = {}
    for p in sorted((root / "tests").rglob("*.py")):
        try:
            n = len(PATTERN.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        if n:
            found[p.relative_to(root).as_posix()] = n
    return found


def load_baseline(path: Path = BASELINE) -> dict[str, int]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in (data.get("files") or {}).items()}


def new_violations(found: dict[str, int], baseline: dict[str, int]) -> list[str]:
    out = []
    for f, n in sorted(found.items()):
        allowed = baseline.get(f, 0)
        if n > allowed:
            out.append(f"{f}: {n} live-host path(s), baseline allows {allowed}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--fail-on-new", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args(argv)
    found = scan()
    if args.write_baseline:
        BASELINE.write_text(
            json.dumps(
                {
                    "schema": "TestHostPathBaseline@v1",
                    "note": "Inherited tests that read live host paths. May only shrink; see scripts/check_test_host_paths.py.",
                    "files": found,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {BASELINE.relative_to(ROOT)} ({len(found)} files)")
        return 0
    bad = new_violations(found, load_baseline())
    baseline = load_baseline()
    print(f"test host paths: {len(found)} files (baseline {len(baseline)}), new violations: {len(bad)}")
    for line in bad:
        print(f"  NEW: {line}")
    return 1 if (bad and args.fail_on_new) else 0


if __name__ == "__main__":
    raise SystemExit(main())
