"""
db_patch_remaining.py — Patches delta_tracker.py and trade_ai_orchestrator.py
Run once from project root after deploying db_adapter.py:
    python3 linux/db_patch_remaining.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"

def patch_file(name, patches):
    path = SCRIPTS / name
    if not path.exists():
        print(f"  SKIP: {name} not found")
        return
    content = path.read_text(encoding="utf-8")
    changed = False
    for old, new, label in patches:
        if old in content:
            content = content.replace(old, new)
            print(f"  ✓ {name}: {label}")
            changed = True
        elif new in content:
            print(f"  ✓ {name}: {label} (already patched)")
        else:
            print(f"  ⚠ {name}: could not find '{label}' block")
    if changed:
        path.write_text(content, encoding="utf-8")

# ── delta_tracker.py ──────────────────────────────────────────────────────────
patch_file("delta_tracker.py", [
    (
        "import os",
        "import os\ntry:\n    from db_adapter import load_state as _db_load_state, save_state as _db_save_state\nexcept ImportError:\n    _db_load_state = None\n    _db_save_state = None",
        "add db_adapter import"
    ),
    (
        '''            return json.loads(path.read_text(encoding="utf-8"))''',
        '''            # Try db_adapter first (PostgreSQL on Linux)
            if _db_load_state:
                data = _db_load_state(path)
                if data:
                    return data
            return json.loads(path.read_text(encoding="utf-8"))''',
        "patch load_state"
    ),
    (
        '''    path.write_text(json.dumps(state, indent=2), encoding="utf-8")''',
        '''    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    # Also persist via db_adapter (PostgreSQL on Linux)
    if _db_save_state:
        _db_save_state(state, path)''',
        "patch save_state"
    ),
])

# ── trade_ai_orchestrator.py ──────────────────────────────────────────────────
patch_file("trade_ai_orchestrator.py", [
    (
        "from pathlib import Path",
        "from pathlib import Path\ntry:\n    from db_adapter import save_run_summary as _db_save_run_summary\nexcept ImportError:\n    _db_save_run_summary = None",
        "add db_adapter import"
    ),
    (
        '''        (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))''',
        '''        (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))
        # Also persist via db_adapter (PostgreSQL on Linux)
        if _db_save_run_summary:
            _db_save_run_summary(summary, output_dir / "run_summary.json")''',
        "patch save run_summary"
    ),
])

print("\nDone. All remaining scripts patched for db_adapter.")
