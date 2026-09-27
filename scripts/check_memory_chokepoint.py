#!/usr/bin/env python3
"""check_memory_chokepoint.py — Ring 1 of the Memory Enforcement Layer (01 §2).

Every read or write of platform memory goes through ``scripts/lib/intelligence_client.py``. A direct
import of one of the nine memory silos anywhere else is a violation. Today's violations are recorded
in ``config/memory_chokepoint_baseline.json`` and the baseline may only SHRINK: a NEW file or a file
whose count GREW fails (exit 1). This is the same ratchet as check_telegram_chokepoint.py and
check_provider_chokepoint.py, and the same precedent as the lane registry's undeclared baseline.

Violation classes (static, .py only, repo-only inputs):
  silo_import   ``import <silo>`` / ``from <silo> import`` / ``from scripts.lib.<silo> import``
                for a silo in SILOS, outside the façade and the approved tooling.

Usage:
    python3 scripts/check_memory_chokepoint.py             # ratchet against the baseline (CI)
    python3 scripts/check_memory_chokepoint.py --report    # print every hit
    python3 scripts/check_memory_chokepoint.py --update-baseline   # record current debt (review the diff)

AUTHORITY: READ_ONLY_ADVISORY. Static analysis only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
BASELINE = PROJ / "config" / "memory_chokepoint_baseline.json"
SCAN_DIRS = ("scripts", "apps", "tests")

# The nine silos the façade absorbs (01 §2.2) plus their direct readers/writers.
SILOS = (
    "agent_durable_memory", "agent_memory_provider", "agent_memory_admission", "agent_memory_governance",
    "memory_m2_v2", "cio_memory_integration", "memory_prod_cutover",
    "aec_memory_spines", "comms.subject_memory", "subject_memory",
    "advisory.advisory_memory", "advisory_memory",
    "health_root_cause_memory", "semantic_operator_memory", "comms_memory",
    "research_governance.durable_store", "memory_grounding", "memory_consumption_receipt",
)

# The façade itself and the tooling that legitimately touches silos directly: the providers' own
# modules, admission, the shadow measure, the belief writer, tests of those modules, and the
# checker. Everything else is debt.
APPROVED = {
    "scripts/lib/intelligence_client.py",
    "scripts/check_memory_chokepoint.py",
}
APPROVED_PREFIXES = (
    "scripts/lib/agent_durable_memory.py", "scripts/lib/agent_memory_provider.py",
    "scripts/lib/agent_memory_admission.py", "scripts/lib/agent_memory_governance.py",
    "scripts/lib/memory_m2_v2.py", "scripts/lib/cio_memory_integration.py", "scripts/lib/memory_prod_cutover.py",
    "scripts/lib/aec_memory_spines.py", "scripts/lib/comms/subject_memory.py", "scripts/lib/advisory/advisory_memory.py",
    "scripts/lib/health_root_cause_memory.py", "scripts/lib/semantic_operator_memory.py", "scripts/lib/comms_memory.py",
    "scripts/lib/research_governance/durable_store.py", "scripts/lib/memory_grounding.py",
    "scripts/lib/memory_consumption_receipt.py",
    "scripts/memory_admin.py", "scripts/lib/agent_memory_shadow_measure.py", "scripts/run_memory_shadow_measure.py",
    "scripts/lib/cross_agent_memory_agreement.py", "scripts/lib/memory_shadow_projector.py",
)

_MOD = "|".join(re.escape(s) for s in SILOS)
PATTERNS = [
    re.compile(rf"^\s*import\s+(?:scripts\.lib\.)?(?:{_MOD})\b", re.M),
    re.compile(rf"^\s*from\s+(?:scripts\.lib\.)?(?:{_MOD})\s+import\b", re.M),
    re.compile(rf"^\s*from\s+(?:scripts\.)?lib\s+import\s+(?:{_MOD})\b", re.M),
    re.compile(rf"__import__\(\s*['\"](?:scripts\.lib\.)?(?:{_MOD})['\"]", re.M),
]


def _files() -> list[Path]:
    out: list[Path] = []
    for d in SCAN_DIRS:
        base = PROJ / d
        if base.exists():
            out += [p for p in base.rglob("*.py") if "node_modules" not in p.parts and "archive" not in p.parts]
    return sorted(out)


def _approved(rel: str) -> bool:
    return rel in APPROVED or any(rel == p or rel.startswith(p) for p in APPROVED_PREFIXES)


def scan() -> dict[str, int]:
    hits: dict[str, int] = {}
    for p in _files():
        rel = p.relative_to(PROJ).as_posix()
        if _approved(rel):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = sum(len(pat.findall(text)) for pat in PATTERNS)
        if n:
            hits[rel] = n
    return hits


def load_baseline() -> dict | None:
    if not BASELINE.exists():
        return None
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def ratchet(current: dict[str, int], baseline: dict[str, int]) -> tuple[list[str], list[str]]:
    new = [f for f in current if f not in baseline]
    grew = [f for f, n in current.items() if f in baseline and n > baseline[f]]
    return sorted(new), sorted(grew)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    current = scan()
    if args.update_baseline:
        BASELINE.write_text(json.dumps({
            "_note": "Ring 1 memory chokepoint debt. May only shrink. Regenerate with "
                     "scripts/check_memory_chokepoint.py --update-baseline and review the diff "
                     "(01 §2, pkg-20260927-cogx-w1-d9e1).",
            "silos": list(SILOS),
            "files": dict(sorted(current.items())),
            "total": sum(current.values()),
        }, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        print(f"baseline written: {len(current)} files, {sum(current.values())} direct silo imports")
        return 0
    if args.json:
        print(json.dumps({"files": current, "total": sum(current.values())}, indent=2, sort_keys=True))
        return 0
    if args.report:
        for f, n in sorted(current.items()):
            print(f"{n:3d}  {f}")
        print(f"total {sum(current.values())} in {len(current)} files")
        return 0
    base = load_baseline()
    if base is None:
        print("memory chokepoint: NO BASELINE — run --update-baseline once to record current debt.", file=sys.stderr)
        return 1
    new, grew = ratchet(current, base.get("files", {}))
    if new or grew:
        for f in new:
            print(f"memory chokepoint: NEW direct silo import in {f} ({current[f]}) — read/write memory through scripts/lib/intelligence_client.py", file=sys.stderr)
        for f in grew:
            print(f"memory chokepoint: GREW {f}: {base['files'][f]} -> {current[f]}", file=sys.stderr)
        return 1
    shrunk = sum(base.get("files", {}).values()) - sum(current.values())
    print(f"memory chokepoint: OK ({sum(current.values())} direct imports in {len(current)} files; baseline {base.get('total')}; shrunk by {shrunk})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
