#!/usr/bin/env python3
"""check_docs_drive_parity.py — v1.1 P9: alert when canonical lifecycle docs are
missing or stale in the Drive sync manifest. Piggybacks the hourly
sync-docs-to-drive.sh (gog) manifest — read-only; exit 1 + stderr line on drift
so the health surface can alarm."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path.home() / ".local" / "state" / "drive-sync-manifest.txt"
CANONICAL = [
    "docs/OPTIONS_LIFECYCLE_DESK.md",
    "docs/_findings/OPTIONS_LIFECYCLE_DESK_DIAGNOSIS_2026-07-19.md",
    "docs/_findings/OPTIONS_LIFECYCLE_V1_1_INTEGRATION_AUDIT_2026-07-19.md",
    "docs/runbooks/OPTIONS_FIRST_POSITION_ACCEPTANCE.md",
    "docs/COST_INTELLIGENCE_ARCHITECTURE.md",
    "docs/options-module.md",
    "docs/DOCUMENTATION_INDEX.md",
    "docs/CHANGELOG.md",
]
HASH_STATE = Path.home() / ".local" / "state" / "docs-parity-hashes.json"
STALE_HOURS = 26   # hourly sync + slack


def main() -> int:
    import hashlib, json
    problems = []
    manifest = MANIFEST.read_text() if MANIFEST.exists() else ""
    manifest_mtime = MANIFEST.stat().st_mtime if MANIFEST.exists() else 0
    state = json.loads(HASH_STATE.read_text()) if HASH_STATE.exists() else {}
    for rel in CANONICAL:
        p = ROOT / rel
        if not p.exists():
            problems.append(f"MISSING IN REPO: {rel}")
            continue
        if Path(rel).name not in manifest:
            problems.append(f"NOT IN DRIVE MANIFEST yet: {rel} (next hourly sync should pick it up; "
                            "alarm only if this persists)")
            continue
        # CONTENT parity: hash recorded when the doc was last covered by a sync
        # (manifest newer than the file). A doc changed after the last sync =
        # content drift until the next sync re-covers it.
        cur_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        if p.stat().st_mtime <= manifest_mtime:
            state[rel] = {"hash": cur_hash, "synced_hash_at": manifest_mtime}
        else:
            rec = state.get(rel, {})
            if rec.get("hash") != cur_hash:
                problems.append(f"CONTENT DRIFT since last sync: {rel} "
                                f"(local {cur_hash} vs synced {rec.get('hash', 'never')})")
    try:
        HASH_STATE.write_text(json.dumps(state, indent=1))
    except Exception:
        pass
    if MANIFEST.exists():
        age_h = (time.time() - MANIFEST.stat().st_mtime) / 3600
        if age_h > STALE_HOURS:
            problems.append(f"Drive sync manifest {age_h:.0f}h old (> {STALE_HOURS}h) — sync cron may be dead")
    else:
        problems.append("Drive sync manifest absent — sync has never run on this host?")
    if problems:
        print("DOCS↔DRIVE PARITY: DRIFT", file=sys.stderr)
        for x in problems:
            print(" -", x)
        return 1
    print(f"DOCS↔DRIVE PARITY: OK ({len(CANONICAL)} canonical docs tracked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
